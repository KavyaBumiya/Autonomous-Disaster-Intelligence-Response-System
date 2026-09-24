"""Prediction endpoints — Phase 3.
Flood & fire spread simulation + what-if scenario analysis.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.engine.prediction_engine import predict_spread

router = APIRouter()


class FloodPredictionBody(BaseModel):
    zone_id: str
    hours: int = 12
    rainfall_mm_hr: float = 50.0


class FirePredictionBody(BaseModel):
    zone_id: str
    hours: int = 12
    wind_speed_kmh: float = 20.0


class WhatIfBody(BaseModel):
    zone_id: str
    disaster_type: str = "flood"
    rainfall_mm_hr: float = 50.0
    hours: int = 12
    wind_speed_kmh: float = 20.0
    resource_delta: int = 0


@router.post("/flood", tags=["predictions"])
async def predict_flood(body: FloodPredictionBody, db: AsyncSession = Depends(get_db)):
    """Run flood spread simulation for a zone."""
    try:
        result = await predict_spread(
            zone_id=body.zone_id,
            disaster_type="flood",
            hours_ahead=body.hours,
            db=db,
        )
        return {
            "disaster_type": "flood",
            "zone_id": body.zone_id,
            "hours_ahead": body.hours,
            "rainfall_mm_hr": body.rainfall_mm_hr,
            "result": result,
        }
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.post("/fire", tags=["predictions"])
async def predict_fire(body: FirePredictionBody, db: AsyncSession = Depends(get_db)):
    """Run fire spread simulation for a zone."""
    try:
        result = await predict_spread(
            zone_id=body.zone_id,
            disaster_type="fire",
            hours_ahead=body.hours,
            db=db,
        )
        return {
            "disaster_type": "fire",
            "zone_id": body.zone_id,
            "hours_ahead": body.hours,
            "wind_speed_kmh": body.wind_speed_kmh,
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
    from app.models.zone import Zone

    z_result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = z_result.scalar_one_or_none()

    if not zone:
        raise HTTPException(404, detail="Zone not found")

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
async def what_if_simulation(body: WhatIfBody, db: AsyncSession = Depends(get_db)):
    """
    What-if simulation: adjust parameters and see predicted outcome
    on priority score and spread area.
    """
    base_result = await predict_spread(
        zone_id=body.zone_id,
        disaster_type=body.disaster_type,
        hours_ahead=body.hours,
        db=db,
    )

    priority_delta = body.resource_delta * 3.0
    new_priority = max(
        0.0, min(100.0, float(base_result.get("priority_base", 50.0)) + priority_delta)
    )

    adjusted_result = dict(base_result)
    adjusted_result["priority_delta"] = round(priority_delta, 2)
    adjusted_result["new_priority"] = round(new_priority, 1)
    adjusted_result["resource_delta"] = body.resource_delta
    adjusted_result["disaster_type"] = body.disaster_type
    adjusted_result["rainfall_mm_hr"] = body.rainfall_mm_hr
    adjusted_result["wind_speed_kmh"] = body.wind_speed_kmh

    return {
        "zone_id": body.zone_id,
        "disaster_type": body.disaster_type,
        "base_prediction": base_result,
        "adjusted_prediction": adjusted_result,
        "new_priority": round(new_priority, 1),
        "priority_delta": round(priority_delta, 2),
        "description": (
            f"What-if: rainfall={body.rainfall_mm_hr}mm/hr, wind={body.wind_speed_kmh}km/h, "
            f"resource delta={body.resource_delta:+d}, priority change={priority_delta:+.1f}"
        ),
    }
