"""
Open-Meteo connector (PRD §2/§6) — forecast + ERA5 historical, no API key.

Endpoints:
    forecast  {open_meteo_api_base}/…      current + hourly forecast
    archive   {open_meteo_archive_base}    ERA5 reanalysis history

Normalization:
    - current block → WeatherObservation (§5)
    - hourly block  → ForecastResult of ForecastSlice
    - WMO weather codes → weather_main / weather_description

Unit conventions (verified live against the API):
    precipitation  mm (per hour)     wind_speed_10m  km/h   temperature_2m  °C
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError
from app.schemas.observations import ForecastResult, ForecastSlice, WeatherObservation

logger = structlog.get_logger()

# WMO weather interpretation codes → category / human text
_CODE_MAIN: dict[int, str] = {
    0: "Clear", 1: "Clear", 2: "Clear", 3: "Clouds",
    45: "Fog", 48: "Fog",
    51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
    56: "Freezing Drizzle", 57: "Freezing Drizzle",
    61: "Rain", 63: "Rain", 65: "Rain",
    66: "Freezing Rain", 67: "Freezing Rain",
    71: "Snow", 73: "Snow", 75: "Snow", 77: "Snow grains",
    80: "Rain Showers", 81: "Rain Showers", 82: "Rain Showers",
    85: "Snow Showers", 86: "Snow Showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
}

_CODE_DESCRIPTION: dict[int, str] = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow fall", 73: "Moderate snow fall", 75: "Heavy snow fall",
    77: "Snow grains",
    80: "Rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

_CURRENT_VARS = (
    "temperature_2m,precipitation,weather_code,wind_speed_10m,relative_humidity_2m"
)
_HOURLY_VARS = "precipitation,precipitation_probability,temperature_2m"
_ARCHIVE_HOURLY_VARS = "temperature_2m,precipitation"
_FORECAST_PATH = "/forecast"  # {open_meteo_api_base}/forecast


def code_to_main(code: int | None) -> str:
    if code is None:
        return ""
    return _CODE_MAIN.get(code, "Unknown")


def code_to_description(code: int | None) -> str:
    if code is None:
        return ""
    return _CODE_DESCRIPTION.get(code, "Unknown condition")


def _parse_api_time(raw: str | None) -> datetime:
    """Open-Meteo times are ISO local without tz — treat as UTC-agnostic now()
    when unparseable so callers always get a timestamp."""
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class OpenMeteoConnector(BaseConnector):
    provider = "open-meteo"
    timeout_seconds = 10.0

    def __init__(
        self,
        base_url: str | None = None,
        archive_base_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = base_url or settings.open_meteo_api_base
        self.archive_base_url = archive_base_url or settings.open_meteo_archive_base

    # ── Current conditions → WeatherObservation ─────────────────────────

    async def get_current_weather(self, lat: float, lng: float) -> WeatherObservation:
        data = await self.get_json(
            _FORECAST_PATH,
            params={
                "latitude": lat,
                "longitude": lng,
                "current": _CURRENT_VARS,
            },
        )
        current = data.get("current")
        if not isinstance(current, dict) or not current:
            raise ConnectorError(
                self.provider, "missing 'current' block in response", retryable=False
            )

        code = current.get("weather_code")
        try:
            code_int = int(code) if code is not None else None
        except (TypeError, ValueError):
            code_int = None

        return WeatherObservation(
            source=self.provider,
            observation_type="weather",
            latitude=float(data.get("latitude", lat)),
            longitude=float(data.get("longitude", lng)),
            timestamp=_parse_api_time(current.get("time")),
            rainfall_mm_hr=float(current.get("precipitation") or 0.0),
            temperature_c=_safe_float(current.get("temperature_2m")),
            wind_speed_kmh=_safe_float(current.get("wind_speed_10m")),
            humidity_pct=_safe_float(current.get("relative_humidity_2m")),
            weather_code=code_int,
            weather_main=code_to_main(code_int),
            weather_description=code_to_description(code_int),
            confidence=1.0,
        )

    # ── Hourly forecast → ForecastResult ────────────────────────────────

    async def get_forecast(
        self, lat: float, lng: float, hours: int = 24
    ) -> ForecastResult:
        data = await self.get_json(
            _FORECAST_PATH,
            params={
                "latitude": lat,
                "longitude": lng,
                "hourly": _HOURLY_VARS,
                "forecast_days": max(2, (hours // 24) + 1),
            },
        )
        hourly = data.get("hourly") or {}
        times: list[str] = hourly.get("time") or []
        precip: list[Any] = hourly.get("precipitation") or []
        prob: list[Any] = hourly.get("precipitation_probability") or []
        temp: list[Any] = hourly.get("temperature_2m") or []

        if not times:
            raise ConnectorError(
                self.provider, "missing 'hourly.time' in response", retryable=False
            )

        # Start from the first hour >= now (arrays begin at local midnight).
        now = datetime.now()
        start = 0
        for i, t in enumerate(times):
            try:
                if datetime.fromisoformat(t) >= now.replace(tzinfo=None):
                    start = i
                    break
            except ValueError:
                continue

        slices: list[ForecastSlice] = []
        for i in range(start, min(start + hours, len(times))):
            slices.append(
                ForecastSlice(
                    time=times[i],
                    precipitation_mm=float(precip[i]) if i < len(precip) else 0.0,
                    precipitation_probability_pct=(
                        float(prob[i]) if i < len(prob) and prob[i] is not None else None
                    ),
                    temperature_c=float(temp[i]) if i < len(temp) and temp[i] is not None else None,
                )
            )

        return ForecastResult(
            source=self.provider,
            observation_type="forecast",
            latitude=float(data.get("latitude", lat)),
            longitude=float(data.get("longitude", lng)),
            retrieved_at=datetime.now(timezone.utc),
            hours=slices,
        )

    # ── ERA5 historical → ForecastResult-shaped hours ───────────────────

    async def get_historical_weather(
        self, lat: float, lng: float, start_date: str, end_date: str
    ) -> ForecastResult:
        """start_date/end_date: YYYY-MM-DD (ERA5 availability limits apply)."""
        data = await self.get_json(
            self.archive_base_url,  # absolute URL passes through _url()
            params={
                "latitude": lat,
                "longitude": lng,
                "start_date": start_date,
                "end_date": end_date,
                "hourly": _ARCHIVE_HOURLY_VARS,
            },
        )
        hourly = data.get("hourly") or {}
        times: list[str] = hourly.get("time") or []
        precip: list[Any] = hourly.get("precipitation") or []
        temp: list[Any] = hourly.get("temperature_2m") or []

        if not times:
            raise ConnectorError(
                self.provider, "missing 'hourly.time' in archive response", retryable=False
            )

        slices = [
            ForecastSlice(
                time=times[i],
                precipitation_mm=float(precip[i]) if i < len(precip) and precip[i] is not None else 0.0,
                temperature_c=float(temp[i]) if i < len(temp) and temp[i] is not None else None,
            )
            for i in range(len(times))
        ]
        return ForecastResult(
            source=self.provider,
            observation_type="historical_weather",
            latitude=float(data.get("latitude", lat)),
            longitude=float(data.get("longitude", lng)),
            retrieved_at=datetime.now(timezone.utc),
            hours=slices,
        )


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
