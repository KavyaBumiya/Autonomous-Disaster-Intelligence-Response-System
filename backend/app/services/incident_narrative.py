"""
AEGIS-AI — Incident narrative persistence
==========================================
Fills Incident.groq_summary and Incident.groq_explanation from the Groq
Gateway using ONLY deterministic engine evidence (PRD §8).

The LLM words the narrative; it never invents priority scores, victim counts,
or resource recommendations. Fields are written once (or forced on demand)
so Evidence / Approval panels can read them without re-calling Groq every time.
"""
from __future__ import annotations

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.services.groq_gateway import groq_gateway

logger = structlog.get_logger()


async def _evidence_bundle(incident: Incident, db: AsyncSession) -> dict:
    """Structured evidence handed to the summariser — engine output plus
    external evidence with provider/retrieved_at attribution (PRD §33)."""
    from app.services.evidence_fusion import evidence_fusion

    bundle = {
        "incident_id": incident.id,
        "zone_id": incident.zone_id,
        "disaster_type": incident.disaster_type,
        "priority_score": incident.priority_score,
        "priority_band": incident.priority_band,
        "severity": incident.severity_score,
        "confidence": incident.confidence,
        "victim_count": incident.victim_count,
        "victim_confidence": incident.victim_confidence,
        "report_count": incident.report_count,
        "avg_trust": incident.avg_trust_score,
        "status": incident.status,
        "xai_reasoning": incident.xai_reasoning,
        "created_at": incident.created_at.isoformat() if incident.created_at else None,
    }
    bundle["external_evidence"] = await evidence_fusion.incident_attribution(
        incident.id, db
    )
    return bundle


async def ensure_incident_narrative(
    incident: Incident,
    db: AsyncSession,
    *,
    force: bool = False,
) -> Incident:
    """
    Populate groq_summary / groq_explanation when missing (or when force=True).

    Safe to call repeatedly — no-ops when both fields are already set and
    force is False. Groq failures leave the fields untouched (original XAI
    string remains available to the UI).
    """
    need_summary = force or not (incident.groq_summary or "").strip()
    need_explain = force or not (incident.groq_explanation or "").strip()
    if not need_summary and not need_explain:
        return incident

    if need_summary:
        try:
            incident.groq_summary = await groq_gateway.summarise_incident(
                await _evidence_bundle(incident, db)
            )
        except Exception as exc:
            logger.warning(
                "groq_summary_failed",
                incident_id=incident.id,
                error=str(exc),
            )

    if need_explain and (incident.xai_reasoning or "").strip():
        try:
            incident.groq_explanation = await groq_gateway.explain_xai(
                xai_reasoning=incident.xai_reasoning or "",
                incident_id=incident.id,
            )
        except Exception as exc:
            logger.warning(
                "groq_explanation_failed",
                incident_id=incident.id,
                error=str(exc),
            )

    await db.flush()
    logger.info(
        "incident_narrative_updated",
        incident_id=incident.id,
        summary=bool(incident.groq_summary),
        explanation=bool(incident.groq_explanation),
        forced=force,
    )
    return incident


async def ensure_narratives_for_actions(
    incident_ids: list[str],
    db: AsyncSession,
) -> None:
    """Batch-fill narratives for incidents referenced by the approval queue."""
    if not incident_ids:
        return

    from sqlalchemy import select

    result = await db.execute(
        select(Incident).where(Incident.id.in_(incident_ids))
    )
    for incident in result.scalars().all():
        await ensure_incident_narrative(incident, db)
