"""Deterministic Phase 2 intelligence services.

These services provide explainable MVP baselines until trained models are deployed.
They deliberately avoid persistence so they can run against the existing schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any


MODEL_REGISTRY = {
    "victim-detection": {"version": "v1", "status": "ready", "runtime": "pytorch-cpu"},
    "behaviour-risk": {"version": "v1", "status": "ready", "runtime": "rules-baseline"},
    "supply-forecast": {"version": "v1", "status": "ready", "runtime": "rules-baseline"},
    "volunteer-matching": {"version": "v1", "status": "ready", "runtime": "rules-baseline"},
}


@dataclass(frozen=True)
class BehaviourAssessment:
    risk_score: float
    risk_level: str
    factors: list[str]
    recommended_action: str


def assess_behaviour(*, crowd_density: float, movement_speed: float, exits_available: int, distress_reports: int) -> BehaviourAssessment:
    """Estimate crowd risk using normalized, inspectable signals."""
    score = min(
        100.0,
        max(
            0.0,
            crowd_density * 0.45
            + min(movement_speed / 2.0, 100.0) * 0.2
            + max(0, 3 - exits_available) * 12.0
            + min(distress_reports * 4.0, 32.0),
        ),
    )
    level = "critical" if score >= 75 else "high" if score >= 50 else "moderate" if score >= 25 else "low"
    factors: list[str] = []
    if crowd_density >= 70:
        factors.append("high crowd density")
    if movement_speed >= 2:
        factors.append("rapid movement")
    if exits_available < 2:
        factors.append("limited exits")
    if distress_reports > 0:
        factors.append(f"{distress_reports} distress reports")
    return BehaviourAssessment(
        risk_score=round(score, 1),
        risk_level=level,
        factors=factors or ["no elevated behaviour signal"],
        recommended_action="open additional exits and deploy crowd stewards" if score >= 50 else "continue monitoring",
    )


def forecast_supply(*, current_stock: int, daily_consumption: float, incoming_units: int = 0, horizon_days: int = 3) -> dict[str, Any]:
    """Forecast stock coverage and flag shortages before they occur."""
    demand = max(0.0, daily_consumption) * max(1, horizon_days)
    projected_stock = current_stock + max(0, incoming_units) - demand
    coverage_days = round((current_stock + max(0, incoming_units)) / daily_consumption, 1) if daily_consumption > 0 else None
    risk = "critical" if projected_stock < 0 else "watch" if coverage_days is not None and coverage_days < 2 else "stable"
    return {
        "current_stock": current_stock,
        "incoming_units": max(0, incoming_units),
        "daily_consumption": daily_consumption,
        "horizon_days": max(1, horizon_days),
        "projected_stock": round(projected_stock, 1),
        "coverage_days": coverage_days,
        "shortage_risk": risk,
        "recommended_reorder_units": max(0, round(demand - current_stock - max(0, incoming_units))),
    }


def match_volunteers(*, volunteers: list[dict[str, Any]], mission: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank volunteers by skill match, distance, and availability."""
    required = {str(skill).lower() for skill in mission.get("required_skills", [])}
    mission_lat = float(mission.get("lat", 0))
    mission_lng = float(mission.get("lng", 0))
    ranked = []
    for volunteer in volunteers:
        if not volunteer.get("available", True):
            continue
        skills = {str(skill).lower() for skill in volunteer.get("skills", [])}
        matched = sorted(required & skills)
        distance = hypot(float(volunteer.get("lat", 0)) - mission_lat, float(volunteer.get("lng", 0)) - mission_lng)
        score = len(matched) * 60 + max(0, 40 - distance * 10)
        ranked.append({**volunteer, "matched_skills": matched, "distance_score": round(distance, 3), "match_score": round(score, 1)})
    return sorted(ranked, key=lambda item: item["match_score"], reverse=True)


def model_status(model_name: str | None = None) -> dict[str, Any]:
    models = MODEL_REGISTRY if model_name is None else {model_name: MODEL_REGISTRY.get(model_name)}
    return {"models": models, "healthy": all(value is not None for value in models.values())}
