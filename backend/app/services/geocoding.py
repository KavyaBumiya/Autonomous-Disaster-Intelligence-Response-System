"""
Geocoding service — free-text location → lat/lng (Nominatim via
app.integrations.gis.nominatim, Photon fallback via gis.photon).

Contract (preserved for callers in nlp_service / pollers):
    await geocode("Vadodara")  →  {"lat", "lng", "display_name", "confidence", ...}
                                  or None when no match / provider down.

Behaviour:
    * 24 h Redis cache on the historical `geocode:{md5}` key (shared entries
      from the geopy era still hit — same key scheme, same value shape).
    * 10 min negative cache for no-match queries (protects the public API
      from repeated junk lookups).
    * Fallback (§31): when Nominatim fails (its usage policy blocks cloud
      IPs), Photon serves the same OSM data keylessly — cached identically,
      still real data.
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
from app.integrations.gis.photon import PhotonConnector

logger = structlog.get_logger()

CACHE_TTL_SECONDS = 86400      # 24 hours — locations don't change
NEGATIVE_TTL_SECONDS = 600     # no-match results: 10 minutes

_connector: NominatimConnector | None = None
_fallback: PhotonConnector | None = None


def _get_connector() -> NominatimConnector:
    global _connector
    if _connector is None:
        _connector = NominatimConnector()
    return _connector


def _get_fallback() -> PhotonConnector:
    global _fallback
    if _fallback is None:
        _fallback = PhotonConnector()
    return _fallback


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
    except ConnectorError as primary_exc:
        # Fallback (§31): real OSM data via Photon when Nominatim is
        # unreachable (cloud-IP policy, outage, rate limit).
        try:
            candidates = await _get_fallback().search(location_string, limit=limit)
        except ConnectorError as fb_exc:
            logger.warning(
                "geocode_provider_failed",
                provider=primary_exc.provider,
                error=primary_exc.message,
                status_code=primary_exc.status_code,
                fallback=fb_exc.provider,
                fallback_error=fb_exc.message,
            )
            return []
        logger.warning(
            "geocode_fallback_used",
            primary=primary_exc.provider,
            fallback="photon",
            error=primary_exc.message,
        )

    if candidates:
        await cache.cache_set(key, candidates, ttl=CACHE_TTL_SECONDS)
    else:
        await cache.cache_set(key, [], ttl=NEGATIVE_TTL_SECONDS)
    return candidates


async def geocode(location_string: str) -> dict[str, Any] | None:
    """Best match for a location string, or None. Backward-compatible shape."""
    candidates = await geocode_candidates(location_string, limit=1)
    return candidates[0] if candidates else None
