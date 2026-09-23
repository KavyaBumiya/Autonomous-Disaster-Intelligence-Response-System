"""Phase 2 intelligence endpoints.

The endpoints expose explainable MVP baselines for behaviour, supply, volunteers,
and model serving health. They are intentionally stateless until production
model and volunteer records are introduced.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.services.phase2 import assess_behaviour, forecast_supply, match_volunteers, model_status

router = APIRouter(prefix="/api/phase2")


class BehaviourRequest(BaseModel):
    crowd_density: float = Field(ge=0, le=100)
    movement_speed: float = Field(ge=0, description="Estimated metres per second")
    exits_available: int = Field(ge=0)
    distress_reports: int = Field(ge=0)


class SupplyRequest(BaseModel):
    current_stock: int = Field(ge=0)
    daily_consumption: float = Field(ge=0)
    incoming_units: int = Field(default=0, ge=0)
    horizon_days: int = Field(default=3, ge=1, le=30)


class VolunteerMission(BaseModel):
    required_skills: list[str] = Field(default_factory=list)
    lat: float
    lng: float


class VolunteerMatchRequest(BaseModel):
    mission: VolunteerMission
    volunteers: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/models")
async def list_models(_: dict = Depends(get_current_user)):
    return model_status()


@router.get("/models/{model_name}")
async def get_model(model_name: str, _: dict = Depends(get_current_user)):
    result = model_status(model_name)
    if not result["healthy"]:
        raise HTTPException(status_code=404, detail=f"Model '{model_name}' is not registered")
    return result


@router.post("/behaviour/assess")
async def assess_behaviour_risk(body: BehaviourRequest, _: dict = Depends(get_current_user)):
    assessment = assess_behaviour(**body.model_dump())
    return {"model": "behaviour-risk", **assessment.__dict__}


@router.post("/supply/forecast")
async def forecast_supply_shortage(body: SupplyRequest, _: dict = Depends(get_current_user)):
    return {"model": "supply-forecast", **forecast_supply(**body.model_dump())}


@router.post("/volunteers/match")
async def match_volunteer_mission(body: VolunteerMatchRequest, _: dict = Depends(get_current_user)):
    return {
        "model": "volunteer-matching",
        "mission": body.mission.model_dump(),
        "matches": match_volunteers(
            volunteers=body.volunteers,
            mission=body.mission.model_dump(),
        ),
    }
