"""
Geocoding service — converts free-text location strings to lat/lng.
Uses Nominatim (OSM) with aggressive Redis caching to respect rate limits.
Falls back gracefully when no match is found.
"""
import hashlib
import json
from typing import Optional

import redis.asyncio as aioredis
import structlog
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

_redis_client: aioredis.Redis | None = None
_geocoder: Nominatim | None = None

CACHE_TTL_SECONDS = 86400  # 24 hours — locations don't change


def _get_geocoder() -> Nominatim:
    global _geocoder
    if _geocoder is None:
        _geocoder = Nominatim(user_agent=settings.nominatim_user_agent)
    return _geocoder


async def _get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _cache_key(location_string: str) -> str:
    h = hashlib.md5(location_string.lower().strip().encode()).hexdigest()
    return f"geocode:{h}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=5))
def _geocode_sync(location_string: str) -> Optional[dict]:
    geocoder = _get_geocoder()
    try:
        location = geocoder.geocode(location_string, timeout=10, language="en")
        if location:
            return {
                "lat": location.latitude,
                "lng": location.longitude,
                "display_name": location.address,
                "confidence": 0.8,
            }
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.warning("Geocoding error", location=location_string, error=str(e))
        raise
    return None


async def geocode(location_string: str) -> Optional[dict]:
    """
    Resolve a location string to lat/lng.
    Returns None if no match found or location string is empty.
    """
    if not location_string or not location_string.strip():
        return None

    # Check Redis cache first
    try:
        r = await _get_redis()
        cached = await r.get(_cache_key(location_string))
        if cached:
            return json.loads(cached)
    except Exception as e:
        logger.warning("Redis geocode cache read failed", error=str(e))

    # Synchronous geocoding (geopy is not async-native)
    import asyncio
    result = await asyncio.get_event_loop().run_in_executor(
        None, _geocode_sync, location_string
    )

    # Store in cache
    if result:
        try:
            r = await _get_redis()
            await r.setex(_cache_key(location_string), CACHE_TTL_SECONDS, json.dumps(result))
        except Exception as e:
            logger.warning("Redis geocode cache write failed", error=str(e))

    return result
