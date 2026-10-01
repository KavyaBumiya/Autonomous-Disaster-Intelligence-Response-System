"""
MET Norway Locationforecast 2.0 connector — fallback weather source.

Why a fallback exists (2026-09): the free Open-Meteo API is rate-limited per
IP (10k/day, 5k/h); on shared cloud egress IPs (Render) that quota is burned
by other tenants and the provider answers HTTP 429 for long stretches.
MET Norway's locationforecast is keyless, global, and cloud-friendly, so
WeatherService tries it whenever the primary source fails — real model data,
clearly labelled with source="met-norway" (never fabricated, §31).

Endpoints:
    GET {met_norway_base_url}/compact?lat=..&lon=..     current + hourly
    (identifying User-Agent header required by met.no usage policy)

Units (verified live):
    air_temperature °C   wind_speed m/s → converted to km/h
    precipitation_amount mm (per next_1_hours bucket)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError
from app.schemas.observations import ForecastResult, ForecastSlice, WeatherObservation

logger = structlog.get_logger()

_FORECAST_PATH = "/compact"

# met.no symbol_code (suffixes _day/_night/_polartwilight stripped) →
# (weather_main, weather_description) aligned with the WMO table in open_meteo.
_SYMBOL_EXACT: dict[str, tuple[str, str]] = {
    "clearsky": ("Clear", "Clear sky"),
    "fair": ("Clear", "Mainly clear"),
    "partlycloudy": ("Clouds", "Partly cloudy"),
    "cloudy": ("Clouds", "Overcast"),
    "fog": ("Fog", "Fog"),
    "freezingrain": ("Freezing Rain", "Freezing rain"),
    "freezingdrizzle": ("Freezing Drizzle", "Freezing drizzle"),
    "lightrain": ("Rain", "Light rain"),
    "rain": ("Rain", "Moderate rain"),
    "heavyrain": ("Rain", "Heavy rain"),
    "lightsnow": ("Snow", "Light snow"),
    "snow": ("Snow", "Moderate snow"),
    "heavysnow": ("Snow", "Heavy snow"),
    "lightsnowshowers": ("Snow Showers", "Light snow showers"),
    "snowshowers": ("Snow Showers", "Snow showers"),
    "heavysnowshowers": ("Snow Showers", "Heavy snow showers"),
    "lightrainshowers": ("Rain Showers", "Light rain showers"),
    "rainshowers": ("Rain Showers", "Rain showers"),
    "heavyrainshowers": ("Rain Showers", "Heavy rain showers"),
    "lightsleet": ("Snow", "Light sleet"),
    "sleet": ("Snow", "Sleet"),
    "heavysleet": ("Snow", "Heavy sleet"),
    "lightsleetshowers": ("Snow Showers", "Light sleet showers"),
    "sleetshowers": ("Snow Showers", "Sleet showers"),
    "heavysleetshowers": ("Snow Showers", "Heavy sleet showers"),
}

_SYMBOL_PREFIX: tuple[tuple[str, tuple[str, str]], ...] = (
    ("thunderstorm", ("Thunderstorm", "Thunderstorm")),
    ("lightthunderstorm", ("Thunderstorm", "Thunderstorm")),
    ("heavythunderstorm", ("Thunderstorm", "Thunderstorm")),
    ("heavyrainandsnow", ("Snow", "Rain and snow")),
    ("lightrainandsnow", ("Snow", "Rain and snow")),
)


def symbol_to_main_desc(symbol: str | None) -> tuple[str, str]:
    """met.no symbol_code → (weather_main, weather_description)."""
    if not symbol:
        return "Unknown", "Unknown condition"
    base = symbol.split("_", 1)[0] if "_" in symbol else symbol
    hit = _SYMBOL_EXACT.get(base)
    if hit:
        return hit
    for prefix, mapped in _SYMBOL_PREFIX:
        if base.startswith(prefix) or prefix in base:
            return mapped
    return "Unknown", "Unknown condition"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_time(raw: str | None) -> datetime:
    if raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class MetNorwayConnector(BaseConnector):
    provider = "met-norway"
    timeout_seconds = 10.0
    max_attempts = 2  # fallback traffic — fail over quickly

    def __init__(self, base_url: str | None = None, user_agent: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.met_norway_base_url).rstrip("/")
        self.user_agent = user_agent or settings.met_norway_user_agent

    async def _compact(self, lat: float, lng: float) -> dict[str, Any]:
        data = await self.get_json(
            _FORECAST_PATH,
            params={"lat": f"{lat:.4f}", "lon": f"{lng:.4f}"},
            headers={"User-Agent": self.user_agent},
        )
        if not isinstance(data, dict):
            raise ConnectorError(self.provider, "unexpected payload type", retryable=False)
        return data

    # ── Current conditions → WeatherObservation ─────────────────────────

    async def get_current_weather(self, lat: float, lng: float) -> WeatherObservation:
        data = await self._compact(lat, lng)
        series = ((data.get("properties") or {}).get("timeseries")) or []
        if not series or not isinstance(series[0], dict):
            raise ConnectorError(
                self.provider, "missing 'properties.timeseries'", retryable=False
            )

        entry = series[0]
        block = entry.get("data") or {}
        instant = (block.get("instant") or {}).get("details") or {}
        next_1h = block.get("next_1_hours") or {}
        precip = ((next_1h.get("details") or {}).get("precipitation_amount")) or 0.0
        symbol = ((next_1h.get("summary") or {}).get("symbol_code")) or (
            ((block.get("next_12_hours") or {}).get("summary") or {}).get("symbol_code")
        )
        main, desc = symbol_to_main_desc(symbol)

        wind_ms = _safe_float(instant.get("wind_speed"))
        return WeatherObservation(
            source=self.provider,
            observation_type="weather",
            latitude=float(lat),
            longitude=float(lng),
            timestamp=_parse_time(entry.get("time")),
            rainfall_mm_hr=float(precip or 0.0),
            temperature_c=_safe_float(instant.get("air_temperature")),
            wind_speed_kmh=(round(wind_ms * 3.6, 2) if wind_ms is not None else None),
            humidity_pct=_safe_float(instant.get("relative_humidity")),
            pressure_hpa=_safe_float(
                instant.get("air_pressure_at_sea_level")
            ),
            weather_code=None,  # met.no exposes symbol codes, not WMO numbers
            weather_main=main,
            weather_description=desc,
            confidence=1.0,
        )

    # ── Hourly forecast → ForecastResult ────────────────────────────────

    async def get_forecast(self, lat: float, lng: float, hours: int = 24) -> ForecastResult:
        data = await self._compact(lat, lng)
        series = ((data.get("properties") or {}).get("timeseries")) or []
        if not series:
            raise ConnectorError(
                self.provider, "missing 'properties.timeseries'", retryable=False
            )

        slices: list[ForecastSlice] = []
        for entry in series[: max(1, hours)]:
            if not isinstance(entry, dict):
                continue
            block = entry.get("data") or {}
            instant = (block.get("instant") or {}).get("details") or {}
            next_1h = block.get("next_1_hours") or {}
            details = next_1h.get("details") or {}
            precip = details.get("precipitation_amount")
            if precip is None:
                # Beyond the 1-hour horizon met.no only ships 6-hour buckets —
                # allocate the real bucket evenly rather than inventing values.
                next_6h = block.get("next_6_hours") or {}
                six = (next_6h.get("details") or {}).get("precipitation_amount")
                precip = (float(six) / 6.0) if six is not None else 0.0
            slices.append(
                ForecastSlice(
                    time=str(entry.get("time", "")),
                    precipitation_mm=float(precip),
                    precipitation_probability_pct=None,  # met.no has no probability
                    temperature_c=_safe_float(instant.get("air_temperature")),
                )
            )

        if not slices:
            raise ConnectorError(
                self.provider, "no usable timeseries entries", retryable=False
            )

        return ForecastResult(
            source=self.provider,
            observation_type="forecast",
            latitude=float(lat),
            longitude=float(lng),
            retrieved_at=datetime.now(timezone.utc),
            hours=slices,
        )
