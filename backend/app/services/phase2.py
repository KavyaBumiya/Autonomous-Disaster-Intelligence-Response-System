"""Deterministic Phase 2 intelligence services.

These services provide explainable MVP baselines. Only hazards with a shipped
artifact are fitted to observed data; the rest are arithmetic and are reported as
untrained, because a registry entry that claims `"status": "ready"` for a
hand-written threshold is a claim the code cannot back up.

They deliberately avoid persistence so they can run against the existing schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from typing import Any

from app.ml.occurrence_model import available_models, get_occurrence_model

# Every entry states what actually computes it. `trained: False` means the
# numbers come from coefficients a human typed, not from fitting them to data.
_STATIC_REGISTRY = {
    "behaviour-risk": {
        "version": "v1",
        "runtime": "rules-baseline",
        "trained": False,
        "implemented_by": "app.services.phase2.assess_behaviour",
    },
    "supply-forecast": {
        "version": "v1",
        "runtime": "rules-baseline",
        "trained": False,
        "implemented_by": "app.services.phase2.forecast_supply",
    },
    "volunteer-matching": {
        "version": "v1",
        "runtime": "rules-baseline",
        "trained": False,
        "implemented_by": "app.services.phase2.match_volunteers",
    },
    "victim-detection": {
        # Not a Phase 2 function and not trained here: image_analysis runs a
        # pretrained HuggingFace detector and loads it lazily on first use.
        "version": "pretrained-checkpoint",
        "runtime": "huggingface-inference",
        "trained": False,
        "implemented_by": "app.ai.vision.image_analysis",
    },
}


def _trained_entry(hazard: str) -> dict[str, Any]:
    """Live status of one fitted hazard model, read from its artifact.

    Built per hazard rather than written out once for flood, because three
    artifacts now ship and a hand-maintained list understated that. Reporting
    one fitted model while three were on disk is exactly the kind of claim this
    registry exists to avoid making.
    """
    model = get_occurrence_model(hazard)
    info = model.info()
    entry_name = f"{hazard}-occurrence"
    if not info.get("available"):
        return {
            "version": "none",
            "runtime": "rules-baseline (fallback)",
            "trained": False,
            "implemented_by": f"app.ml.occurrence_model.OccurrenceModel[{hazard}]",
            "available": False,
            "reason": info.get("reason"),
        }
    metrics = info.get("metrics") or {}
    return {
        "version": info.get("model_version"),
        "runtime": "trained-logistic",
        "trained": True,
        "implemented_by": f"app.ml.occurrence_model.OccurrenceModel[{hazard}]",
        "available": True,
        "trained_at": info.get("trained_at"),
        "roc_auc": metrics.get("roc_auc"),
        "roc_auc_baseline_rule": metrics.get("roc_auc_baseline_rule"),
        "beats_single_feature": bool(metrics.get("beats_single_feature", True)),
        "rows": metrics.get("rows"),
        "positives": metrics.get("positives"),
        "training_data": (info.get("training_data") or {}).get("labels"),
        "limitations": info.get("limitations"),
    }


def model_registry() -> dict[str, Any]:
    """The full registry, with every fitted hazard reported from its artifact.

    Driven off `available_models()` so a hazard cannot ship an artifact without
    appearing here, and cannot be listed as trained without an artifact.
    """
    trained = {
        f"{hazard}-occurrence": _trained_entry(hazard)
        for hazard, available in available_models().items()
        if available
    }
    return {**_STATIC_REGISTRY, **trained}


# Kept for existing importers; prefer model_registry() for live status.
MODEL_REGISTRY = _STATIC_REGISTRY


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
    """Health of the model registry.

    `healthy` now means every registered model is either loaded or has a
    working fallback. It previously meant only that the entry existed, so an
    untrained rule and a fitted model both reported "ready".
    """
    models = model_registry() if model_name is None else model_registry().get(model_name)
    if model_name is not None and models is None:
        return {"models": {model_name: None}, "healthy": False}

    entries = {model_name: models} if model_name is not None else models
    healthy = all(
        entry is not None
        and (entry.get("available") is not False or not entry.get("trained"))
        for entry in entries.values()
    )
    return {
        "models": models,
        "healthy": healthy,
        "trained_models": [k for k, v in entries.items() if (v or {}).get("trained")],
        "untrained_models": [
            k for k, v in entries.items() if v is not None and not v.get("trained")
        ],
    }
