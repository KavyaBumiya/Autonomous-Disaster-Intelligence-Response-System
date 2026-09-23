"""
Agent Orchestrator — runs the agent pipeline for a zone/incident.
Phase 1 pipeline:
  1. Detection Agent v0 (classification)
  2. Verification Agent v1 (trust scoring per report)
  3. Decision Engine (priority scoring + XAI)
  4. Emit WebSocket events
"""
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

# Minimum report count before creating an Incident record
INCIDENT_CREATION_THRESHOLD = 2


async def process_report(report: Report, db: AsyncSession) -> None:
    """
    Called after a new report is stored.
    1. Ensure a zone exists or upsert.
    2. Run Verification Agent on this report.
    3. Update incident + run Decision Engine.
    4. Emit WebSocket events.
    """
    if not report.lat or not report.lng:
        logger.debug("Skipping orchestration — report has no location", report_id=report.id)
        # Still emit the raw report event
        await emit_new_report({
            "id": report.id,
            "source": report.source,
            "trust_score": None,
            "suppressed": False,
            "disaster_type": report.disaster_type,
            "lat": None,
            "lng": None,
            "zone_id": None,
            "message_text": report.message_text,
            "transcript": report.transcript,
        })
        return

    # ── Step 1: Upsert zone ───────────────────────────────────
    zone = await _upsert_zone(report, db)
    report.zone_id = zone.id
    await db.flush()

    # ── Step 2: Run Verification Agent ───────────────────────
    incident = await _get_or_create_incident(zone, db)

    verify_input = AgentInput(
        incident_id=incident.id,
        zone_id=zone.id,
        report_ids=[report.id],
    )
    verify_output = await verification.run(verify_input, db)

    # Update report trust score
    old_score = report.trust_score
    report.trust_score = verify_output.payload.get("trust_score")
    report.suppressed = verify_output.payload.get("suppressed", False)

    # Save agent output
    db.add(AgentOutputModel(
        id=str(uuid.uuid4()),
        agent_name=verify_output.agent_name,
        incident_id=incident.id,
        output_type=verify_output.output_type,
        payload=verify_output.payload,
        confidence=verify_output.confidence,
        reasoning=verify_output.reasoning,
    ))

    # ── Step 3: Run Detection Agent ──────────────────────────
    # Gather all report IDs for this zone
    zone_reports = await db.execute(
        select(Report.id).where(Report.zone_id == zone.id)
    )
    all_report_ids = [row[0] for row in zone_reports.all()]

    detect_input = AgentInput(
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

    # Update incident disaster type
    incident.disaster_type = detect_output.payload.get("disaster_type")
    incident.report_count = len(all_report_ids)

    # ── Step 4: Decision Engine ──────────────────────────────
    old_priority = incident.priority_score
    decision = await score_zone(zone.id, incident, db)

    incident.priority_score = decision["priority_score"]
    incident.confidence = decision["confidence"]
    incident.xai_reasoning = decision["xai_reasoning"]
    incident.severity_score = detect_output.payload.get("severity_score", 0.0)

    # Compute avg trust score for zone
    avg_result = await db.execute(
        select(func.avg(Report.trust_score)).where(
            and_(Report.zone_id == zone.id, Report.trust_score.isnot(None))
        )
    )
    incident.avg_trust_score = float(avg_result.scalar() or 0.0)

    await db.flush()

    # ── Step 5: WebSocket events ─────────────────────────────
    await emit_new_report({
        "id": report.id,
        "source": report.source,
        "trust_score": report.trust_score,
        "suppressed": report.suppressed,
        "disaster_type": report.disaster_type,
        "lat": report.lat,
        "lng": report.lng,
        "zone_id": zone.id,
        "message_text": report.message_text,
        "transcript": report.transcript,
    })

    if old_score is not None and old_score != report.trust_score:
        await emit_trust_score_updated(
            report.id, old_score, report.trust_score, verify_output.reasoning
        )

    await emit_incident_priority_updated(
        zone.id,
        incident.id,
        old_priority,
        incident.priority_score,
        incident.xai_reasoning,
        incident.disaster_type,
    )


async def _upsert_zone(report: Report, db: AsyncSession) -> Zone:
    """Find existing zone within 500m of report coords, or create one."""
    ZONE_RADIUS_DEG = 0.005  # ~500m at equatorial scale

    result = await db.execute(
        select(Zone).where(
            and_(
                Zone.centroid_lat.between(report.lat - ZONE_RADIUS_DEG, report.lat + ZONE_RADIUS_DEG),
                Zone.centroid_lng.between(report.lng - ZONE_RADIUS_DEG, report.lng + ZONE_RADIUS_DEG),
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
        )
        db.add(zone)
        await db.flush()
        logger.info("New zone created", zone_id=zone.id, lat=report.lat, lng=report.lng)

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
            "id": incident.id,
            "zone_id": zone.id,
            "lat": zone.centroid_lat,
            "lng": zone.centroid_lng,
            "disaster_type": None,
            "priority_score": 0.0,
        })

    return incident
