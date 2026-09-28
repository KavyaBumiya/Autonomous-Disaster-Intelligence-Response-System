"""Zone listing, creation and detail/summary endpoints."""
import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.report import Report
from app.models.zone import Zone

router = APIRouter()


def _centroid_polygon(lat: float, lng: float, radius_meters: float) -> str:
    """Build a closed circular WKT polygon around a centroid.

    Used to give PostGIS a real zone polygon so provider readings can be
    spatially joined. Approximates a circle with 65 vertices, which is well
    inside the precision that matters at operational zone sizes.
    """
    lat_radius = (radius_meters / 111_320.0) / 180.0
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    lng_radius = (radius_meters / (111_320.0 * cos_lat)) / 180.0

    points = []
    for step in range(65):
        angle = math.radians(step * (360.0 / 64.0))
        points.append(f"{lng + lng_radius * math.cos(angle):.8f} {lat + lat_radius * math.sin(angle):.8f}")
    return f"POLYGON(({', '.join(points)}))"


class ZoneCreateBody(BaseModel):
    """Operational zone definition.

    Zones are operator-declared geography, not data pulled from a provider:
    an analyst names the areas they are responsible for and the console
    aggregates live provider readings against them.
    """

    name: str = Field(..., min_length=1, max_length=255)
    centroid_lat: float = Field(..., ge=-90.0, le=90.0)
    centroid_lng: float = Field(..., ge=-180.0, le=180.0)
    radius_meters: float = Field(default=500.0, gt=0.0, le=200_000.0)
    # Optional 0–1 population density, used by the Decision Engine. Omit it if
    # unknown; the engine then stays neutral instead of assuming a value.
    density_ratio: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


@router.post("", status_code=201, tags=["zones"])
async def create_zone(
    body: ZoneCreateBody,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Declare a new operational zone.

    Idempotent on name: re-posting an existing zone name updates its geometry
    instead of creating a duplicate.
    """
    existing = await db.execute(
        select(Zone).where(and_(Zone.name == body.name, Zone.deleted.is_(False)))
    )
    zone = existing.scalar_one_or_none()
    was_created = zone is None

    if zone is None:
        zone = Zone(id=str(uuid.uuid4()), name=body.name)
        db.add(zone)

    zone.centroid_lat = body.centroid_lat
    zone.centroid_lng = body.centroid_lng
    zone.radius_meters = body.radius_meters
    zone.density_ratio = body.density_ratio
    zone.geometry = f"SRID=4326;{_centroid_polygon(body.centroid_lat, body.centroid_lng, body.radius_meters)}"

    await db.commit()
    await db.refresh(zone)

    return {
        "zone_id": zone.id,
        "name": zone.name,
        "centroid_lat": zone.centroid_lat,
        "centroid_lng": zone.centroid_lng,
        "radius_meters": zone.radius_meters,
        "density_ratio": zone.density_ratio,
        "priority_score": zone.priority_score or 0,
        "victim_count": zone.victim_count or 0,
        "created": was_created,
        "created_at": zone.created_at.isoformat() if zone.created_at else None,
    }


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
                "density_ratio": z.density_ratio,
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
        "density_ratio": zone.density_ratio,
        "priority_score": zone.priority_score or 0,
        "victim_count": zone.victim_count or 0,
        "created_at": zone.created_at.isoformat() if zone.created_at else None,
        "updated_at": zone.updated_at.isoformat() if zone.updated_at else None,
    }
