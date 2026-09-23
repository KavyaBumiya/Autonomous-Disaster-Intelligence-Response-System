"""Zone listing and detail/summary endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.zone import Zone
from app.models.report import Report
from fastapi import HTTPException

router = APIRouter()


@router.get("")
async def list_zones(
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    result = await db.execute(select(Zone).order_by(Zone.created_at.desc()).offset(offset).limit(limit))
    zones = result.scalars().all()
    total = (await db.execute(select(func.count(Zone.id)))).scalar()

    return {
        "zones": [
            {
                "zone_id": z.id,
                "name": z.name,
                "centroid_lat": z.centroid_lat,
                "centroid_lng": z.centroid_lng,
                "radius_meters": z.radius_meters,
                "priority_score": z.priority_score or 0,
                "victim_count": z.victim_count or 0,
                "created_at": z.created_at.isoformat() if z.created_at else None,
            }
            for z in zones
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{zone_id}/reports/summary")
async def zone_report_summary(
    zone_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Aggregated report stats for a zone."""
    # Total count
    total = (await db.execute(
        select(func.count(Report.id)).where(Report.zone_id == zone_id)
    )).scalar()

    # Trust breakdown
    high = (await db.execute(
        select(func.count(Report.id)).where(
            and_(Report.zone_id == zone_id, Report.trust_score >= 0.75)
        )
    )).scalar()
    medium = (await db.execute(
        select(func.count(Report.id)).where(
            and_(Report.zone_id == zone_id, Report.trust_score >= 0.50, Report.trust_score < 0.75)
        )
    )).scalar()
    low = (await db.execute(
        select(func.count(Report.id)).where(
            and_(Report.zone_id == zone_id, Report.trust_score >= 0.25, Report.trust_score < 0.50)
        )
    )).scalar()
    suppressed = (await db.execute(
        select(func.count(Report.id)).where(
            and_(Report.zone_id == zone_id, Report.suppressed == True)
        )
    )).scalar()

    # Source breakdown
    citizen_text = (await db.execute(
        select(func.count(Report.id)).where(
            and_(Report.zone_id == zone_id, Report.source == "citizen_text")
        )
    )).scalar()
    citizen_voice = (await db.execute(
        select(func.count(Report.id)).where(
            and_(Report.zone_id == zone_id, Report.source == "citizen_voice")
        )
    )).scalar()
    social = (await db.execute(
        select(func.count(Report.id)).where(
            and_(Report.zone_id == zone_id, Report.source == "social_media")
        )
    )).scalar()

    # Dominant disaster type
    dtype_result = await db.execute(
        select(Report.disaster_type, func.count(Report.id).label("cnt"))
        .where(and_(Report.zone_id == zone_id, Report.disaster_type.isnot(None)))
        .group_by(Report.disaster_type)
        .order_by(func.count(Report.id).desc())
        .limit(1)
    )
    dtype_row = dtype_result.one_or_none()
    dominant = dtype_row[0] if dtype_row else None

    # Avg trust
    avg_trust = (await db.execute(
        select(func.avg(Report.trust_score)).where(
            and_(Report.zone_id == zone_id, Report.trust_score.isnot(None))
        )
    )).scalar() or 0.0

    return {
        "zone_id": zone_id,
        "total_reports": total,
        "high_trust_count": high,
        "medium_trust_count": medium,
        "low_trust_count": low,
        "suppressed_count": suppressed,
        "sources": {
            "citizen_text": citizen_text,
            "citizen_voice": citizen_voice,
            "social_media": social,
        },
        "dominant_disaster_type": dominant,
        "avg_trust_score": round(float(avg_trust), 3),
    }


@router.get("/{zone_id}")
async def get_zone(
    zone_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Return the geographic and priority data required by the live map."""
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")

    return {
        "zone_id": zone.id,
        "name": zone.name,
        "centroid_lat": zone.centroid_lat,
        "centroid_lng": zone.centroid_lng,
        "radius_meters": zone.radius_meters,
        "priority_score": zone.priority_score or 0,
        "victim_count": zone.victim_count or 0,
        "created_at": zone.created_at.isoformat() if zone.created_at else None,
        "updated_at": zone.updated_at.isoformat() if zone.updated_at else None,
    }
