"""
Weather Service — Open-Meteo Integration.

Provides weather data retrieval from Open-Meteo API for flood/fire prediction
and general weather monitoring. Cached responses with TTL for performance.
"""
import time
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from app.core.apis_config import WEATHER_APIS, get_weather_api_config, API_CONFIG

# Open-Meteo base configuration
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_CACHE_TTL = API_CONFIG["cache_ttl_seconds"]  # 5 minutes


class WeatherService:
    """Weather service using Open-Meteo API."""

    def __init__(self, api_name: str = "open-meteo"):
        self.api_name = api_name
        self.config = get_weather_api_config(api_name)
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}

    def _is_cached(self, key: str) -> bool:
        """Check if cached data is still valid."""
        if key not in self._cache:
            return False
        if time.time() - self._cache_timestamps.get(key, 0) > OPEN_METEO_CACHE_TTL:
            return False
        return True

    def _cache_set(self, key: str, data: Dict[str, Any]) -> None:
        """Cache weather data."""
        self._cache[key] = data
        self._cache_timestamps[key] = time.time()

    def _cache_get(self, key: str) -> Optional[Dict[str, Any]]:
        """Get cached weather data if available."""
        if self._is_cached(key):
            return self._cache[key]
        return None

    def get_current_weather(
        self, latitude: float, longitude: float
    ) -> Dict[str, Any]:
        """
        Get current weather conditions for a location.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees

        Returns:
            Dictionary with current weather conditions
        """
        cache_key = f"current_{latitude}_{longitude}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        try:
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "current_weather": "true",
            }
            resp = requests.get(OPEN_METEO_BASE, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                result = {
                    "temperature": data["current_weather"].get("temperature"),
                    "windspeed": data["current_weather"].get("windspeed"),
                    "winddirection": data["current_weather"].get("winddirection"),
                  "weathercode": data["current_weather"].get("weathercode"),
                  "time": data["current_weather"].get("time"),
                }
                self._cache_set(cache_key, result)
                return result
        except Exception as e:
            print(f"Error fetching weather: {e}")

        return {}

    def get_hourly_forecast(
        self,
        latitude: float,
        longitude: float,
        hourly_vars: List[str] = None,
        start_date: str = None,
        end_date: str = None,
    ) -> Dict[str, Any]:
        """
        Get hourly weather forecast.

        Args:
            latitude: Latitude in decimal degrees
            longitude: Longitude in decimal degrees
            hourly_vars: List of hourly variables to retrieve
            start_date: Start date YYYY-MM-DD (default: today)
            end_date: End date YYYY-MM-DD (default: 7 days ahead)

        Returns:
            Dictionary with hourly forecast data
        """
        if hourly_vars is None:
            hourly_vars = ["temperature_2m", "precipitation", "weathercode"]

        cache_key = f"hourly_{latitude}_{longitude}_{','.join(hourly_vars)}"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        try:
            params = {
                "latitude": latitude,
                "longitude": longitude,
                "hourly": ",".join(hourly_vars),
            }

            if start_date:
                params["start_date"] = start_date
            if end_date:
                params["end_date"] = end_date

            resp = requests.get(OPEN_METEO_BASE, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                self._cache_set(cache_key, data)
                return data

        except Exception as e:
            print(f"Error fetching hourly forecast: {e}")

        return {}

    def get_weather_code_description(self, code: int) -> str:
        """Convert Open-Meteo weather code to human-readable description."""
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


# ─── Service Instance ────────────────────────────────────────────────

# Global service instance
weather_service = WeatherService()


# ─── Convenience Functions ───────────────────────────────────────────

def get_current_weather(latitude: float, longitude: float) -> Dict[str, Any]:
    """Quick access to current weather."""
    return weather_service.get_current_weather(latitude, longitude)


def get_hourly_forecast(
    latitude: float,
    longitude: float,
    hourly_vars=None,
    start_date=None,
    end_date=None,
) -> Dict[str, Any]:
    """Quick access to hourly forecast."""
    return weather_service.get_hourly_forecast(
        latitude, longitude, hourly_vars, start_date, end_date
    )


def get_weather_description(code: int) -> str:
    """Quick access to weather code description."""
    return weather_service.get_weather_code_description(code)