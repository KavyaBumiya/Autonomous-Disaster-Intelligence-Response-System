"""
AEGIS-AI — Agent Orchestrator
==============================
Runs the full intelligence pipeline after every new report is stored.

Phase 2 pipeline (updated):
  1. Groq report parser  — structured extraction from citizen text (fast, async)
  2. Zone upsert          — find or create zone from lat/lng
  3. Verification Agent   — multi-signal trust scoring
  4. Detection Agent      — disaster type classification
  5. Decision Engine      — deterministic PRD-aligned priority formula
  6. WebSocket events     — real-time dashboard updates

PRD §2 constraint: The LLM (Groq) is called ONLY in step 1 to parse raw text
into structured fields. All scoring and decision-making is deterministic.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentInput
from app.agents import detection, verification
from app.engine.decision import score_zone
from app.models.incident import Incident
from app.models.agent_output import AgentOutput as AgentOutputModel
from app.models.report import Report
from app.models.zone import Zone
from app.services.websocket import (
    emit_new_report,
    emit_trust_score_updated,
    emit_incident_priority_updated,
    emit_new_incident,
)

logger = structlog.get_logger()


async def process_report(report: Report, db: AsyncSession) -> None:
    """
    Entry point called after every new report is committed.

    Steps
    -----
    1. Parse raw text with Groq (if available) → enrich report fields
    2. Upsert zone from coordinates
    3. Verification Agent → trust score
    4. Detection Agent    → disaster type + severity
    5. Decision Engine    → priority score + XAI
    6. Emit WebSocket events
    """
    # ── Step 1: Groq report parsing (best-effort, never blocks pipeline) ──
    await _enrich_with_groq(report)

    # ── No location → skip spatial pipeline, still emit raw event ─────────
    if not report.lat or not report.lng:
        logger.debug("No location — skipping spatial pipeline", report_id=report.id)
        await emit_new_report({
            "id":           report.id,
            "source":       report.source,
            "trust_score":  None,
            "suppressed":   False,
            "disaster_type": report.disaster_type,
            "lat":          None,
            "lng":          None,
            "zone_id":      None,
            "message_text": report.message_text,
            "transcript":   report.transcript,
        })
        return

    # ── Step 2: Zone upsert ────────────────────────────────────────────────
    zone           = await _upsert_zone(report, db)
    report.zone_id = zone.id
    await db.flush()

    # ── Step 3: Verification Agent ─────────────────────────────────────────
    incident = await _get_or_create_incident(zone, db)

    verify_input  = AgentInput(
        incident_id=incident.id,
        zone_id=zone.id,
        report_ids=[report.id],
    )
    verify_output = await verification.run(verify_input, db)

    old_trust_score      = report.trust_score
    report.trust_score   = verify_output.payload.get("trust_score")
    report.suppressed    = verify_output.payload.get("suppressed", False)

    db.add(AgentOutputModel(
        id=str(uuid.uuid4()),
        agent_name=verify_output.agent_name,
        incident_id=incident.id,
        output_type=verify_output.output_type,
        payload=verify_output.payload,
        confidence=verify_output.confidence,
        reasoning=verify_output.reasoning,
    ))

    # ── Step 4: Detection Agent ────────────────────────────────────────────
    zone_reports    = await db.execute(select(Report.id).where(Report.zone_id == zone.id))
    all_report_ids  = [row[0] for row in zone_reports.all()]

    detect_input  = AgentInput(
        incident_id=incident.id,
        zone_id=zone.id,
        report_ids=all_report_ids,
    )
    detect_output = await detection.run(detect_input, db)

    db.add(AgentOutputModel(
        id=str(uuid.uuid4()),
        agent_name=detect_output.agent_name,
        incident_id=incident.id,
        output_type=detect_output.output_type,
        payload=detect_output.payload,
        confidence=detect_output.confidence,
        reasoning=detect_output.reasoning,
    ))

    # Sync incident fields from detection output
    incident.disaster_type  = detect_output.payload.get("disaster_type") or incident.disaster_type
    incident.severity_score = detect_output.payload.get("severity_score", incident.severity_score)
    incident.report_count   = len(all_report_ids)

    # ── Step 5: Decision Engine ────────────────────────────────────────────
    old_priority = incident.priority_score
    decision     = await score_zone(zone.id, incident, db)

    incident.priority_score = decision["priority_score"]
    incident.confidence     = decision["confidence"]
    incident.xai_reasoning  = decision["xai_reasoning"]
    incident.priority_band  = decision.get("priority_band", "LOW")
    incident.polled_at      = datetime.now(timezone.utc)

    avg_result = await db.execute(
        select(func.avg(Report.trust_score)).where(
            and_(Report.zone_id == zone.id, Report.trust_score.isnot(None))
        )
    )
    incident.avg_trust_score = float(avg_result.scalar() or 0.0)

    # Update zone-level priority/victim summary
    zone.priority_score = incident.priority_score
    zone.victim_count   = incident.victim_count

    await db.flush()

    # ── Step 6: WebSocket events ───────────────────────────────────────────
    await emit_new_report({
        "id":           report.id,
        "source":       report.source,
        "trust_score":  report.trust_score,
        "suppressed":   report.suppressed,
        "disaster_type": report.disaster_type,
        "lat":          report.lat,
        "lng":          report.lng,
        "zone_id":      zone.id,
        "message_text": report.message_text,
        "transcript":   report.transcript,
    })

    if old_trust_score is not None and old_trust_score != report.trust_score:
        await emit_trust_score_updated(
            report.id, old_trust_score, report.trust_score, verify_output.reasoning
        )

    await emit_incident_priority_updated(
        zone.id,
        incident.id,
        old_priority,
        incident.priority_score,
        incident.xai_reasoning,
        incident.disaster_type,
    )


# ── Internal helpers ───────────────────────────────────────────────────────

async def _enrich_with_groq(report: Report) -> None:
    """
    Use Groq to extract structured fields from the raw report text.
    Runs best-effort — any failure is silently logged, pipeline continues.
    """
    raw_text = report.message_text or report.transcript or ""
    if not raw_text.strip():
        return

    try:
        from app.services.report_parser import parse_citizen_report, parsed_report_to_nlp_hints
        parsed = await parse_citizen_report(raw_text)
        hints  = parsed_report_to_nlp_hints(parsed)

        # Only fill fields not already set by the NLP service
        if hints.get("disaster_type") and not report.disaster_type:
            report.disaster_type = hints["disaster_type"]

        # Store Groq parse fields for audit (migration 0003 columns)
        if hasattr(report, "groq_parsed_hazard") and parsed.hazard_type != "unknown":
            report.groq_parsed_hazard    = parsed.hazard_type
            report.groq_parsed_urgency   = parsed.urgency
            report.groq_people_estimated = parsed.people_estimated
            report.groq_condition        = parsed.condition

        logger.debug(
            "groq_enrichment_done",
            report_id=report.id,
            hazard=parsed.hazard_type,
            urgency=parsed.urgency,
        )
    except Exception as exc:
        # Never let Groq failure break the ingestion pipeline
        logger.warning("groq_enrichment_failed", report_id=report.id, error=str(exc))


async def _upsert_zone(report: Report, db: AsyncSession) -> Zone:
    """Find existing zone within ~500m of report coords, or create one."""
    RADIUS_DEG = 0.005  # ≈ 500m at equatorial scale

    result = await db.execute(
        select(Zone).where(
            and_(
                Zone.centroid_lat.between(report.lat - RADIUS_DEG, report.lat + RADIUS_DEG),
                Zone.centroid_lng.between(report.lng - RADIUS_DEG, report.lng + RADIUS_DEG),
                Zone.deleted == False,
            )
        ).limit(1)
    )
    zone = result.scalar_one_or_none()

    if not zone:
        zone = Zone(
            id=str(uuid.uuid4()),
            centroid_lat=report.lat,
            centroid_lng=report.lng,
            radius_meters=500.0,
            name=report.location_string or f"Zone @ {report.lat:.3f},{report.lng:.3f}",
            deleted=False,
        )
        db.add(zone)
        await db.flush()
        logger.info("zone_created", zone_id=zone.id, lat=report.lat, lng=report.lng)

    return zone


async def _get_or_create_incident(zone: Zone, db: AsyncSession) -> Incident:
    """Find active incident for zone, or create one."""
    result = await db.execute(
        select(Incident).where(
            and_(Incident.zone_id == zone.id, Incident.active == True)
        ).limit(1)
    )
    incident = result.scalar_one_or_none()

    if not incident:
        incident = Incident(
            id=str(uuid.uuid4()),
            zone_id=zone.id,
            active=True,
            status="active",
            created_at=datetime.now(timezone.utc),
        )
        db.add(incident)
        await db.flush()
        await emit_new_incident({
            "id":            incident.id,
            "zone_id":       zone.id,
            "lat":           zone.centroid_lat,
            "lng":           zone.centroid_lng,
            "disaster_type": None,
            "priority_score": 0.0,
        })
        logger.info("incident_created", incident_id=incident.id, zone_id=zone.id)

    return incident
