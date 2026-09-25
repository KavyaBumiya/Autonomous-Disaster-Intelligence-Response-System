"""
OSRM connector — road-network routing (PRD §5.5 / §8).

Thin wrapper over the shared BaseConnector so routing participates in the
provider registry (§34) and honours settings.osrm_api_base. Failures raise
ConnectorError; callers (route_intelligence) degrade to a clearly-labelled
straight-line estimate (§7 — never present fallback as live OSRM).
"""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.base import BaseConnector


class OsrmConnector(BaseConnector):
    provider = "osrm"
    # Routing sits in a request path a user is waiting on: short timeout,
    # two attempts — availability beats completeness, fallback covers rest.
    timeout_seconds = 6.0
    max_attempts = 2

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or get_settings().osrm_api_base).rstrip("/")

    async def route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        *,
        alternatives: bool = False,
        geometries: str = "geojson",
        overview: str = "full",
    ) -> dict[str, Any] | None:
        """Driving route between two points.

        Returns the FIRST route normalized to
        {distance_m, duration_s, geometry} or None when the road network
        has no route (OSRM code != Ok). Provider/network failures raise
        ConnectorError — caller decides whether to fall back.
        """
        coords = f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
        data = await self.get_json(
            f"/route/v1/driving/{coords}",
            params={
                "overview": overview,
                "geometries": geometries,
                "alternatives": "true" if alternatives else "false",
            },
        )
        if not isinstance(data, dict):
            return None
        routes = data.get("routes")
        if data.get("code") != "Ok" or not routes:
            return None
        first = routes[0]
        geometry = (first.get("geometry") or {}).get("coordinates") or []
        return {
            "distance_m": float(first.get("distance") or 0.0),
            "duration_s": float(first.get("duration") or 0.0),
            "geometry": geometry,
            "route_count": len(routes),
        }
