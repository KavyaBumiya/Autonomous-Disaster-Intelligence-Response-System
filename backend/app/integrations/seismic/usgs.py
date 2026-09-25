"""
USGS earthquake connector — FDSN event query + geojson feed (PRD §5).

Uses settings.usgs_api_base / settings.usgs_feed_url (§35). Responses flow
through the shared BaseConnector (timeout, retry, registry); raw GeoJSON is
returned as-is and normalized by the caller (pollers/seismic.py).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError


class UsgsConnector(BaseConnector):
    provider = "usgs"
    timeout_seconds = 15.0
    max_attempts = 3

    def __init__(
        self,
        api_base: str | None = None,
        feed_url: str | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (api_base or settings.usgs_api_base).rstrip("/")
        self.feed_url = feed_url or settings.usgs_feed_url

    async def recent_events(
        self,
        *,
        minutes: int = 30,
        min_magnitude: float = 3.0,
        limit: int = 50,
        start: datetime | None = None,
    ) -> dict[str, Any]:
        """GeoJSON FeatureCollection: events since `start` (default now−minutes)
        with magnitude ≥ min_magnitude, newest first."""
        since = start or (datetime.now(timezone.utc) - timedelta(minutes=minutes))
        return await self.get_json(
            "/query",
            params={
                "format": "geojson",
                "starttime": since.strftime("%Y-%m-%dT%H:%M:%S"),
                "minmagnitude": str(min_magnitude),
                "orderby": "time",
                "limit": str(limit),
            },
        )

    async def all_hour_feed(self) -> dict[str, Any]:
        """USGS 'all_hour' summary feed (absolute feed URL)."""
        data = await self.get_json(self.feed_url)
        return data if isinstance(data, dict) else {"type": "FeatureCollection", "features": []}

    async def events_by_bbox(
        self,
        south: float,
        west: float,
        north: float,
        east: float,
        *,
        min_magnitude: float = 0.0,
        limit: int = 50,
        start: datetime | None = None,
    ) -> dict[str, Any]:
        """GeoJSON events inside a bounding box (FDSN geobox params)."""
        params: dict[str, Any] = {
            "format": "geojson",
            "minlatitude": south,
            "maxlatitude": north,
            "minlongitude": west,
            "maxlongitude": east,
            "minmagnitude": str(min_magnitude),
            "orderby": "time",
            "limit": str(limit),
        }
        if start is not None:
            params["starttime"] = start.strftime("%Y-%m-%dT%H:%M:%S")
        return await self.get_json("/query", params=params)

    async def events_by_time(
        self,
        start: datetime,
        end: datetime | None = None,
        *,
        min_magnitude: float = 0.0,
        limit: int = 50,
    ) -> dict[str, Any]:
        """GeoJSON events in a time window (FDSN starttime/endtime)."""
        params: dict[str, Any] = {
            "format": "geojson",
            "starttime": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "minmagnitude": str(min_magnitude),
            "orderby": "time",
            "limit": str(limit),
        }
        if end is not None:
            params["endtime"] = end.strftime("%Y-%m-%dT%H:%M:%S")
        return await self.get_json("/query", params=params)

    async def get_event(self, event_id: str) -> dict[str, Any] | None:
        """Single event by USGS event id (e.g. 'us7000abcd'). None if unknown.

        USGS returns a bare GeoJSON *Feature* for eventid queries — normalized
        here to a FeatureCollection so callers see one consistent shape."""
        try:
            data = await self.get_json(
                "/query", params={"format": "geojson", "eventid": event_id}
            )
        except ConnectorError as exc:
            if exc.status_code == 404:
                return None  # unknown event id — not a provider failure
            raise
        if not isinstance(data, dict):
            return None
        if data.get("type") == "Feature" and data.get("id"):
            return {"type": "FeatureCollection", "features": [data]}
        if data.get("features"):
            return data
        return None
