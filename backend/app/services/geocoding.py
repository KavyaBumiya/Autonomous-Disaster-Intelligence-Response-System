"""
Geocoding service — free-text location → lat/lng (Nominatim via
app.integrations.gis.nominatim).

Contract (preserved for callers in nlp_service / pollers):
    await geocode("Vadodara")  →  {"lat", "lng", "display_name", "confidence", ...}
                                  or None when no match / provider down.

Behaviour:
    * 24 h Redis cache on the historical `geocode:{md5}` key (shared entries
      from the geopy era still hit — same key scheme, same value shape).
    * 10 min negative cache for no-match queries (protects the public API
      from repeated junk lookups).
    * Provider failures degrade to None — geocoding is enrichment, never a
      reason to fail an analysis (§7: never fabricate → we simply omit).
"""
from __future__ import annotations

import hashlib
from typing import Any

import structlog

from app.integrations import cache
from app.integrations.base import ConnectorError
from app.integrations.gis.nominatim import NominatimConnector

logger = structlog.get_logger()

CACHE_TTL_SECONDS = 86400      # 24 hours — locations don't change
NEGATIVE_TTL_SECONDS = 600     # no-match results: 10 minutes

_connector: NominatimConnector | None = None


def _get_connector() -> NominatimConnector:
    global _connector
    if _connector is None:
        _connector = NominatimConnector()
    return _connector


def _cache_key(location_string: str) -> str:
    # Kept byte-identical to the legacy key so pre-existing cache entries
    # remain valid across the geopy → connector migration.
    digest = hashlib.md5(location_string.lower().strip().encode()).hexdigest()
    return f"geocode:{digest}"


async def geocode_candidates(location_string: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Ranked geocoding candidates (best first). [] on no match or failure."""
    if not location_string or not location_string.strip():
        return []

    key = _cache_key(location_string)
    cached = await cache.cache_get(key)
    if isinstance(cached, list):
        return cached[:limit]

    try:
        candidates = await _get_connector().search(location_string, limit=limit)
    except ConnectorError as exc:
        logger.warning(
            "geocode_provider_failed",
            provider=exc.provider,
            error=exc.message,
            status_code=exc.status_code,
        )
        return []

    if candidates:
        await cache.cache_set(key, candidates, ttl=CACHE_TTL_SECONDS)
    else:
        await cache.cache_set(key, [], ttl=NEGATIVE_TTL_SECONDS)
    return candidates


async def geocode(location_string: str) -> dict[str, Any] | None:
    """Best match for a location string, or None. Backward-compatible shape."""
    candidates = await geocode_candidates(location_string, limit=1)
    return candidates[0] if candidates else None
