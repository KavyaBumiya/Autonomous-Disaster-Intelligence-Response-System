"""
NASA EONET poller — ingests open natural events (§28 cadence).

Runs every settings.eonet_poll_interval_minutes (default 10 min — EONET is
a low-cadence catalog, far below the 1,000 req/h api.nasa.gov budget).

Storage: `external_observations` (source='nasa_eonet', type='natural_event')
— the PRD §5 table for NON-domain feeds; weather/seismic/GIS keep their own
tables (no duplication). Dedupe key: value->>'eonet_id'. Rows are refreshed
when a tracked event moves (storms) or gains/loses closure info.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.integrations.base import ConnectorError
from app.integrations.nasa.eonet import EonetConnector, normalize_event
from app.models.external import ExternalObservation

logger = structlog.get_logger()

SOURCE = "nasa_eonet"
OBSERVATION_TYPE = "natural_event"


async def poll_eonet(limit: int = 200) -> int:
    """Fetch open EONET events, upsert normalized rows. Returns rows
    inserted+updated (0 = nothing new or provider unavailable — never
    fabricated, §7)."""
    try:
        data = await EonetConnector().events(status="open", limit=limit)
    except ConnectorError as exc:
        logger.warning(
            "eonet_poll_request_failed",
            provider=exc.provider,
            error=exc.message,
            status_code=exc.status_code,
        )
        return 0

    raw_events = data.get("events") or []
    normalized = [n for e in raw_events if (n := normalize_event(e)) is not None]
    if not normalized:
        return 0

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        stored = 0
        for n in normalized:
            value = {
                "eonet_id": n["eonet_id"],
                "title": n["title"],
                "category": n["category"],
                "magnitude_value": n["magnitude_value"],
                "magnitude_unit": n["magnitude_unit"],
            }
            payload = {
                "provider": "nasa_eonet",
                "title": n["title"],
                "description": n["description"],
                "link": n["link"],
                "closed": n["closed"],
                "category": n["category"],
                "category_title": n["category_title"],
                "sources": n["sources"],
                "geometry_type": n["geometry_type"],
                "latest_geometry_date": n["latest_geometry_date"],
            }
            result = await db.execute(
                select(ExternalObservation)
                .where(
                    ExternalObservation.source == SOURCE,
                    ExternalObservation.value["eonet_id"].astext == n["eonet_id"],
                )
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                db.add(
                    ExternalObservation(
                        id=str(uuid.uuid4()),
                        source=SOURCE,
                        observation_type=OBSERVATION_TYPE,
                        lat=n["lat"],
                        lng=n["lng"],
                        value=value,
                        payload=payload,
                        confidence=1.0,
                        retrieved_at=now,
                    )
                )
                stored += 1
            else:
                moved = row.lat != n["lat"] or row.lng != n["lng"]
                old_value = row.value or {}
                old_payload = row.payload or {}
                changed = (
                    moved
                    or old_value.get("magnitude_value") != n["magnitude_value"]
                    or old_payload.get("closed") != n["closed"]
                )
                if changed:
                    row.lat = n["lat"]
                    row.lng = n["lng"]
                    row.value = value
                    row.payload = payload
                    row.retrieved_at = now
                    stored += 1

        if stored:
            await db.commit()
            logger.info(
                "eonet_events_stored",
                inserted_or_updated=stored,
                fetched=len(normalized),
            )
    return stored
