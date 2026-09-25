"""
USGS Earthquake API poller — runs every 2 minutes.
Fetches events from the last 30 minutes with magnitude >= 3.0.

HTTP/retry handled by UsgsConnector (Phase 6); normalization per §14 via
EarthquakeObservation.from_feature (Phase 7).
"""
import uuid
from datetime import datetime, timezone

import structlog

from app.core.database import AsyncSessionLocal
from app.integrations.base import ConnectorError
from app.integrations.seismic.usgs import UsgsConnector
from app.models.seismic import SeismicEvent
from app.schemas.observations import EarthquakeObservation
from sqlalchemy import select

logger = structlog.get_logger()


async def poll_seismic(
    minutes: int = 30, min_magnitude: float = 3.0, limit: int = 50
) -> None:
    """Poll USGS for recent seismic events and store new ones."""
    try:
        data = await UsgsConnector().recent_events(
            minutes=minutes, min_magnitude=min_magnitude, limit=limit
        )
    except ConnectorError as e:
        logger.warning(
            "Seismic poll request failed",
            provider=e.provider,
            error=e.message,
            status_code=e.status_code,
        )
        return

    features = data.get("features", []) if isinstance(data, dict) else []
    if not features:
        return

    async with AsyncSessionLocal() as db:
        stored = 0
        new_events: list[dict] = []
        retrieved_at = datetime.now(timezone.utc)
        for feature in features:
            obs = EarthquakeObservation.from_feature(feature, retrieved_at=retrieved_at)
            if obs is None:
                continue

            # Check if already stored
            existing = await db.execute(
                select(SeismicEvent).where(SeismicEvent.usgs_id == obs.usgs_id)
            )
            if existing.scalar_one_or_none():
                continue

            event = SeismicEvent(
                id=str(uuid.uuid4()),
                usgs_id=obs.usgs_id,
                magnitude=obs.magnitude,
                depth_km=obs.depth_km,
                lat=obs.lat,
                lng=obs.lng,
                place_description=obs.place,
                event_time=obs.event_time,
                risk_score=obs.risk_score,
                polled_at=retrieved_at,
            )
            db.add(event)
            stored += 1
            new_events.append(
                {
                    "usgs_id": obs.usgs_id,
                    "magnitude": obs.magnitude,
                    "place": obs.place,
                    "lat": obs.lat,
                    "lng": obs.lng,
                    "depth_km": obs.depth_km,
                    "event_time": obs.event_time.isoformat(),
                    "risk_score": obs.risk_score,
                }
            )

        if stored:
            await db.commit()
            logger.info("Seismic events stored", count=stored)

            # WebSocket earthquake.detected (§25) — NEW events only, after commit
            try:
                from app.services.websocket import emit_earthquake_detected

                await emit_earthquake_detected(new_events)
            except Exception as exc:  # noqa: BLE001
                logger.warning("earthquake_detected_emit_failed", error=str(exc))
