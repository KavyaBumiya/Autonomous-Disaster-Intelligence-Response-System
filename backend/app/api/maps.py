from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.integrations.base import ConnectorError
from app.integrations.maps.google_maps import GoogleMapsConnector

router = APIRouter()


@router.get("/geocode", tags=["maps"])
async def geocode(
    address: str = Query(..., min_length=1, description="Address to geocode"),
    _: dict = Depends(get_current_user),
):
    connector = GoogleMapsConnector()
    try:
        result = await connector.geocode(address)
        return {"provider": "google-maps", "result": result}
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc


@router.get("/reverse-geocode", tags=["maps"])
async def reverse_geocode(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    _: dict = Depends(get_current_user),
):
    connector = GoogleMapsConnector()
    try:
        result = await connector.reverse_geocode(lat, lng)
        return {"provider": "google-maps", "result": result}
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc


@router.get("/places", tags=["maps"])
async def places_nearby(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius: int = Query(500, ge=1, le=50000),
    keyword: str | None = Query(None),
    place_type: str | None = Query(None),
    _: dict = Depends(get_current_user),
):
    connector = GoogleMapsConnector()
    try:
        results = await connector.places_nearby(lat, lng, radius, keyword, place_type)
        return {"provider": "google-maps", "count": len(results), "results": results}
    except ConnectorError as exc:
        raise HTTPException(502, detail=exc.message) from exc
