from __future__ import annotations

import json
from typing import Any

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError


class TomTomConnector(BaseConnector):
    provider = "tomtom"
    base_url = "https://api.tomtom.com"
    timeout_seconds = 15.0

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.tomtom_api_key

    def _add_key(self, params: dict[str, Any] | None) -> dict[str, Any]:
        p = dict(params or {})
        p["key"] = self._api_key
        return p

    async def calculate_route(
        self,
        origin_lat: float,
        origin_lng: float,
        dest_lat: float,
        dest_lng: float,
        *,
        traffic: bool = True,
        vehicle: str = "car",
    ) -> dict[str, Any]:
        origin = f"{origin_lat},{origin_lng}"
        destination = f"{dest_lat},{dest_lng}"
        params = self._add_key({
            "traffic": "true" if traffic else "false",
            "travelMode": vehicle,
            "computeTravelTimeFor": "all",
        })
        path = f"/routing/1/calculateRoute/{origin}:{destination}/json"
        resp = await self.get_json(path, params=params)
        data = resp.json()
        routes = data.get("routes", [])
        if not routes:
            raise ConnectorError(self.provider, "no routes returned", retryable=False)
        route = routes[0]
        summary = route.get("summary", {})
        legs = route.get("legs", [])
        geometry_coords = []
        for leg in legs:
            for point in leg.get("points", []):
                geometry_coords.append([point.get("longitude", 0), point.get("latitude", 0)])
        return {
            "distance_km": round(summary.get("lengthInMeters", 0) / 1000, 2),
            "duration_minutes": round(summary.get("travelTimeInSeconds", 0) / 60, 1),
            "traffic_delay_minutes": round(summary.get("trafficDelayInSeconds", 0) / 60, 1),
            "geometry": {
                "type": "LineString",
                "coordinates": geometry_coords,
            },
            "source": "tomtom",
        }

    async def traffic_flow(
        self,
        lat: float,
        lng: float,
        zoom: int = 10,
    ) -> dict[str, Any]:
        params = self._add_key({"zoom": str(zoom), "style": "absolute"})
        resp = await self.get_json(
            f"/traffic/services/4/flowSegmentData/absolute/{zoom}/json",
            params=params,
        )
        data = resp.json()
        segment = data.get("flowSegmentData", {})
        return {
            "current_speed_kmh": segment.get("currentSpeed"),
            "free_flow_speed_kmh": segment.get("freeFlowSpeed"),
            "confidence": segment.get("confidence"),
            "source": "tomtom",
        }

    async def search(
        self,
        query: str,
        *,
        lat: float | None = None,
        lng: float | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        params = self._add_key({
            "query": query,
            "limit": str(limit),
            "countrySet": "IN",
        })
        if lat is not None and lng is not None:
            params["lat"] = str(lat)
            params["lon"] = str(lng)
        resp = await self.get_json("/search/2/search/{query}.json".format(query=query), params=params)
        data = resp.json()
        results = data.get("results", [])
        return [
            {
                "name": r.get("poi", {}).get("name"),
                "address": r.get("address", {}).get("freeformAddress"),
                "lat": r.get("position", {}).get("lat"),
                "lng": r.get("position", {}).get("lon"),
                "categories": r.get("poi", {}).get("categories", []),
            }
            for r in results
        ]
