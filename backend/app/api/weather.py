"""
Weather endpoints — Phase 15 (live Open-Meteo via WeatherService).

Backend-owned retrieval (§6): handlers call weather_service only, never
Open-Meteo directly. Provider failures surface as 503 (§31) so the frontend
can mark weather DEGRADED — values are never fabricated.
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.dependencies import get_current_user
from app.integrations.base import ConnectorError
from app.pollers.weather import _compute_risk_score
from app.services.weather_service import weather_service

router = APIRouter()


@router.get("/current")
async def weather_current(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    _: dict = Depends(get_current_user),
):
    """Current conditions + deterministic risk score for a point."""
    try:
        obs = await weather_service.get_current_weather(lat, lng, allow_stale=True)
    except ConnectorError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Weather provider unavailable: {exc.message}",
        )

    wind = obs.wind_speed_kmh or 0.0
    risk = _compute_risk_score(obs.rainfall_mm_hr, wind, obs.weather_main)
    return {
        "provider": obs.source,
        "lat": obs.latitude,
        "lng": obs.longitude,
        "rainfall_mm_hr": obs.rainfall_mm_hr,
        "wind_speed_kmh": wind,
        "temperature_c": obs.temperature_c,
        "humidity_pct": obs.humidity_pct,
        "weather_main": obs.weather_main,
        "weather_description": obs.weather_description,
        "risk_score": round(risk, 3),
        "timestamp": obs.timestamp.isoformat(),
        "from_cache": obs.from_cache,
        "source": "current",
    }


@router.get("/forecast")
async def weather_forecast(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    hours: int = Query(24, ge=1, le=48),
    _: dict = Depends(get_current_user),
):
    """Hourly forecast slices (precipitation + temperature)."""
    try:
        fc = await weather_service.get_forecast(lat, lng, hours=hours, allow_stale=True)
    except ConnectorError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Weather forecast provider unavailable: {exc.message}",
        )

    payload = fc.model_dump(mode="json")
    return {
        "provider": fc.source,
        "lat": fc.latitude,
        "lng": fc.longitude,
        "hours": fc.hours,
        "retrieved_at": payload.get("retrieved_at"),
        "from_cache": fc.from_cache,
        "source": "forecast",
    }
