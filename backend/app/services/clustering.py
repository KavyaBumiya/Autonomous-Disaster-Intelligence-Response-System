"""
Cross-zone incident clustering (PRD §9) — deterministic corroboration merge.

When a report arrives from a zone without an active incident, look for an
active incident in a NEARBY zone (PostGIS distance + recency + hazard-type
compatibility + text similarity) and merge the corroboration into it instead
of creating a duplicate incident.

Deterministic only — no LLM. Tunables are module constants (§6).
"""
from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.report import Report
from app.models.zone import Zone
from app.services.deduplication import similarity_score

logger = structlog.get_logger()

CLUSTER_RADIUS_M = 500.0        # candidate incidents within this of the report zone
MERGE_DISTANCE_M = 250.0        # same-hazard merge distance (strong signal)
CLUSTER_WINDOW_HOURS = 24.0     # only recent incidents are merge targets
SIMILARITY_THRESHOLD = 0.30     # text corroboration threshold
_MIN_TEXT_LEN = 20
_RECENT_REPORTS_PER_CANDIDATE = 5


def _hazard_compatible(incident_type: str | None, report_type: str | None) -> tuple[bool, str | None]:
    """(compatible, known_hazard) — different known hazards never merge."""
    inc = (incident_type or "").lower().strip()
    rpt = (report_type or "").lower().strip()
    if inc and rpt and inc != rpt:
        return False, None                 # known-but-different → incompatible
    return True, (rpt or inc or None)


async def find_cluster_incident(
    zone: Zone, report: Report, db: AsyncSession
) -> Incident | None:
    """Nearest mergeable active incident for a report, or None (create new)."""
    if not report.lat or not report.lng:
        return None

    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(hours=CLUSTER_WINDOW_HOURS)
    candidates = (
        await db.execute(
            text(
                """
                SELECT i.id, i.zone_id, i.disaster_type, i.created_at,
                       z.centroid_lat, z.centroid_lng,
                       ST_Distance(
                           ST_MakePoint(z.centroid_lng, z.centroid_lat)::geography,
                           ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                       ) AS distance_m
                FROM incidents i
                JOIN zones z ON z.id = i.zone_id
                WHERE i.active = true
                  AND i.zone_id <> :zone_id
                  AND i.created_at >= :cutoff
                  AND ST_DWithin(
                        ST_MakePoint(z.centroid_lng, z.centroid_lat)::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        :radius_m)
                ORDER BY distance_m ASC
                LIMIT 10
                """
            ),
            {
                "zone_id": zone.id,
                "lat": float(report.lat),
                "lng": float(report.lng),
                "radius_m": CLUSTER_RADIUS_M,
                "cutoff": cutoff,
            },
        )
    ).mappings().all()
    if not candidates:
        return None

    text_a = (report.message_text or report.transcript or "").strip()

    for cand in candidates:
        distance_m = float(cand["distance_m"])
        compatible, known_hazard = _hazard_compatible(
            cand["disaster_type"], report.disaster_type
        )
        if not compatible:
            continue

        # Strong signal: same known hazard AND very close → merge
        if known_hazard and distance_m <= MERGE_DISTANCE_M:
            return await _load_incident(str(cand["id"]), db)

        # Corroboration signal: text similarity against candidate's reports
        if text_a and len(text_a) >= _MIN_TEXT_LEN:
            sim = await _max_similarity(text_a, str(cand["zone_id"]), report.id, db)
            if sim >= SIMILARITY_THRESHOLD:
                logger.info(
                    "incident_cluster_merge",
                    target_incident_id=str(cand["id"]),
                    target_zone_id=str(cand["zone_id"]),
                    distance_m=round(distance_m, 1),
                    similarity=round(sim, 3),
                    report_id=report.id,
                )
                return await _load_incident(str(cand["id"]), db)

    return None


async def _max_similarity(text_a: str, zone_id: str, exclude_report_id: str,
                          db: AsyncSession) -> float:
    from sqlalchemy import select
    from datetime import datetime, timedelta, timezone

    since = datetime.now(timezone.utc) - timedelta(hours=CLUSTER_WINDOW_HOURS)
    rows = (
        await db.execute(
            select(Report.message_text, Report.transcript).where(
                Report.zone_id == zone_id,
                Report.created_at >= since,
                Report.id != exclude_report_id,
            ).limit(20)
        )
    ).all()
    max_sim = 0.0
    for message_text, transcript in rows:
        text_b = (message_text or transcript or "").strip()
        if not text_b:
            continue
        max_sim = max(max_sim, similarity_score(text_a, text_b))
    return max_sim


async def _load_incident(incident_id: str, db: AsyncSession) -> Incident | None:
    from sqlalchemy import select

    return (
        await db.execute(select(Incident).where(Incident.id == incident_id))
    ).scalar_one_or_none()
