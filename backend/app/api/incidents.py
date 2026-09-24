"""Incident listing and detail endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.incident import Incident
from app.models.zone import Zone

router = APIRouter()


def _incident_payload(inc: Incident, zone: Zone | None) -> dict:
    return {
        "incident_id": inc.id,
        "zone_id": inc.zone_id,
        "zone_name": zone.name if zone else None,
        "lat": zone.centroid_lat if zone else None,
        "lng": zone.centroid_lng if zone else None,
        "disaster_type": inc.disaster_type,
        "priority_score": inc.priority_score,
        "priority_band": getattr(inc, "priority_band", None),
        "severity_score": inc.severity_score,
        "confidence": inc.confidence,
        "status": inc.status,
        "report_count": inc.report_count,
        "avg_trust_score": inc.avg_trust_score,
        "victim_count": getattr(inc, "victim_count", 0) or 0,
        "victim_confidence": getattr(inc, "victim_confidence", 0.0) or 0.0,
        "xai_reasoning": inc.xai_reasoning,
        "groq_summary": getattr(inc, "groq_summary", None),
        "groq_explanation": getattr(inc, "groq_explanation", None),
        "active": inc.active,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
    }


@router.get("")
async def list_incidents(
    active_only: bool = Query(True),
    zone_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    q = select(Incident)
    if active_only:
        q = q.where(Incident.active == True)
    if zone_id:
        q = q.where(Incident.zone_id == zone_id)
    q = q.order_by(Incident.priority_score.desc()).offset(offset).limit(limit)
    result = await db.execute(q)
    incidents = result.scalars().all()

    count_q = select(func.count(Incident.id))
    if active_only:
        count_q = count_q.where(Incident.active == True)
    if zone_id:
        count_q = count_q.where(Incident.zone_id == zone_id)
    total = (await db.execute(count_q)).scalar()

    items = []
    for inc in incidents:
        zone_result = await db.execute(select(Zone).where(Zone.id == inc.zone_id))
        zone = zone_result.scalar_one_or_none()
        items.append(_incident_payload(inc, zone))

    return {"incidents": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{incident_id}")
async def get_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    inc = result.scalar_one_or_none()
    if not inc:
        raise HTTPException(404, detail="Incident not found")

    zone_result = await db.execute(select(Zone).where(Zone.id == inc.zone_id))
    zone = zone_result.scalar_one_or_none()
    return _incident_payload(inc, zone)
