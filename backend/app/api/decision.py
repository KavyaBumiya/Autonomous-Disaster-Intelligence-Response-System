"""
Decision & Human Approval Endpoints.

Critical actions (evacuation, dispatch, resource allocation, emergency
communication) require human approval. The AI recommends; humans approve.

Endpoints:
    POST /api/decision/recommend  — AI generates recommendation
    POST /api/decision/approve    — Human approves a recommendation
    POST /api/decision/reject     — Human rejects a recommendation
    GET  /api/decision/pending    — List pending approvals
    GET  /api/decision/{decision_id} — Get decision details
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.core.database import get_db
from app.models.action import Action
from app.services.websocket import emit_action_state_changed

router = APIRouter(prefix="/api/decision", tags=["decision"])


# ── Request/Response Models ──────────────────────────────────────────────


class RecommendRequest(BaseModel):
    incident_id: str
    action_type: str = Field(..., pattern="^(evacuation|dispatch|resource_allocation|emergency_communication|rescue)$")
    context: dict[str, Any] = Field(default_factory=dict)
    hazard_type: str | None = None
    location: dict[str, Any] | None = None


class ApproveRequest(BaseModel):
    decision_id: str
    note: str | None = None


class RejectRequest(BaseModel):
    decision_id: str
    reason: str = Field(..., min_length=1)


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/recommend")
async def recommend(
    body: RecommendRequest,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(["commander", "analyst"])),
):
    """AI generates a recommendation for a critical action.

    The recommendation includes:
    - evidence
    - confidence
    - risk assessment
    - requires_human_approval: true (always for critical actions)
    """
    from app.ai.router.model_router import get_model_router
    from app.ai.providers.base import TaskType

    router = get_model_router()

    # Build recommendation context
    context = {
        "incident_id": body.incident_id,
        "action_type": body.action_type,
        "hazard_type": body.hazard_type,
        "location": body.location,
        **body.context,
    }

    # Get AI recommendation
    result = await router.route(
        TaskType.EXPLAINABILITY,
        context,
        hazard=body.hazard_type,
    )

    # Create pending action
    action = Action(
        id=str(uuid.uuid4()),
        incident_id=body.incident_id,
        action_type=body.action_type,
        description=f"AI Recommendation: {result.explanation}",
        recommended_by=f"ai_router:{result.model_id}",
        status="pending_approval",
        priority_score=result.confidence * 100,
    )
    db.add(action)
    await db.commit()

    return {
        "decision_id": action.id,
        "incident_id": body.incident_id,
        "action_type": body.action_type,
        "recommendation": result.prediction,
        "confidence": result.confidence,
        "evidence": result.evidence,
        "explanation": result.explanation,
        "model_used": result.model_id,
        "model_version": result.model_version,
        "requires_human_approval": True,
        "status": "pending_approval",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/approve")
async def approve(
    body: ApproveRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["commander"])),
):
    """Human approves a pending recommendation."""
    result = await db.execute(select(Action).where(Action.id == body.decision_id))
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(404, detail="Decision not found")

    if action.status != "pending_approval":
        raise HTTPException(400, detail=f"Decision is not pending (status: {action.status})")

    action.status = "approved"
    action.approved_by = user["user_id"]
    action.approval_note = body.note
    action.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Emit WebSocket event
    await emit_action_state_changed(
        action.id,
        action.zone_id,
        "approved",
        user["role"],
    )

    return {
        "decision_id": action.id,
        "status": "approved",
        "approved_by": user["user_id"],
        "note": body.note,
        "message": "Action approved — execution authorized",
    }


@router.post("/reject")
async def reject(
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(require_role(["commander"])),
):
    """Human rejects a pending recommendation."""
    result = await db.execute(select(Action).where(Action.id == body.decision_id))
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(404, detail="Decision not found")

    if action.status != "pending_approval":
        raise HTTPException(400, detail=f"Decision is not pending (status: {action.status})")

    action.status = "rejected"
    action.approved_by = user["user_id"]
    action.approval_note = body.reason
    action.updated_at = datetime.now(timezone.utc)
    await db.commit()

    # Emit WebSocket event
    await emit_action_state_changed(
        action.id,
        action.zone_id,
        "rejected",
        user["role"],
    )

    return {
        "decision_id": action.id,
        "status": "rejected",
        "rejected_by": user["user_id"],
        "reason": body.reason,
        "message": "Action rejected — execution blocked",
    }


@router.get("/pending")
async def pending_decisions(
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(["commander"])),
):
    """List all pending decisions."""
    result = await db.execute(
        select(Action)
        .where(Action.status == "pending_approval")
        .order_by(Action.priority_score.desc())
    )
    actions = result.scalars().all()

    return {
        "pending_count": len(actions),
        "decisions": [
            {
                "decision_id": a.id,
                "incident_id": a.incident_id,
                "zone_id": a.zone_id,
                "action_type": a.action_type,
                "description": a.description,
                "recommended_by": a.recommended_by,
                "priority_score": a.priority_score,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in actions
        ],
    }


@router.get("/{decision_id}")
async def get_decision(
    decision_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Get decision details."""
    result = await db.execute(select(Action).where(Action.id == decision_id))
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(404, detail="Decision not found")

    return {
        "decision_id": action.id,
        "incident_id": action.incident_id,
        "zone_id": action.zone_id,
        "action_type": action.action_type,
        "description": action.description,
        "recommended_by": action.recommended_by,
        "priority_score": action.priority_score,
        "status": action.status,
        "approved_by": action.approved_by,
        "approval_note": action.approval_note,
        "created_at": action.created_at.isoformat() if action.created_at else None,
        "updated_at": action.updated_at.isoformat() if action.updated_at else None,
    }
