"""NASA endpoints — EONET natural-event catalog (additive).

Serves the `external_observations` domain rows ingested by the EONET
poller (§28) — no live provider call in the request path. Empty list
means nothing ingested yet: values are never fabricated (§7).
"""
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.external import ExternalObservation

router = APIRouter()

SOURCE = "nasa_eonet"


def _event_payload(row: ExternalObservation) -> dict:
    value = row.value or {}
    payload = row.payload or {}
    return {
        "id": value.get("eonet_id"),
        "title": value.get("title") or payload.get("title"),
        "description": payload.get("description"),
        "category": value.get("category") or payload.get("category"),
        "category_title": payload.get("category_title"),
        "status": "closed" if payload.get("closed") else "open",
        "closed": payload.get("closed"),
        "lat": row.lat,
        "lng": row.lng,
        "geometry_type": payload.get("geometry_type"),
        "magnitude_value": value.get("magnitude_value"),
        "magnitude_unit": value.get("magnitude_unit"),
        "link": payload.get("link"),
        "sources": payload.get("sources") or [],
        "latest_geometry_date": payload.get("latest_geometry_date"),
        "retrieved_at": row.retrieved_at.isoformat() if row.retrieved_at else None,
    }


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@router.get("/eonet/events", tags=["nasa"])
async def eonet_events(
    status: str = Query("open", pattern="^(open|all|closed)$"),
    category: str | None = Query(
        None, description="Comma-separated EONET category ids (e.g. wildfires,severeStorms)"
    ),
    limit: int = Query(100, ge=1, le=500),
    lat: float | None = Query(None, ge=-90, le=90, description="Area centre (with lng)"),
    lng: float | None = Query(None, ge=-180, le=180, description="Area centre (with lat)"),
    radius_km: float = Query(250.0, gt=0, le=20000),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """NASA EONET natural events (wildfires, storms, volcanoes, floods…)
    as ingested by the poller. Filter by status/category or a radius around
    a point; polygon-only events carry `geometry_type` with lat/lng = null
    (their area is not reduced to an invented centroid)."""
    q = select(ExternalObservation).where(ExternalObservation.source == SOURCE)

    if status == "open":
        q = q.where(ExternalObservation.payload["closed"].astext.is_(None))
    elif status == "closed":
        q = q.where(ExternalObservation.payload["closed"].astext.isnot(None))

    if category:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        if cats:
            q = q.where(ExternalObservation.value["category"].astext.in_(cats))

    if lat is not None and lng is not None:
        # coarse bbox prefilter, exact radius applied below
        d_lat = radius_km / 111.32
        cos_lat = max(0.01, math.cos(math.radians(lat)))
        d_lng = radius_km / (111.32 * cos_lat)
        q = q.where(
            ExternalObservation.lat.between(lat - d_lat, lat + d_lat),
            ExternalObservation.lng.between(lng - d_lng, lng + d_lng),
        )

    rows = (
        await db.execute(
            q.order_by(ExternalObservation.retrieved_at.desc()).limit(limit)
        )
    ).scalars().all()

    events = [_event_payload(r) for r in rows]
    if lat is not None and lng is not None:
        events = [
            e
            for e in events
            if e["lat"] is not None
            and e["lng"] is not None
            and _haversine_km(lat, lng, e["lat"], e["lng"]) <= radius_km
        ]

    return {
        "source": SOURCE,
        "provider": "NASA EONET v3",
        "count": len(events),
        "status_filter": status,
        "events": events,
        "note": (
            "Ingested EONET catalog (poller keeps it fresh). Empty list = "
            "nothing ingested yet — never fabricated."
        ),
    }
