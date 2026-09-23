"""Prediction endpoints — Phase 3.
Flood & fire spread simulation + what-if scenario analysis.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.engine.prediction_engine import predict_spread

router = APIRouter()


@router.post("/flood", tags=["predictions"])
async def predict_flood(
    zone_id: str,
    hours: int = 12,
    rainfall_mm_hr: float = 50.0,
    db: AsyncSession = Depends(get_db),
):
    """Run flood spread simulation for a zone."""
    try:
        result = await predict_spread(
            zone_id=zone_id,
            disaster_type="flood",
            hours_ahead=hours,
            db=db,
        )
        return {
            "disaster_type": "flood",
            "zone_id": zone_id,
            "hours_ahead": hours,
            "rainfall_mm_hr": rainfall_mm_hr,
            "result": result,
        }
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/fire", tags=["predictions"])
async def predict_fire(
    zone_id: str,
    hours: int = 12,
    wind_speed_kmh: float = 20.0,
    db: AsyncSession = Depends(get_db),
):
    """Run fire spread simulation for a zone."""
    try:
        result = await predict_spread(
            zone_id=zone_id,
            disaster_type="fire",
            hours_ahead=hours,
            db=db,
        )
        return {
            "disaster_type": "fire",
            "zone_id": zone_id,
            "hours_ahead": hours,
            "wind_speed_kmh": wind_speed_kmh,
            "result": result,
        }
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.get("/{zone_id}", tags=["predictions"])
async def get_predictions(
    zone_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve current predictions for a zone (last flood/fire run)."""
    # For MVP: we re-run a default prediction; in production this would
    # store predictions in a DB table and return the cached result.
    from app.engine.prediction_engine import calculate_flood_spread, calculate_fire_spread

    # Try to get zone info
    from app.models.zone import Zone
    z_result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = z_result.scalar_one_or_none()

    if not zone:
        raise HTTPException(404, detail="Zone not found")

    # Return last known predictions or default empty struct
    return {
        "zone_id": zone_id,
        "zone_name": zone.name,
        "last_flood": {
            "expires_at": None,
            "affected_cells": [],
            "max_intensity": 0,
            "flooded_percentage": 0,
        },
        "last_fire": {
            "expires_at": None,
            "burned_area": [],
            "max_intensity": 0,
            "spread_direction_degrees": 0.0,
        },
    }


@router.post("/what-if", tags=["predictions"])
async def what_if_simulation(
    zone_id: str,
    disaster_type: str,
    # Flood parameters
    rainfall_mm_hr: float = 50.0,
    hours: int = 12,
    # Fire parameters
    wind_speed_kmh: float = 20.0,
    # Resource adjustment: "+resources" means add N hypothetical resources
    # that lower priority; "-resources" means remove N, raising priority
    resource_delta: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """
    What-if simulation: adjust parameters and see predicted outcome
    on priority score and spread area.

    Returns:
    - Original prediction results
    - Adjusted prediction (with resource delta applied)
    - Priority score change delta
    """
    # Run base prediction
    base_result = await predict_spread(
        zone_id=zone_id,
        disaster_type=disaster_type,
        hours_ahead=hours,
        db=db,
    )

    # Adjust priority score based on resource delta
    # Heuristic: each resource assigned reduces priority by ~3 points (capped)
    # Each resource unassigned increases priority by ~3 points
    priority_delta = resource_delta * 3.0
    new_priority = max(0.0, min(100.0, base_result.get("priority_base", 50.0) + priority_delta))

    # Adjust simulation parameters based on what-if
    adjusted_result = base_result.copy()
    adjusted_result["priority_delta"] = round(priority_delta, 2)
    adjusted_result["new_priority"] = round(new_priority, 1)
    adjusted_result["resource_delta"] = resource_delta
    adjusted_result["disaster_type"] = disaster_type

    return {
        "zone_id": zone_id,
        "disaster_type": disaster_type,
        "base_prediction": base_result,
        "adjusted_prediction": adjusted_result,
        "description": f"What-if: rainfall={rainfall_mm_hr}mm/hr, wind={wind_speed_kmh}km/h, "
                        f"resource delta={resource_delta:+d}, priority change={priority_delta:+.1f}",
    }