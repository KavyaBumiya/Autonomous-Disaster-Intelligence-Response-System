"""
Nominatim connector — forward geocoding: free-text → lat/lng candidates
(PRD §5). Replaces the geopy wrapper so requests flow through the shared
BaseConnector (timeout, retry, registry) and honour settings.nominatim_base_url.

Usage policy (§26 / Nominatim policy):
    * 1 req/s process-wide throttle
    * identifying User-Agent from settings (never a default library UA)
    * results cached by the service layer for 24 h (see services/geocoding.py)
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

from app.core.config import get_settings
from app.integrations.base import BaseConnector

logger = structlog.get_logger()

_THROTTLE_MIN_INTERVAL_S = 1.0
_throttle_lock = asyncio.Lock()
_last_call_at = 0.0


async def _throttle() -> None:
    global _last_call_at
    async with _throttle_lock:
        now = time.monotonic()
        wait = _THROTTLE_MIN_INTERVAL_S - (now - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = time.monotonic()


def _confidence(importance: Any) -> float:
    """Nominatim's own ranking metric → 0..1 confidence.

    importance is the honest signal (not a fabricated score): low-ranked
    matches genuinely are less trustworthy. Missing → neutral 0.5."""
    try:
        value = float(importance)
    except (TypeError, ValueError):
        return 0.5
    return round(min(0.99, max(0.05, value)), 2)


class NominatimConnector(BaseConnector):
    provider = "nominatim"
    timeout_seconds = 10.0
    max_attempts = 3

    def __init__(self, base_url: str | None = None, user_agent: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.nominatim_base_url).rstrip("/")
        self.user_agent = user_agent or settings.nominatim_user_agent

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Resolve a location string to ranked candidates (best first).

        Raises ConnectorError on provider failure; returns [] on no match."""
        await _throttle()
        data = await self.get_json(
            "/search",
            params={
                "q": query,
                "format": "jsonv2",
                "limit": max(1, min(limit, 10)),
                "addressdetails": 0,
                "accept-language": "en",
            },
            headers={"User-Agent": self.user_agent},
        )
        if not isinstance(data, list):
            # Nominatim occasionally returns an error object for bad input.
            logger.warning("nominatim_unexpected_payload", query_type=type(data).__name__)
            return []

        out: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict) or "lat" not in item or "lon" not in item:
                continue
            try:
                lat = float(item["lat"])
                lng = float(item["lon"])
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "display_name": item.get("display_name"),
                    "confidence": _confidence(item.get("importance")),
                    "osm_type": item.get("osm_type"),
                    "osm_id": item.get("osm_id"),
                    "category": item.get("category"),
                    "type": item.get("type"),
                }
            )
        logger.info("nominatim_search_ok", query_len=len(query), results=len(out))
        return out
