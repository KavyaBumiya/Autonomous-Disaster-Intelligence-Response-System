"""
Open-Meteo poller — runs every 5 minutes per active zone.
Stores readings in weather_readings table and updates zone risk scores.

Phase 2 rewrite: delegates retrieval to WeatherService (single Open-Meteo
owner, Redis-cached, connector-level retry). Two live bugs fixed:
    1. rainfall used hourly[-1] (last forecast hour) → now current precipitation
    2. windspeed (already km/h) was multiplied by 3.6 → now used as-is

Provider failures: zone is skipped (existing behavior); the connector
registry marks open-meteo DEGRADED/OFFLINE for /api/health (§31).
"""
import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.integrations.base import ConnectorError
from app.models.weather import WeatherReading
from app.models.zone import Zone
from app.pollers import log_poller_cancelled
from app.services.weather_service import weather_service

logger = structlog.get_logger()


def _compute_risk_score(rainfall_mm_hr: float, wind_speed_kmh: float, weather_main: str) -> float:
    """Normalised 0.0–1.0 risk score from weather data.

    Wind thresholds are km/h (Open-Meteo unit — verified live).
    """
    score = 0.0
    # Rainfall contribution
    if rainfall_mm_hr >= 100:
        score += 0.5
    elif rainfall_mm_hr >= 50:
        score += 0.35
    elif rainfall_mm_hr >= 20:
        score += 0.2
    elif rainfall_mm_hr >= 5:
        score += 0.1

    # Wind contribution
    if wind_speed_kmh >= 120:
        score += 0.4
    elif wind_speed_kmh >= 80:
        score += 0.25
    elif wind_speed_kmh >= 40:
        score += 0.1

    # Weather condition boost
    if weather_main in ("Thunderstorm", "Tornado"):
        score += 0.1
    elif weather_main in ("Snow", "Extreme"):
        score += 0.05

    return min(score, 1.0)


async def poll_weather() -> None:
    """Poll weather for all active zones and store results.

    Emits `weather.updated` (§25) only when a zone's risk score actually
    changed since its previous reading — throttled by design."""
    try:
        await _poll_weather_inner()
    except asyncio.CancelledError:
        # App shutdown cancelled this run (usually mid provider read or Redis
        # GET). Expected, not a provider fault — log and re-raise so task
        # cancellation semantics stay intact.
        log_poller_cancelled("weather")
        raise


async def _poll_weather_inner() -> None:
    async with AsyncSessionLocal() as db:
        # Soft-deleted zones are excluded everywhere else in the codebase
        # (heatmaps, zones API, route intelligence). Polling them anyway keeps
        # burning Open-Meteo quota every 5 minutes -- pushing a shared Render
        # egress IP further toward the 429 -- and keeps emitting
        # weather.updated for zones the operator removed.
        result = await db.execute(select(Zone).where(Zone.deleted == False))  # noqa: E712
        zones = result.scalars().all()

        if not zones:
            logger.info("weather_poll_no_zones", hint="no live zones; weather panel empty")
            return

        # Latest risk per zone (DISTINCT ON — one row per zone) for throttling
        prev_by_zone: dict[str, float] = {}
        try:
            rows = (
                await db.execute(
                    select(WeatherReading.zone_id, WeatherReading.risk_score)
                    .where(WeatherReading.zone_id.in_([z.id for z in zones]))
                    .distinct(WeatherReading.zone_id)
                    .order_by(WeatherReading.zone_id, WeatherReading.polled_at.desc())
                )
            ).all()
            prev_by_zone = {zid: float(rs) for zid, rs in rows if zid}
        except Exception as exc:  # noqa: BLE001
            logger.warning("weather_prev_risk_lookup_failed", error=str(exc))

        pending_emits: list[tuple[str, float, float | None, dict]] = []

        for zone in zones:
            try:
                # Fresh fetch only — never persist stale/cached weather as new.
                obs = await weather_service.get_current_weather(
                    zone.centroid_lat, zone.centroid_lng, allow_stale=False
                )

                wind = obs.wind_speed_kmh or 0.0
                risk = _compute_risk_score(obs.rainfall_mm_hr, wind, obs.weather_main)

                reading = WeatherReading(
                    id=str(uuid.uuid4()),
                    zone_id=zone.id,
                    lat=zone.centroid_lat,
                    lng=zone.centroid_lng,
                    rainfall_mm_hr=obs.rainfall_mm_hr,
                    wind_speed_kmh=wind,
                    temperature_c=obs.temperature_c,
                    # Stored so the occurrence models have pressure and humidity
                    # to read. Both stay None when the provider omits them: a
                    # plausible-looking substitute would be an invented reading,
                    # and the models refuse to score on a missing feature anyway.
                    humidity_pct=obs.humidity_pct,
                    pressure_hpa=obs.pressure_hpa,
                    weather_main=obs.weather_main,
                    weather_description=obs.weather_description,
                    risk_score=risk,
                    polled_at=datetime.now(timezone.utc),
                )
                db.add(reading)
                logger.debug(
                    "Weather polled",
                    zone=zone.id,
                    rainfall=obs.rainfall_mm_hr,
                    wind=wind,
                    risk=risk,
                )

                prev = prev_by_zone.get(zone.id)
                if prev is None or abs(risk - float(prev)) > 1e-9:
                    pending_emits.append(
                        (
                            zone.id,
                            risk,
                            prev,
                            {
                                "rainfall_mm_hr": obs.rainfall_mm_hr,
                                "wind_speed_kmh": wind,
                                "weather_main": obs.weather_main,
                                "weather_description": obs.weather_description,
                            },
                        )
                    )

            except ConnectorError as e:
                logger.warning(
                    "Weather provider unavailable — zone skipped",
                    zone=zone.id,
                    provider=e.provider,
                    error=e.message,
                )
            except Exception as e:
                logger.warning("Weather poll failed for zone", zone=zone.id, error=str(e))

        await db.commit()

        # After commit — emit only queued risk-score changes (§25 throttled)
        for zone_id, risk, prev, data in pending_emits:
            try:
                from app.services.websocket import emit_weather_updated

                await emit_weather_updated(zone_id, risk, prev, data)
            except Exception as exc:  # noqa: BLE001
                logger.warning("weather_updated_emit_failed", zone=zone_id,
                               error=str(exc))
