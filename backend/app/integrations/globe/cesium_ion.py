from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.integrations.base import BaseConnector, ConnectorError


class CesiumIonConnector(BaseConnector):
    provider = "cesium-ion"
    base_url = "https://api.cesium.com"
    timeout_seconds = 15.0

    def __init__(self) -> None:
        settings = get_settings()
        self._token = settings.cesium_ion_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    async def get_asset(self, asset_id: int) -> dict[str, Any]:
        resp = await self.get(f"/v1/assets/{asset_id}", headers=self._headers())
        data = resp.json()
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "type": data.get("type"),
            "bytes": data.get("bytes"),
            "attribution": data.get("attribution"),
            "key": self._token,
        }

    async def get_imagery_assets(self) -> list[dict[str, Any]]:
        resp = await self.get("/v1/assets?type=IMAGERY", headers=self._headers())
        data = resp.json()
        items = data.get("items", [])
        return [
            {"id": item.get("id"), "name": item.get("name"), "type": item.get("type")}
            for item in items
        ]

    async def get_terrain_assets(self) -> list[dict[str, Any]]:
        resp = await self.get("/v1/assets?type=TERRAIN", headers=self._headers())
        data = resp.json()
        items = data.get("items", [])
        return [
            {"id": item.get("id"), "name": item.get("name"), "type": item.get("type")}
            for item in items
        ]
