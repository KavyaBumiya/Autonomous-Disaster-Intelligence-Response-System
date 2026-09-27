"""
Photon (Komoot) connector — fallback geocoder: free-text → lat/lng.

Why a fallback exists (2026-09): Nominatim's usage policy blocks requests
coming from cloud/datacenter IPs, which makes forward geocoding fail on
Render even though the service itself is healthy. Photon serves the same
OpenStreetMap data keylessly and tolerates cloud egress, so the geocoding
service tries it whenever Nominatim fails — real OSM data, labelled via the
registry as provider "photon" (never fabricated, §31).

Endpoint:
    GET {photon_base_url}/api/?q=..&limit=..   GeoJSON FeatureCollection
"""
from __future__ import annotations

from typing import Any

import structlog

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError

logger = structlog.get_logger()


def _display_name(props: dict[str, Any]) -> str | None:
    parts = [
        props.get("name"),
        props.get("street"),
        props.get("city") or props.get("district") or props.get("county"),
        props.get("state"),
        props.get("country"),
    ]
    seen: list[str] = []
    for part in parts:
        text = str(part).strip() if part else ""
        if text and text not in seen:
            seen.append(text)
    return ", ".join(seen) or None


class PhotonConnector(BaseConnector):
    provider = "photon"
    timeout_seconds = 10.0
    max_attempts = 2

    def __init__(self, base_url: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.photon_base_url).rstrip("/")

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """Resolve a location string to candidates in Photon's ranked order.

        Same candidate shape as NominatimConnector.search so callers are
        provider-agnostic. Photon exposes no per-result importance score, so
        confidence is the neutral 0.5 (identical to Nominatim without
        importance) — never a fabricated ranking."""
        data = await self.get_json(
            "/api/",
            params={"q": query, "limit": max(1, min(limit, 10))},
        )
        features = data.get("features") if isinstance(data, dict) else None
        if not isinstance(features, list):
            logger.warning("photon_unexpected_payload", query_type=type(data).__name__)
            return []

        out: list[dict[str, Any]] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            try:
                lng = float(coords[0])
                lat = float(coords[1])
            except (TypeError, ValueError):
                continue
            out.append(
                {
                    "lat": lat,
                    "lng": lng,
                    "display_name": _display_name(props) or props.get("name"),
                    "confidence": 0.5,
                    "osm_type": props.get("osm_type"),
                    "osm_id": props.get("osm_id"),
                    "category": props.get("osm_key"),
                    "type": props.get("osm_value"),
                }
            )
        logger.info("photon_search_ok", query_len=len(query), results=len(out))
        return out
