"""Earthquakes — recent seismic events for panels/maps (plan Phase 6).

Serves the domain table `seismic_events` (kept fresh by the 2-minute USGS
poller, §28) — no extra provider calls from the request path.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.seismic import SeismicEvent

router = APIRouter()


@router.get("/recent", tags=["earthquakes"])
async def recent_earthquakes(
    minutes: int = Query(default=1440, ge=1, le=20160, description="Look-back window in minutes (max 14 days)"),
    min_magnitude: float = Query(default=0.0, ge=0.0, le=10.0),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Seismic events from the last `minutes`, newest first.

    Backed by `seismic_events` (USGS poller, 2-minute cadence). Empty list
    = no qualifying events (never fabricated, §7)."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    rows = (
        await db.execute(
            select(SeismicEvent)
            .where(
                SeismicEvent.event_time >= since,
                SeismicEvent.magnitude >= min_magnitude,
            )
            .order_by(SeismicEvent.event_time.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "count": len(rows),
        "window_minutes": minutes,
        "min_magnitude": min_magnitude,
        "source": "seismic_events",
        "earthquakes": [
            {
                "id": e.id,
                "usgs_id": e.usgs_id,
                "magnitude": e.magnitude,
                "depth_km": e.depth_km,
                "lat": e.lat,
                "lng": e.lng,
                "place": e.place_description,
                "event_time": e.event_time.isoformat() if e.event_time else None,
                "risk_score": e.risk_score,
                "polled_at": e.polled_at.isoformat() if e.polled_at else None,
            }
            for e in rows
        ],
    }
