"""
USGS Earthquake API poller — runs every 2 minutes.
Fetches events from the last 30 minutes with magnitude >= 3.0.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.models.seismic import SeismicEvent
from sqlalchemy import select

logger = structlog.get_logger()
settings = get_settings()


def _magnitude_to_risk(magnitude: float) -> float:
    """Convert Richter magnitude to 0.0–1.0 risk score."""
    if magnitude >= 7.0:
        return 1.0
    elif magnitude >= 6.0:
        return 0.8
    elif magnitude >= 5.0:
        return 0.6
    elif magnitude >= 4.5:
        return 0.4
    elif magnitude >= 4.0:
        return 0.25
    elif magnitude >= 3.0:
        return 0.1
    return 0.0


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
async def _fetch_seismic() -> dict | None:
    start_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{settings.usgs_api_base}/query",
            params={
                "format": "geojson",
                "starttime": start_time,
                "minmagnitude": "3.0",
                "orderby": "time",
                "limit": "50",
            },
        )
        resp.raise_for_status()
        return resp.json()


async def poll_seismic() -> None:
    """Poll USGS for recent seismic events and store new ones."""
    try:
        data = await _fetch_seismic()
    except Exception as e:
        logger.warning("Seismic poll request failed", error=str(e))
        return

    features = data.get("features", [])
    if not features:
        return

    async with AsyncSessionLocal() as db:
        stored = 0
        for feature in features:
            props = feature.get("properties", {})
            coords = feature.get("geometry", {}).get("coordinates", [])
            usgs_id = feature.get("id")

            if not usgs_id or len(coords) < 2:
                continue

            # Check if already stored
            existing = await db.execute(
                select(SeismicEvent).where(SeismicEvent.usgs_id == usgs_id)
            )
            if existing.scalar_one_or_none():
                continue

            magnitude = props.get("mag", 0.0)
            event_time_ms = props.get("time")
            event_time = (
                datetime.fromtimestamp(event_time_ms / 1000, tz=timezone.utc)
                if event_time_ms
                else datetime.now(timezone.utc)
            )

            event = SeismicEvent(
                id=str(uuid.uuid4()),
                usgs_id=usgs_id,
                magnitude=magnitude,
                depth_km=coords[2] if len(coords) > 2 else None,
                lat=coords[1],
                lng=coords[0],
                place_description=props.get("place"),
                event_time=event_time,
                risk_score=_magnitude_to_risk(magnitude),
                polled_at=datetime.now(timezone.utc),
            )
            db.add(event)
            stored += 1

        if stored:
            await db.commit()
            logger.info("Seismic events stored", count=stored)

