"""
AEGIS-AI — Command Center API
==============================
Replaces the Ollama-based endpoint with the NVIDIA NIM AI Gateway.

Architecture (PRD §4, §9):
  Commander query
    → AI Gateway (NVIDIA NIM — language understanding, tool orchestration, explanation)
    → ToolExecutor (actual DB reads / engine calls — never the LLM directly)
    → Deterministic Decision Engine  (priority numbers — never the LLM)
    → Human Approval Gate            (for safety-critical actions)
    → Response with XAI evidence

SECURITY:
  • NVIDIA_API_KEY lives only in the backend process (.env → settings).
  • The key is never serialised into any HTTP response.
  • The frontend receives only the natural-language response and structured data.

HUMAN APPROVAL GATE (PRD §9):
  The LLM cannot approve, reject, or bypass any action.
  All action state changes go through PATCH /api/actions/{id}
  which requires commander role and creates an audit record.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user, require_role
from app.core.config import get_settings
from app.core.database import get_db
from app.models.incident import Incident
from app.models.resource import Resource
from app.models.zone import Zone
from app.services.ai_gateway import ai_gateway, ToolExecutor, CommandQueryResponse

logger   = structlog.get_logger()
settings = get_settings()

router = APIRouter(prefix="/api/command", tags=["command center"])


# The UI polls this endpoint, so the live NIM probe is cached briefly to avoid
# spending a completion call (and a rate-limit slot) on every poll.
_PROBE_TTL_SECONDS = 60.0
_probe_cache: dict = {"at": 0.0, "result": {}}


async def _nvidia_probe_cached() -> dict:
    now = time.monotonic()
    if now - _probe_cache["at"] < _PROBE_TTL_SECONDS:
        return _probe_cache["result"]
    try:
        result = await ai_gateway._get_connector().health()
    except Exception as exc:  # never let a probe break the health endpoint
        result = {"provider": "nvidia", "status": "OFFLINE", "reason": type(exc).__name__}
    _probe_cache.update({"at": now, "result": result})
    return result


# ─── Request / Response models ───────────────────────────────────────────

class CommandQueryRequest(BaseModel):
    user_query:          str       = Field(..., min_length=1, max_length=2000,
                                           description="Natural-language commander query")
    model_name:          str | None = Field(None, description="Override LLM model")
    conversation_id:     str | None = Field(None, description="Multi-turn conversation ID")
    include_xai:         bool       = Field(True,  description="Include XAI evidence in response")
    zone_context:        str | None = Field(None,  description="Current zone ID for context")


class FunctionCallInfo(BaseModel):
    name:      str
    arguments: dict


class CommandResponseModel(BaseModel):
    response:          str
    function_calls:    list[FunctionCallInfo] = []
    execution_results: list[dict]             = []
    execution_time:    float                  = 0.0
    model_used:        str                    = ""
    ai_available:      bool                   = False
    ai_configured:     bool                   = False
    ai_call_id:        str                    = ""
    conversation_id:   str | None             = None


# ─── Health check ────────────────────────────────────────────────────────

@router.get("/health")
async def command_health():
    """
    Check whether the AI Gateway is configured AND actually authenticating.

    A configured key is not proof of a working one, so this runs a real probe
    against NIM (cached briefly) rather than just checking that the key exists.
    The key itself is never exposed.
    """
    configured = ai_gateway.available
    probe: dict = {}
    if configured:
        probe = await _nvidia_probe_cached()

    online = bool(probe.get("status") == "ONLINE")
    if not configured:
        note = "NVIDIA_API_KEY not set — using offline fallback"
    elif online:
        note = "NVIDIA NIM AI Gateway ready"
    else:
        reason = probe.get("reason") or "probe failed"
        note = f"NVIDIA NIM unreachable ({reason}) — using offline fallback"

    return {
        "ai_available": online,
        "ai_configured": configured,
        "model":        settings.nvidia_model if online else None,
        "provider":     "nvidia-nim",
        "note":         note,
    }


# ─── Primary query endpoint ──────────────────────────────────────────────

@router.post("/query", response_model=CommandResponseModel)
async def command_query(
    request: CommandQueryRequest,
    db:      AsyncSession = Depends(get_db),
    current_user: dict    = Depends(require_role(["commander", "responder", "analyst"])),
):
    """
    Process a natural-language commander query via the AI Gateway.

    The LLM:
      ✓ understands the query
      ✓ calls backend tools to gather evidence
      ✓ summarises and explains results
      ✗ does NOT independently assign priority scores
      ✗ does NOT allocate resources or authorise dispatch
      ✗ does NOT bypass the human approval gate
    """
    start = datetime.now(timezone.utc)

    # Build a ToolExecutor bound to this request's DB session
    executor = ToolExecutor(db=db)

    # Optional: prepend zone context so the model knows where to focus
    query = request.user_query
    if request.zone_context:
        query = f"[Current zone context: {request.zone_context}]\n\n{query}"

    # Multi-turn history (Redis, PRD §11) — empty when conversation_id omitted
    conversation_history: list[dict] = []
    if request.conversation_id:
        from app.services.conversation_store import load_history, append_turn
        conversation_history = await load_history(request.conversation_id)

    try:
        result: CommandQueryResponse = await ai_gateway.command_query(
            user_query=query,
            tool_executor=executor,
            model_override=request.model_name,
            conversation_history=conversation_history,
        )
    except Exception as exc:
        logger.error("command_query_failed", error=str(exc), user=current_user.get("user_id"))
        # Never raise 500 for commander — degrade gracefully
        result = CommandQueryResponse(
            response=(
                "⚠️  AI Gateway encountered an error. "
                "The deterministic engine and all data APIs remain operational. "
                f"Error detail: {str(exc)[:120]}"
            ),
            model_used="error-fallback",
            ai_used=False,
        )

    # Persist this exchange for follow-up questions
    if request.conversation_id:
        try:
            await append_turn(request.conversation_id, request.user_query, result.response)
        except Exception as conv_exc:
            logger.warning("conversation_persist_failed", error=str(conv_exc))

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    logger.info(
        "command_query",
        user_id=current_user.get("user_id"),
        role=current_user.get("role"),
        tools_called=[fc.get("name") for fc in result.function_calls],
        ai_available=result.ai_used,
        ai_configured=ai_gateway.available,
        conversation_id=request.conversation_id,
        history_turns=len(conversation_history),
        elapsed_s=round(elapsed, 2),
    )

    response_model = CommandResponseModel(
        response=result.response,
        function_calls=[
            FunctionCallInfo(name=fc.get("name", ""), arguments=fc.get("arguments", {}))
            for fc in result.function_calls
        ],
        execution_results=result.execution_results,
        execution_time=result.execution_time or elapsed,
        model_used=result.model_used,
        # Truthful per request: the AI produced this reply or it did not. A
        # configured key alone is reported separately as ai_configured, which
        # mirrors the split already exposed by GET /api/command/health.
        ai_available=result.ai_used,
        ai_configured=ai_gateway.available,
        ai_call_id=result.ai_call_id,
        conversation_id=request.conversation_id,
    )

    # WebSocket: command_interaction (§25) — enrichment only, never breaks the reply
    try:
        from app.services.websocket import emit_command_interaction

        await emit_command_interaction(
            user_id=current_user.get("user_id", ""),
            query=request.user_query,
            response={
                "response": response_model.response[:500],
                "function_calls": [fc.name for fc in response_model.function_calls],
                "model_used": response_model.model_used,
            },
            source="command_center",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("command_interaction_emit_failed", error=str(exc))

    return response_model


# ─── XAI Explanation endpoint ────────────────────────────────────────────

@router.get("/explain/{incident_id}")
async def explain_incident(
    incident_id:  str,
    db:           AsyncSession = Depends(get_db),
    current_user: dict         = Depends(get_current_user),
):
    """
    Generate a plain-English explanation of an incident's priority and evidence.
    The AI layer explains the output of the deterministic engine — it does not
    produce the score.
    """
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(404, detail="Incident not found")

    explanation = await ai_gateway.explain_xai(
        xai_reasoning=incident.xai_reasoning or "",
        incident_id=incident_id,
    )

    # Persist for Evidence / Approval panels (PRD §8)
    if explanation and explanation != (incident.xai_reasoning or ""):
        incident.groq_explanation = explanation
        await db.commit()

    # Additive source attribution for persisted evidence (PRD §33)
    from app.services.evidence_fusion import evidence_fusion

    attribution = await evidence_fusion.incident_attribution(incident_id, db)

    return {
        "incident_id":    incident_id,
        "priority_score": incident.priority_score,
        "priority_band":  _band_label(incident.priority_score),
        "explanation":    explanation,
        "xai_raw":        incident.xai_reasoning,
        "ai_used":        ai_gateway.available,
        "evidence_attribution": attribution,
    }


# ─── Incident summary endpoint ───────────────────────────────────────────

@router.get("/summarise/{incident_id}")
async def summarise_incident(
    incident_id:  str,
    db:           AsyncSession = Depends(get_db),
    current_user: dict         = Depends(get_current_user),
):
    """
    Generate a concise operational summary for a commander briefing.
    """
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(404, detail="Incident not found")

    evidence = {
        "incident_id":   incident_id,
        "disaster_type": incident.disaster_type,
        "priority_score": incident.priority_score,
        "victim_count":  incident.victim_count,
        "report_count":  incident.report_count,
        "avg_trust":     incident.avg_trust_score,
        "severity":      incident.severity_score,
        "status":        incident.status,
        "created_at":    incident.created_at.isoformat() if incident.created_at else None,
    }

    summary = await ai_gateway.summarise_incident(evidence)

    # Persist for dashboard panels (PRD §8)
    if summary:
        incident.groq_summary = summary
        await db.commit()

    return {
        "incident_id": incident_id,
        "summary":     summary,
        "evidence":    evidence,
        "ai_used":     ai_gateway.available,
    }


# ─── Convenience read-only endpoints (no LLM, direct DB) ─────────────────

@router.get("/resources/available")
async def list_available_resources(
    db:           AsyncSession = Depends(get_db),
    current_user: dict         = Depends(require_role(["commander", "responder", "analyst"])),
):
    """List all resources that are available and below capacity."""
    result = await db.execute(
        select(Resource).where(
            and_(
                Resource.available == True,
                Resource.current_load < Resource.capacity,
            )
        ).order_by(Resource.name)
    )
    resources = result.scalars().all()
    total = len(resources)

    return {
        "resources": [
            {
                "id":            r.id,
                "name":          r.name,
                "resource_type": r.resource_type,
                "capacity":      r.capacity,
                "current_load":  r.current_load,
                "available":     r.available,
                "lat":           r.lat,
                "lng":           r.lng,
            }
            for r in resources
        ],
        "total":              total,
        "availability_ratio": total / max(1, total),
    }


@router.get("/zone-status")
async def zone_status(
    zone_id:      str            = Query(...),
    db:           AsyncSession   = Depends(get_db),
    current_user: dict           = Depends(require_role(["commander", "responder", "analyst"])),
):
    """Comprehensive zone overview — no LLM call, direct DB."""
    zone_result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone        = zone_result.scalar_one_or_none()

    incident_result = await db.execute(
        select(Incident).where(
            Incident.zone_id == zone_id,
            Incident.active  == True,
        ).limit(1)
    )
    incident = incident_result.scalar_one_or_none()

    res_result = await db.execute(
        select(Resource).where(
            and_(Resource.available == True, Resource.current_load < Resource.capacity)
        )
    )
    resources = res_result.scalars().all()

    return {
        "zone_id":   zone_id,
        "zone_name": zone.name if zone else None,
        "centroid":  {
            "lat": zone.centroid_lat if zone else None,
            "lng": zone.centroid_lng if zone else None,
        },
        "incident": {
            "id":              incident.id,
            "priority_score":  incident.priority_score,
            "priority_band":   _band_label(incident.priority_score),
            "disaster_type":   incident.disaster_type,
            "victim_count":    incident.victim_count,
            "victim_confidence": incident.victim_confidence,
            "status":          incident.status,
            "report_count":    incident.report_count,
            "avg_trust":       incident.avg_trust_score,
            "xai_reasoning":   incident.xai_reasoning,
        } if incident else None,
        "available_resource_count": len(resources),
    }


@router.get("/critical")
async def critical_incidents(
    threshold:    float        = Query(70.0, ge=0.0, le=100.0),
    limit:        int          = Query(10,   ge=1,   le=50),
    db:           AsyncSession = Depends(get_db),
    current_user: dict         = Depends(require_role(["commander", "responder", "analyst"])),
):
    """Incidents above the priority threshold — deterministic, no LLM."""
    result = await db.execute(
        select(Incident).where(
            Incident.priority_score >= threshold,
            Incident.active         == True,
        ).order_by(Incident.priority_score.desc()).limit(limit)
    )
    incidents = result.scalars().all()

    return {
        "threshold": threshold,
        "incidents": [
            {
                "incident_id":   inc.id,
                "zone_id":       inc.zone_id,
                "priority_score": inc.priority_score,
                "priority_band": _band_label(inc.priority_score),
                "disaster_type": inc.disaster_type,
                "victim_count":  inc.victim_count,
                "status":        inc.status,
                "xai_summary":   (inc.xai_reasoning or "")[:200],
            }
            for inc in incidents
        ],
        "total": len(incidents),
    }


@router.get("/reports")
async def incident_reports(
    incident_id:  str          = Query(...),
    limit:        int          = Query(10, ge=1, le=50),
    db:           AsyncSession = Depends(get_db),
    current_user: dict         = Depends(require_role(["commander", "responder", "analyst"])),
):
    """Recent reports for an incident/zone — direct DB, no LLM."""
    from app.models.report import Report

    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(404, detail="Incident not found")

    rpt_result = await db.execute(
        select(Report)
        .where(Report.zone_id == incident.zone_id)
        .order_by(Report.created_at.desc())
        .limit(limit)
    )
    reports = rpt_result.scalars().all()

    return {
        "incident_id": incident_id,
        "reports": [
            {
                "id":           r.id,
                "source":       r.source,
                "trust_score":  r.trust_score,
                "suppressed":   r.suppressed,
                "disaster_type": r.disaster_type,
                "excerpt":      (r.message_text or r.transcript or "")[:100],
                "lat":          r.lat,
                "lng":          r.lng,
                "created_at":   r.created_at.isoformat() if r.created_at else None,
            }
            for r in reports
        ],
        "total": len(reports),
    }


# ─── Approval queue read endpoint ────────────────────────────────────────

@router.get("/approval-queue")
async def approval_queue(
    db:           AsyncSession = Depends(get_db),
    current_user: dict         = Depends(require_role(["commander"])),
):
    """
    Return all actions pending human approval.
    Commanders review these before any dispatch is authorised.
    PRD §9: The LLM cannot approve these — only a human commander can.
    Missing AI narratives are generated (wording only — engine evidence
    is the source of truth) so the approval brief is self-contained.
    """
    from app.models.action import Action

    result = await db.execute(
        select(Action)
        .where(Action.status == "pending_approval")
        .order_by(Action.priority_score.desc())
    )
    actions = result.scalars().all()

    # Ensure each linked incident has summary + explanation for the brief
    try:
        from app.services.incident_narrative import ensure_narratives_for_actions
        await ensure_narratives_for_actions(
            list({a.incident_id for a in actions if a.incident_id}),
            db,
        )
        await db.commit()
    except Exception as exc:
        logger.warning("approval_queue_narrative_failed", error=str(exc))
        await db.rollback()

    # Reload actions + incidents after potential narrative fill
    incident_by_id: dict[str, object] = {}
    incident_ids = list({a.incident_id for a in actions if a.incident_id})
    if incident_ids:
        from app.models.incident import Incident

        inc_result = await db.execute(
            select(Incident).where(Incident.id.in_(incident_ids))
        )
        incident_by_id = {inc.id: inc for inc in inc_result.scalars().all()}

    return {
        "pending_count": len(actions),
        "actions": [
            {
                "action_id":       a.id,
                "incident_id":     a.incident_id,
                "zone_id":         a.zone_id,
                "action_type":     a.action_type,
                "description":     a.description,
                "recommended_by":  a.recommended_by,
                "priority_score":  a.priority_score,
                "priority_band":   _band_label(a.priority_score),
                "status":          a.status,
                "created_at":      a.created_at.isoformat() if a.created_at else None,
                "incident_summary": (
                    getattr(incident_by_id.get(a.incident_id), "groq_summary", None)
                ),
                "incident_explanation": (
                    getattr(incident_by_id.get(a.incident_id), "groq_explanation", None)
                ),
            }
            for a in actions
        ],
        "note": "All actions require explicit commander approval before dispatch. "
                "The AI cannot approve or bypass this gate.",
    }


# ─── Helper ──────────────────────────────────────────────────────────────

def _band_label(score: float | None) -> str:
    s = score or 0.0
    if s >= 85:
        return "CRITICAL"
    if s >= 70:
        return "HIGH"
    if s >= 40:
        return "MEDIUM"
    return "LOW"
