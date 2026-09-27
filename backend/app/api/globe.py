from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.integrations.base import ConnectorError
from app.integrations.globe.cesium_ion import CesiumIonConnector

router = APIRouter()


@router.get("/token", tags=["cesium-ion"])
async def get_cesium_token(_: dict = Depends(get_current_user)):
    settings = get_settings()
    if not settings.cesium_ion_token:
        raise HTTPException(503, detail="Cesium Ion token not configured")
    return {
        "accessToken": settings.cesium_ion_token,
        "assetId": settings.cesium_ion_asset_id or None,
    }


@router.get("/assets/{asset_id}", tags=["cesium-ion"])
async def get_asset(
    asset_id: int,
    _: dict = Depends(get_current_user),
):
    connector = CesiumIonConnector()
    try:
        result = await connector.get_asset(asset_id)
        return result
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc


@router.get("/assets", tags=["cesium-ion"])
async def list_assets(
    asset_type: str = Query("IMAGERY", pattern="^(IMAGERY|TERRAIN|3DTILES)$"),
    _: dict = Depends(get_current_user),
):
    connector = CesiumIonConnector()
    try:
        if asset_type == "TERRAIN":
            result = await connector.get_terrain_assets()
        else:
            result = await connector.get_imagery_assets()
        return {"type": asset_type, "count": len(result), "assets": result}
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc
