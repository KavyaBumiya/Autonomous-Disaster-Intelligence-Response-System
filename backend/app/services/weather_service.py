"""
WeatherService — backend-owned weather retrieval (PRD §6).

Single entrypoint for the poller, prediction engine, API endpoints and
AI tools — nobody calls Open-Meteo directly anymore.

Capabilities:
    get_current_weather(lat, lng, allow_stale=False) -> WeatherObservation
    get_forecast(lat, lng, hours=24, allow_stale=False) -> ForecastResult
    get_historical_weather(lat, lng, start, end) -> ForecastResult

Provider fallback (§31): Open-Meteo is primary; when it fails (shared cloud
egress IPs hit its per-IP rate limits → HTTP 429), MET Norway Locationforecast
serves real model data labelled source="met-norway". The fallback is live
data — allowed even when allow_stale=False. Only when BOTH sources fail do
we serve stale cache or raise the distinct "nothing fabricated" error.

Caching (§27):
    weather:{lat:.4f}:{lng:.4f}         fresh cache   TTL 300 s
    weather:{lat:.4f}:{lng:.4f}:latest  stale fallback TTL 24 h
    forecast:{lat}:{lng}:{hours}          fresh cache   TTL 30 min
    forecast:{lat}:{lng}:{hours}:latest   stale fallback TTL 24 h

Failure policy (§31):
    allow_stale=False → ConnectorError propagates when no source works
                        (poller skips the zone)
    allow_stale=True  → stale cache returned with from_cache=True, or
                        ConnectorError if no cache exists.
    Weather is NEVER fabricated.
"""
from __future__ import annotations


import structlog

from app.integrations import cache
from app.integrations.base import ConnectorError
from app.integrations.weather.met_norway import MetNorwayConnector
from app.integrations.weather.open_meteo import OpenMeteoConnector
from app.schemas.observations import ForecastResult, WeatherObservation

logger = structlog.get_logger()

FRESH_TTL_SECONDS = 300          # §27 weather:{lat}:{lng}
LATEST_TTL_SECONDS = 86400       # stale fallback — honest label, 24 h


class WeatherService:
    def __init__(
        self,
        connector: OpenMeteoConnector | None = None,
        fallback: MetNorwayConnector | None = None,
    ) -> None:
        self._connector = connector or OpenMeteoConnector()
        self._fallback = fallback or MetNorwayConnector()

    # ── keys ─────────────────────────────────────────────────────────────

    @staticmethod
    def _fresh_key(lat: float, lng: float) -> str:
        return f"weather:{lat:.4f}:{lng:.4f}"

    @staticmethod
    def _latest_key(lat: float, lng: float) -> str:
        return f"weather:{lat:.4f}:{lng:.4f}:latest"

    # ── current ──────────────────────────────────────────────────────────

    async def get_current_weather(
        self, lat: float, lng: float, *, allow_stale: bool = False
    ) -> WeatherObservation:
        fresh_key = self._fresh_key(lat, lng)

        cached = await cache.cache_get(fresh_key)
        if cached:
            try:
                return WeatherObservation(**{**cached, "from_cache": True})
            except (TypeError, ValueError):
                logger.warning("weather_cache_invalid", key=fresh_key)

        try:
            obs = await self._connector.get_current_weather(lat, lng)
        except ConnectorError as exc:
            # Fallback source (§31): real MET Norway data when Open-Meteo is
            # unavailable — live data, allowed even when allow_stale=False.
            try:
                obs = await self._fallback.get_current_weather(lat, lng)
            except ConnectorError:
                obs = None
                if not allow_stale:
                    raise exc  # headline error stays the primary provider's
            else:
                logger.warning(
                    "weather_fallback_used",
                    primary=exc.provider,
                    fallback=self._fallback.provider,
                    error=exc.message,
                )
            if obs is None:
                stale = await cache.cache_get(self._latest_key(lat, lng))
                if stale:
                    logger.warning(
                        "weather_stale_served",
                        provider=getattr(self._connector, "provider", "open-meteo"),
                        age_hint=stale.get("timestamp"),
                        error=exc.message,
                    )
                    try:
                        return WeatherObservation(**{**stale, "from_cache": True})
                    except (TypeError, ValueError):
                        pass
                # §31 distinct "no cache" message — never fabricate readings.
                raise ConnectorError(
                    exc.provider,
                    f"{exc.message} (no cached weather available for this "
                    f"location — DEGRADED, nothing fabricated)",
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc

        payload = obs.model_dump(mode="json")
        await cache.cache_set(fresh_key, payload, FRESH_TTL_SECONDS)
        await cache.cache_set(self._latest_key(lat, lng), payload, LATEST_TTL_SECONDS)
        return obs

    # ── forecast ─────────────────────────────────────────────────────────

    async def get_forecast(
        self, lat: float, lng: float, hours: int = 24, *, allow_stale: bool = False
    ) -> ForecastResult:
        key = f"forecast:{lat:.4f}:{lng:.4f}:{hours}"
        latest_key = f"{key}:latest"
        cached = await cache.cache_get(key)
        if cached:
            try:
                return ForecastResult(**{**cached, "from_cache": True})
            except (TypeError, ValueError):
                logger.warning("forecast_cache_invalid", key=key)

        try:
            result = await self._connector.get_forecast(lat, lng, hours)
        except ConnectorError as exc:
            # Fallback source first (real live MET Norway forecast), then
            # the stale sibling (mirrors get_current_weather): real cached
            # data, honestly labelled from_cache — never fabricated (§31).
            try:
                result = await self._fallback.get_forecast(lat, lng, hours)
            except ConnectorError:
                result = None
                if not allow_stale:
                    raise exc  # headline error stays the primary provider's
            else:
                logger.warning(
                    "weather_fallback_used",
                    primary=exc.provider,
                    fallback=self._fallback.provider,
                    error=exc.message,
                )
            if result is None:
                stale = await cache.cache_get(latest_key)
                if stale:
                    try:
                        fr = ForecastResult(**{**stale, "from_cache": True})
                        logger.warning(
                            "forecast_stale_served",
                            provider=getattr(self._connector, "provider", "open-meteo"),
                            key=latest_key,
                            error=exc.message,
                        )
                        return fr
                    except (TypeError, ValueError):
                        logger.warning("forecast_stale_invalid", key=latest_key)
                raise ConnectorError(
                    exc.provider,
                    f"{exc.message} (no cached forecast available for this "
                    f"location — DEGRADED, nothing fabricated)",
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                ) from exc

        payload = result.model_dump(mode="json")
        await cache.cache_set(key, payload, FRESH_TTL_SECONDS * 6)
        await cache.cache_set(latest_key, payload, LATEST_TTL_SECONDS)
        return result

    # ── historical (ERA5) ────────────────────────────────────────────────

    async def get_historical_weather(
        self, lat: float, lng: float, start_date: str, end_date: str
    ) -> ForecastResult:
        key = f"weather_hist:{lat:.4f}:{lng:.4f}:{start_date}:{end_date}"
        cached = await cache.cache_get(key)
        if cached:
            try:
                return ForecastResult(**{**cached, "from_cache": True})
            except (TypeError, ValueError):
                logger.warning("weather_history_cache_invalid", key=key)

        result = await self._connector.get_historical_weather(
            lat, lng, start_date, end_date
        )
        # Historical data is immutable — cache for a day.
        await cache.cache_set(key, result.model_dump(mode="json"), LATEST_TTL_SECONDS)
        return result

    @property
    def provider(self) -> str:
        return self._connector.provider


# Shared instance (pollers, services, and API handlers all import this).
weather_service = WeatherService()
