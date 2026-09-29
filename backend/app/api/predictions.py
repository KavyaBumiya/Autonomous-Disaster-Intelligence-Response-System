"""Prediction endpoints — Phase 3.
Flood & fire spread simulation + what-if scenario analysis.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import structlog

from app.core.database import get_db
from app.engine.prediction_engine import predict_all_hazards, predict_spread

logger = structlog.get_logger()

router = APIRouter()


async def _emit_prediction(zone_id: str, disaster_type: str, result: dict) -> None:
    """WebSocket prediction_updated (§25) — enrichment only; cells trimmed
    from the WS payload (HTTP contract keeps the full result)."""
    try:
        from app.services.websocket import emit_prediction_updated

        cells = result.get("cells")
        trimmed = {k: v for k, v in result.items() if k != "cells"}
        if cells is not None:
            trimmed["cells_count"] = len(cells)
        await emit_prediction_updated(zone_id, disaster_type, trimmed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("prediction_updated_emit_failed", zone_id=zone_id, error=str(exc))


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
    """Run flood spread simulation for a zone (driven by body.rainfall_mm_hr)."""
    try:
        result = await predict_spread(
            zone_id=body.zone_id,
            disaster_type="flood",
            hours_ahead=body.hours,
            db=db,
            rainfall_mm_hr=body.rainfall_mm_hr,
        )
        await _emit_prediction(body.zone_id, "flood", result)
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
    """Run fire spread simulation for a zone (driven by body.wind_speed_kmh)."""
    try:
        result = await predict_spread(
            zone_id=body.zone_id,
            disaster_type="fire",
            hours_ahead=body.hours,
            db=db,
            wind_speed_kmh=body.wind_speed_kmh,
        )
        await _emit_prediction(body.zone_id, "fire", result)
        return {
            "disaster_type": "fire",
            "zone_id": body.zone_id,
            "hours_ahead": body.hours,
            "wind_speed_kmh": body.wind_speed_kmh,
            "result": result,
        }
    except ValueError as e:
        raise HTTPException(400, detail=str(e))


@router.get("/all/{zone_id}", tags=["predictions"])
async def get_all_hazard_predictions(
    zone_id: str,
    hours: int = 12,
    db: AsyncSession = Depends(get_db),
):
    """Every modelled hazard for a zone in one uniform envelope.

    Declared before `/{zone_id}` so the literal `all` segment cannot be
    captured as a zone id. Unlike `/{zone_id}`, this returns a list of hazards
    so the console renders new hazards without a frontend change, and each
    entry reports its own `available` flag and `reason` rather than silently
    returning a zero-valued projection.
    """
    try:
        return await predict_all_hazards(zone_id=zone_id, hours_ahead=hours, db=db)
    except ValueError as e:
        raise HTTPException(404, detail=str(e))


@router.get("/{zone_id}", tags=["predictions"])
async def get_predictions(
    zone_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Current MODEL PROJECTION state for a zone — flood & fire runs computed
    from the latest real inputs (weather readings + evidence + GIS context).
    Previously returned an always-empty stub (additive fix, Phase 10)."""
    from app.models.zone import Zone

    z_result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = z_result.scalar_one_or_none()

    if not zone:
        raise HTTPException(404, detail="Zone not found")

    async def _run(kind: str, **kwargs) -> dict | None:
        try:
            return await predict_spread(
                zone_id=zone_id, disaster_type=kind, hours_ahead=12, db=db, **kwargs
            )
        except ValueError:
            return None

    last_flood = await _run("flood")
    last_fire = await _run("fire")

    return {
        "zone_id": zone_id,
        "zone_name": zone.name,
        "projection_label": "MODEL PROJECTION",
        "last_flood": last_flood
        or {
            "expires_at": None,
            "affected_cells": [],
            "max_intensity": 0,
            "flooded_percentage": 0,
        },
        "last_fire": last_fire
        or {
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
    # What-if contract unchanged: parameter-in → deterministic engine.
    # Body parameters now actually drive the base run (previously ignored;
    # body defaults 50/20 equal the legacy hard-coded values).
    kind = body.disaster_type.lower()
    try:
        base_result = await predict_spread(
            zone_id=body.zone_id,
            disaster_type=body.disaster_type,
            hours_ahead=body.hours,
            db=db,
            rainfall_mm_hr=body.rainfall_mm_hr if kind == "flood" else None,
            wind_speed_kmh=body.wind_speed_kmh if kind in ("fire", "storm") else None,
        )
    except ValueError as e:
        # An unsupported disaster_type is a client error, not a server fault.
        raise HTTPException(400, detail=str(e))

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

    await _emit_prediction(body.zone_id, body.disaster_type, adjusted_result)

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
