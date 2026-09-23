"""
Open-Meteo poller — runs every 5 minutes per active zone.
Stores readings in weather_readings table and updates zone risk scores.
"""
import uuid
from datetime import datetime, timezone

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.weather import WeatherReading
from app.models.zone import Zone
from sqlalchemy import select

logger = structlog.get_logger()
settings = get_settings()

OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"


def _weather_code_to_main(code: int) -> str:
    """Convert Open-Meteo weather code to weather main category."""
    if code is None:
        return ""
    codes = {
        0: "Clear",
        1: "Clear",
        2: "Clear",
        3: "Clouds",
        45: "Fog",
        48: "Fog",
        51: "Drizzle",
        53: "Drizzle",
        55: "Drizzle",
        56: "Freezing Drizzle",
        57: "Freezing Drizzle",
        61: "Rain",
        63: "Rain",
        65: "Rain",
        66: "Freezing Rain",
        67: "Freezing Rain",
        71: "Snow",
        73: "Snow",
        75: "Snow",
        77: "Snow",
        80: "Rain Showers",
        81: "Rain Showers",
        82: "Rain Showers",
        95: "Thunderstorm",
        96: "Thunderstorm",
        99: "Thunderstorm",
    }
    return codes.get(code, "Unknown")


def _weather_code_to_description(code: int) -> str:
    """Convert Open-Meteo weather code to human-readable description."""
    if code is None:
        return ""
    codes = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow fall",
        73: "Moderate snow fall",
        75: "Heavy snow fall",
        77: "Snow grains",
        80: "Rain showers",
        81: "Rain showers",
        82: "Rain showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }
    return codes.get(code, "Unknown condition")


def _compute_risk_score(rainfall_mm_hr: float, wind_speed_kmh: float, weather_main: str) -> float:
    """Normalised 0.0–1.0 risk score from weather data."""
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


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
async def _fetch_weather(lat: float, lng: float) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            OPEN_METEO_BASE,
            params={
                "latitude": lat,
                "longitude": lng,
                "current_weather": "true",
                "hourly": "precipitation",
            },
        )
        if resp.status_code != 200:
            return None
        return resp.json()


async def poll_weather() -> None:
    """Poll weather for all active zones and store results."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Zone))
        zones = result.scalars().all()

        if not zones:
            return

        for zone in zones:
            try:
                data = await _fetch_weather(zone.centroid_lat, zone.centroid_lng)
                if not data:
                    continue

                current = data.get("current_weather", {})
                hourly = data.get("hourly", {})

                temp = current.get("temperature")
                wind_mps = current.get("windspeed", 0.0)
                wind_kmh = round(wind_mps * 3.6, 1)
                weather_code = current.get("weathercode", 0)
                weather_main = _weather_code_to_main(weather_code)
                weather_desc = _weather_code_to_description(weather_code)

                # Get rainfall from hourly data - use the most recent hour entry
                rain = hourly.get("rainfall", [])
                if not rain:
                    rain = hourly.get("precipitation", [])
                if rain:
                    # Get the last (most recent) precipitation value
                    rainfall = rain[-1] if rain else 0.0
                else:
                    rainfall = 0.0

                risk = _compute_risk_score(rainfall, wind_kmh, weather_main)

                reading = WeatherReading(
                    id=str(uuid.uuid4()),
                    zone_id=zone.id,
                    lat=zone.centroid_lat,
                    lng=zone.centroid_lng,
                    rainfall_mm_hr=rainfall,
                    wind_speed_kmh=wind_kmh,
                    temperature_c=temp,
                    weather_main=weather_main,
                    weather_description=weather_desc,
                    risk_score=risk,
                    polled_at=datetime.now(timezone.utc),
                )
                db.add(reading)
                logger.debug("Weather polled", zone=zone.id, rainfall=rainfall, wind=wind_kmh, risk=risk)

            except Exception as e:
                logger.warning("Weather poll failed for zone", zone=zone.id, error=str(e))

        await db.commit()