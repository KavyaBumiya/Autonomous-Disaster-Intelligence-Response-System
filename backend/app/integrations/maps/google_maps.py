from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError


class GoogleMapsConnector(BaseConnector):
    provider = "google-maps"
    base_url = "https://maps.googleapis.com/maps/api"
    timeout_seconds = 15.0

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.google_maps_api_key

    def _add_key(self, params: dict[str, Any] | None) -> dict[str, Any]:
        p = dict(params or {})
        p["key"] = self._api_key
        return p

    async def geocode(self, address: str) -> dict[str, Any]:
        params = self._add_key({"address": address})
        resp = await self.get_json("/geocode/json", params=params)
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            raise ConnectorError(
                self.provider,
                f"geocode failed: {data.get('status', 'UNKNOWN_ERROR')}",
                retryable=False,
            )
        result = data["results"][0]
        loc = result.get("geometry", {}).get("location", {})
        return {
            "formatted_address": result.get("formatted_address"),
            "lat": loc.get("lat"),
            "lng": loc.get("lng"),
            "place_id": result.get("place_id"),
            "location_type": result.get("geometry", {}).get("location_type"),
        }

    async def reverse_geocode(self, lat: float, lng: float) -> dict[str, Any]:
        params = self._add_key({"latlng": f"{lat},{lng}"})
        resp = await self.get_json("/geocode/json", params=params)
        data = resp.json()
        if data.get("status") != "OK" or not data.get("results"):
            raise ConnectorError(
                self.provider,
                f"reverse geocode failed: {data.get('status', 'UNKNOWN_ERROR')}",
                retryable=False,
            )
        result = data["results"][0]
        return {
            "formatted_address": result.get("formatted_address"),
            "place_id": result.get("place_id"),
            "address_components": result.get("address_components", []),
        }

    async def places_nearby(
        self,
        lat: float,
        lng: float,
        radius: int = 500,
        keyword: str | None = None,
        place_type: str | None = None,
    ) -> list[dict[str, Any]]:
        params = self._add_key({
            "location": f"{lat},{lng}",
            "radius": str(radius),
        })
        if keyword:
            params["keyword"] = keyword
        if place_type:
            params["type"] = place_type
        resp = await self.get_json("/place/nearbysearch/json", params=params)
        data = resp.json()
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            raise ConnectorError(
                self.provider,
                f"places search failed: {data.get('status', 'UNKNOWN_ERROR')}",
                retryable=data.get("status") in ("UNKNOWN_ERROR",),
            )
        return data.get("results", [])
