from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.integrations.base import ConnectorError
from app.integrations.traffic.tomtom import TomTomConnector

router = APIRouter()


@router.get("/route", tags=["tomtom"])
async def calculate_route(
    origin_lat: float = Query(..., ge=-90, le=90),
    origin_lng: float = Query(..., ge=-180, le=180),
    dest_lat: float = Query(..., ge=-90, le=90),
    dest_lng: float = Query(..., ge=-180, le=180),
    traffic: bool = Query(True),
    _: dict = Depends(get_current_user),
):
    connector = TomTomConnector()
    try:
        result = await connector.calculate_route(
            origin_lat, origin_lng, dest_lat, dest_lng, traffic=traffic
        )
        return result
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc


@router.get("/flow", tags=["tomtom"])
async def traffic_flow(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    zoom: int = Query(10, ge=0, le=22),
    _: dict = Depends(get_current_user),
):
    connector = TomTomConnector()
    try:
        result = await connector.traffic_flow(lat, lng, zoom)
        return result
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc


@router.get("/search", tags=["tomtom"])
async def search(
    q: str = Query(..., min_length=1),
    lat: float | None = Query(None),
    lng: float | None = Query(None),
    limit: int = Query(10, ge=1, le=50),
    _: dict = Depends(get_current_user),
):
    connector = TomTomConnector()
    try:
        results = await connector.search(q, lat=lat, lng=lng, limit=limit)
        return {"provider": "tomtom", "count": len(results), "results": results}
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc
