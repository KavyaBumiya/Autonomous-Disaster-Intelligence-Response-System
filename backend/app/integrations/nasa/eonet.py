"""
NASA EONET connector — Earth Observatory Natural Event Tracker v3 (§5).

EONET is an open, keyless catalog of natural events (wildfires, severe
storms, volcanoes, floods…) with geometry that evolves over time. It is
part of NASA's general Open API portal ecosystem but hosted at
eonet.gsfc.nasa.gov — NOT Earthdata/CMR (separate auth) and NOT satellite
imagery (imagery links come from each event's `sources`).

Docs: https://eonet.gsfc.nasa.gov/docs/v3
Rate: open service; settings.nasa_api_key (api.nasa.gov, 1,000 req/h) is
forwarded only when configured — EONET tolerates but does not require it.

Responses flow through the shared BaseConnector (timeout, retry, registry
circuit breaker); normalization lives in normalize_event (§5) so callers
never touch raw provider payloads.
"""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError


def normalize_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """One EONET event → compact normalized record, or None if malformed.

    Coordinates come from the NEWEST Point geometry (EONET lists geometry
    chronologically, latest last — storms move, so older points are ignored).
    Polygon-only events keep lat/lng = None: an area is stored as its type,
    never reduced to an invented centroid (§7 — no fabricated coordinates).
    Malformed entries (missing id/title) are skipped, not guessed.
    """
    if not isinstance(event, dict):
        return None
    eonet_id = event.get("id")
    title = event.get("title")
    if not eonet_id or not title:
        return None

    categories = event.get("categories") or []
    first_cat = categories[0] if categories and isinstance(categories[0], dict) else {}
    sources = [
        {"id": s.get("id"), "url": s.get("url")}
        for s in (event.get("sources") or [])
        if isinstance(s, dict)
    ]

    lat: float | None = None
    lng: float | None = None
    geometry_type: str | None = None
    latest_date: str | None = None
    magnitude_value: float | None = None
    magnitude_unit: str | None = None

    geometry = event.get("geometry") or []
    if isinstance(geometry, list) and geometry:
        # newest first; take the latest entry that carries a usable Point
        for geo in reversed(geometry):
            if not isinstance(geo, dict):
                continue
            coords = geo.get("coordinates")
            if geo.get("type") == "Point" and isinstance(coords, list) and len(coords) >= 2:
                try:
                    lng_f, lat_f = float(coords[0]), float(coords[1])
                except (TypeError, ValueError):
                    continue
                if -90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0:
                    lat, lng = lat_f, lng_f
                    geometry_type = "Point"
                    latest_date = geo.get("date")
                    magnitude_value = geo.get("magnitudeValue")
                    magnitude_unit = geo.get("magnitudeUnit")
                    break
        if lat is None:
            # no Point at all — record the geometry honestly as non-point
            last_geo = geometry[-1]
            if isinstance(last_geo, dict):
                geometry_type = last_geo.get("type")
                latest_date = last_geo.get("date")
                magnitude_value = last_geo.get("magnitudeValue")
                magnitude_unit = last_geo.get("magnitudeUnit")

    closed = event.get("closed")
    return {
        "eonet_id": eonet_id,
        "title": title,
        "description": event.get("description"),
        "link": event.get("link"),
        "closed": closed,
        "category": first_cat.get("id"),
        "category_title": first_cat.get("title"),
        "sources": sources,
        "lat": lat,
        "lng": lng,
        "geometry_type": geometry_type,
        "magnitude_value": magnitude_value,
        "magnitude_unit": magnitude_unit,
        "latest_geometry_date": latest_date,
    }


class EonetConnector(BaseConnector):
    provider = "nasa/eonet"
    timeout_seconds = 15.0
    max_attempts = 3

    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.eonet_base_url).rstrip("/")

    async def events(
        self,
        *,
        status: str = "open",
        limit: int = 50,
        categories: list[str] | None = None,
        source: str | None = None,
    ) -> dict[str, Any]:
        """Raw EONET payload: {title, description, link, events: [...]}.

        `status`: "open" (default) | "closed" | "all".
        Raises ConnectorError on provider failure (circuit breaker applies).
        """
        params: dict[str, Any] = {"status": status, "limit": str(limit)}
        if categories:
            params["category"] = ",".join(c.strip() for c in categories if c.strip())
        if source:
            params["source"] = source
        api_key = get_settings().nasa_api_key
        if api_key:
            params["api_key"] = api_key  # tolerated; EONET works without it

        data = await self.get_json("/events", params=params)
        if not isinstance(data, dict) or not isinstance(data.get("events"), list):
            raise ConnectorError(
                self.provider,
                "EONET response missing 'events' list — refusing to treat it "
                "as data (nothing fabricated)",
                retryable=True,
            )
        return data

    async def event_by_id(self, eonet_id: str) -> dict[str, Any] | None:
        """Single event detail; None when unknown (honest empty, §7)."""
        try:
            data = await self.get_json(f"/events/{eonet_id}")
        except ConnectorError as exc:
            if exc.status_code == 404:
                return None
            raise
        if not isinstance(data, dict) or not data.get("id"):
            return None
        return data
