from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.integrations.base import ConnectorError
from app.integrations.nasa.firms import NASAFIRMSConnector

router = APIRouter()


@router.get("/fires", tags=["nasa-firms"])
async def active_fires(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(500, ge=1, le=5000),
    days: int = Query(7, ge=1, le=10),
    _: dict = Depends(get_current_user),
):
    connector = NASAFIRMSConnector()
    try:
        result = await connector.get_fire_events(lat, lng, radius_km, days)
        return result
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc


@router.get("/fires/global", tags=["nasa-firms"])
async def global_fires(
    source: str = Query("VIIRS_SNPP_NRT"),
    day_range: int = Query(1, ge=1, le=10),
    _: dict = Depends(get_current_user),
):
    connector = NASAFIRMSConnector()
    try:
        fires = await connector.get_active_fires(source=source, day_range=day_range)
        return {
            "source": "NASA FIRMS",
            "satellite": source,
            "count": len(fires),
            "fires": fires,
        }
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc
