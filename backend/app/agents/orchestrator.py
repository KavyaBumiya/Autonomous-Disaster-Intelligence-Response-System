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
from app.services.geocoding import geocode
from app.services import gis_service
from app.services.clustering import find_cluster_incident
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

    # ── Step 1b: Geocode fallback (Nominatim) when only text location ────
    if (not report.lat or not report.lng) and (report.location_string or "").strip():
        try:
            hit = await geocode(report.location_string.strip())
            if hit and hit.get("lat") is not None and hit.get("lng") is not None:
                report.lat = float(hit["lat"])
                report.lng = float(hit["lng"])
                report.geocoding_confidence = hit.get("confidence")
                await db.flush()
                logger.info(
                    "report_geocoded",
                    report_id=report.id,
                    location=report.location_string,
                    provider="nominatim",
                )
        except Exception as geo_exc:  # enrichment — pipeline continues either way
            logger.warning("geocode_failed", report_id=report.id, error=str(geo_exc))

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
    await gis_service.set_report_geometry(db, report.id, report.lat, report.lng)
    await db.flush()

    # ── Step 2b: External enrichment — weather (Redis) + GIS cache ────────
    await _enrich_weather(zone, db)
    await _enrich_infrastructure(zone, db)

    # ── Step 3: Verification Agent ─────────────────────────────────────────
    incident = await _get_or_create_incident(zone, db, report)

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
    # When corroboration merged into an incident from a neighbouring zone,
    # detection sees reports of BOTH zones (merged incident view).
    zone_ids = {zone.id}
    if incident.zone_id and incident.zone_id != zone.id:
        zone_ids.add(incident.zone_id)
    zone_reports    = await db.execute(select(Report.id).where(Report.zone_id.in_(zone_ids)))
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

    # ── Step 5b: Persist Groq narrative from engine evidence (PRD §8) ────
    try:
        from app.services.incident_narrative import ensure_incident_narrative
        # Refresh narrative when priority moved enough to matter for briefing
        if (
            old_priority is None
            or abs((incident.priority_score or 0.0) - (old_priority or 0.0)) >= 5.0
            or not (incident.groq_explanation or "").strip()
        ):
            await ensure_incident_narrative(incident, db, force=True)
    except Exception as narr_exc:
        logger.warning(
            "narrative_generation_failed",
            incident_id=incident.id,
            error=str(narr_exc),
        )

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
    Use Groq to normalise (translate) and extract structured fields from the
    raw report text. Runs best-effort — any failure is silently logged and the
    deterministic pipeline continues (PRD §2: LLM never blocks decisions).
    """
    raw_text = report.message_text or report.transcript or ""
    if not raw_text.strip():
        return

    try:
        from app.services.groq_gateway import groq_gateway
        from app.services.report_parser import parse_citizen_report, parsed_report_to_nlp_hints

        # ── Multilingual normalisation (PRD §4-G) ─────────────────────────
        # Original text is always preserved on the report; we parse the
        # English translation when the source is not English.
        parse_text = raw_text
        try:
            translation = await groq_gateway.translate(raw_text)
            if translation.was_translated:
                parse_text = translation.translated_text
                # Original citizen wording stays on message_text/transcript;
                # only the language code records the source language.
                report.language_code = translation.source_language
                logger.info(
                    "report_translated",
                    report_id=report.id,
                    source_lang=translation.source_language,
                    model=translation.model_used,
                )
        except Exception as t_exc:
            logger.debug("translate_skipped", report_id=report.id, error=str(t_exc))

        parsed = await parse_citizen_report(parse_text)
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
    """Find existing zone within ~500m of report coords, or create one.
    Phase 9: PostGIS ST_DWithin replaces the RADIUS_DEG bounding box (§9)."""
    zone_id = await gis_service.zone_at_point(db, report.lat, report.lng, radius_m=500.0)

    zone = None
    if zone_id:
        zone = (await db.execute(select(Zone).where(Zone.id == zone_id))).scalar_one_or_none()

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
        await gis_service.set_zone_geometry(
            db, zone.id, zone.centroid_lat, zone.centroid_lng, zone.radius_meters
        )
        logger.info("zone_created", zone_id=zone.id, lat=report.lat, lng=report.lng)

    return zone


async def _enrich_weather(zone: Zone, db: AsyncSession) -> None:
    """Ensure a fresh weather reading exists for the zone (Redis-cached).
    Best-effort: provider failures leave the DB as-is (§31, never fabricate)."""
    from datetime import timedelta

    from app.integrations.base import ConnectorError
    from app.models.weather import WeatherReading
    from app.pollers.weather import _compute_risk_score
    from app.services.weather_service import weather_service

    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    existing = (
        await db.execute(
            select(WeatherReading.id).where(
                and_(
                    WeatherReading.zone_id == zone.id,
                    WeatherReading.polled_at >= since,
                )
            ).limit(1)
        )
    ).scalar_one_or_none()
    if existing:
        return  # fresh reading already stored (poller or earlier report)

    try:
        obs = await weather_service.get_current_weather(
            zone.centroid_lat, zone.centroid_lng, allow_stale=False
        )
    except ConnectorError as exc:
        logger.warning(
            "pipeline_weather_unavailable",
            zone=zone.id,
            provider=exc.provider,
            error=exc.message,
        )
        return

    db.add(
        WeatherReading(
            id=str(uuid.uuid4()),
            zone_id=zone.id,
            lat=zone.centroid_lat,
            lng=zone.centroid_lng,
            rainfall_mm_hr=obs.rainfall_mm_hr,
            wind_speed_kmh=obs.wind_speed_kmh or 0.0,
            temperature_c=obs.temperature_c,
            weather_main=obs.weather_main,
            weather_description=obs.weather_description,
            risk_score=_compute_risk_score(
                obs.rainfall_mm_hr, obs.wind_speed_kmh or 0.0, obs.weather_main
            ),
            polled_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()
    logger.info("pipeline_weather_enriched", zone=zone.id, risk=obs.rainfall_mm_hr)


async def _enrich_infrastructure(zone: Zone, db: AsyncSession) -> None:
    """Refresh GIS cache for the zone when nothing is cached nearby.
    Gated twice: (a) skip when features already exist near the zone,
    (b) Redis throttle — at most one Overpass attempt per zone per hour."""
    from datetime import timedelta

    from app.integrations import cache as redis_cache
    from app.models.infrastructure import Infrastructure

    south, west, north, east = gis_service.bbox_for_radius(
        zone.centroid_lat, zone.centroid_lng,
        max(1000.0, float(zone.radius_meters or 500) * 4),
    )
    cached = (
        await db.execute(
            select(func.count(Infrastructure.id)).where(
                and_(
                    Infrastructure.lat.between(south, north),
                    Infrastructure.lng.between(west, east),
                )
            )
        )
    ).scalar()
    if cached:
        return

    throttle_key = f"gis_refresh_attempted:{zone.id}"
    if await redis_cache.cache_get(throttle_key):
        return  # recent attempt already made (provider down / genuinely empty)

    ingested = await gis_service.refresh_zone_infrastructure(db, zone.id)
    await redis_cache.cache_set(throttle_key, 1, ttl=3600)
    if ingested:
        logger.info("pipeline_gis_enriched", zone=zone.id, features=ingested)


async def _get_or_create_incident(
    zone: Zone, db: AsyncSession, report: Report | None = None
) -> Incident:
    """Find active incident for zone (or a nearby corroboration cluster),
    or create one. Clustering merge is additive — same-zone behaviour is
    unchanged when no cross-zone candidate matches (§9)."""
    result = await db.execute(
        select(Incident).where(
            and_(Incident.zone_id == zone.id, Incident.active == True)
        ).limit(1)
    )
    incident = result.scalar_one_or_none()

    if not incident and report is not None:
        incident = await find_cluster_incident(zone, report, db)
        if incident:
            logger.info(
                "incident_corroboration_merged",
                incident_id=incident.id,
                report_zone_id=zone.id,
                incident_zone_id=incident.zone_id,
                report_id=report.id,
            )
            return incident

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
