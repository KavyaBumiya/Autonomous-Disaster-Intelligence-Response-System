"""
GIS service — Overpass ingestion + PostGIS storage (PRD §8/§9).

Backend owns infrastructure retrieval (§6 principle). Callers pass a bbox
or a zone; this service fetches, upserts into `infrastructure`, and keeps
the PostGIS POINT geometry in sync with lat/lng via a single SQL fixup
(asyncpg-safe: ST_MakePoint at the SQL level, no geoalchemy bind issues).
"""
from __future__ import annotations

import math

import structlog
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import ConnectorError
from app.integrations.gis.overpass import OverpassConnector
from app.models.infrastructure import Infrastructure

logger = structlog.get_logger()

_INSERT_CHUNK = 500


def bbox_for_radius(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """(south, west, north, east) covering a radius around a point."""
    d_lat = radius_m / 111_320.0
    cos_lat = max(0.01, math.cos(math.radians(lat)))
    d_lng = radius_m / (111_320.0 * cos_lat)
    return (lat - d_lat, lng - d_lng, lat + d_lat, lng + d_lng)


async def refresh_infrastructure(
    db: AsyncSession,
    south: float,
    west: float,
    north: float,
    east: float,
    *,
    zone_id: str | None = None,
    connector: OverpassConnector | None = None,
) -> int:
    """Fetch a bbox from Overpass and upsert into `infrastructure`.

    Returns number of normalized features ingested.
    Raises ConnectorError when the provider fails (caller decides fallback).
    """
    conn = connector or OverpassConnector()
    observations = await conn.fetch_infrastructure(south, west, north, east)
    if not observations:
        return 0

    for start in range(0, len(observations), _INSERT_CHUNK):
        chunk = observations[start : start + _INSERT_CHUNK]
        values = [
            {
                "osm_type": o.osm_type,
                "osm_id": o.osm_id,
                "category": o.category,
                "name": o.name,
                "lat": o.lat,
                "lng": o.lng,
                "tags": o.tags,
                "zone_id": zone_id,
                "retrieved_at": o.retrieved_at,
            }
            for o in chunk
        ]
        stmt = pg_insert(Infrastructure).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["osm_type", "osm_id"],
            set_={
                "category": stmt.excluded.category,
                "name": stmt.excluded.name,
                "lat": stmt.excluded.lat,
                "lng": stmt.excluded.lng,
                "tags": stmt.excluded.tags,
                "zone_id": stmt.excluded.zone_id,
                "retrieved_at": stmt.excluded.retrieved_at,
                "updated_at": stmt.excluded.retrieved_at,
            },
        )
        await db.execute(stmt)

    # Keep PostGIS points in sync with authoritative lat/lng (§9).
    await db.execute(
        text(
            "UPDATE infrastructure "
            "SET geometry = ST_SetSRID(ST_MakePoint(lng, lat), 4326) "
            "WHERE geometry IS NULL"
        )
    )
    await db.commit()
    logger.info(
        "infrastructure_refreshed",
        bbox=[south, west, north, east],
        ingested=len(observations),
        zone_id=zone_id,
    )
    return len(observations)


async def refresh_zone_infrastructure(
    db: AsyncSession, zone_id: str, radius_m: float | None = None
) -> int:
    """Convenience: (re)ingest OSM features around a zone centroid."""
    from sqlalchemy import select

    from app.models.zone import Zone

    zone = (
        await db.execute(select(Zone).where(Zone.id == zone_id))
    ).scalar_one_or_none()
    if zone is None:
        return 0
    radius = radius_m if radius_m is not None else max(1000.0, float(zone.radius_meters or 500) * 4)
    south, west, north, east = bbox_for_radius(zone.centroid_lat, zone.centroid_lng, radius)
    try:
        return await refresh_infrastructure(
            db, south, west, north, east, zone_id=zone.id
        )
    except ConnectorError as exc:
        logger.warning(
            "zone_infrastructure_refresh_failed",
            zone=zone_id,
            provider=exc.provider,
            error=exc.message,
        )
        return 0


async def nearest_infrastructure(
    db: AsyncSession, lat: float, lng: float, category: str, limit: int = 5
) -> list[dict]:
    """Nearest features of a category to a point — PostGIS distance (§9)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT id, osm_type, osm_id, category, name, lat, lng,
                       ST_Distance(geometry::geography,
                                   ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography) / 1000.0 AS distance_km
                FROM infrastructure
                WHERE category = :category
                  AND geometry IS NOT NULL
                ORDER BY geometry <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)
                LIMIT :limit
                """
            ),
            {"lat": lat, "lng": lng, "category": category, "limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# ── Geometry write helpers (PRD §9 — geometry kept in sync with lat/lng) ──

async def set_report_geometry(db: AsyncSession, report_id: str, lat: float | None,
                              lng: float | None) -> None:
    """POINT geometry from lat/lng (asyncpg-safe raw SQL, idempotent)."""
    if lat is None or lng is None:
        return
    await db.execute(
        text(
            "UPDATE reports SET geometry = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) "
            "WHERE id = :id"
        ),
        {"id": report_id, "lat": float(lat), "lng": float(lng)},
    )


async def set_zone_geometry(db: AsyncSession, zone_id: str, lat: float, lng: float,
                            radius_m: float) -> None:
    """CIRCLE polygon (geography buffer, metres) around the zone centroid."""
    await db.execute(
        text(
            "UPDATE zones SET geometry = "
            "ST_Buffer(ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography, "
            "GREATEST(:radius, 50))::geometry "
            "WHERE id = :id"
        ),
        {"id": zone_id, "lat": float(lat), "lng": float(lng),
         "radius": float(radius_m or 500.0)},
    )


# ── Spatial queries (PRD §9) ──────────────────────────────────────────────

async def zone_at_point(db: AsyncSession, lat: float, lng: float,
                        radius_m: float = 500.0) -> str | None:
    """Nearest zone containing/within radius of a point — replaces the old
    RADIUS_DEG bounding box in the report pipeline (§9). Returns zone id."""
    row = (
        await db.execute(
            text(
                """
                SELECT id FROM zones
                WHERE deleted = false
                  AND ST_DWithin(
                        ST_MakePoint(centroid_lng, centroid_lat)::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        :radius)
                ORDER BY ST_Distance(
                        ST_MakePoint(centroid_lng, centroid_lat)::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography)
                LIMIT 1
                """
            ),
            {"lat": float(lat), "lng": float(lng), "radius": float(radius_m)},
        )
    ).scalar_one_or_none()
    return row


async def nearby_incidents(db: AsyncSession, lat: float, lng: float,
                           radius_km: float = 5.0) -> list[dict]:
    """Active incidents within radius_km of a point, nearest first (§9)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT i.id, i.zone_id, i.disaster_type, i.priority_score,
                       i.priority_band, i.status, i.active,
                       z.centroid_lat, z.centroid_lng,
                       ST_Distance(
                           ST_MakePoint(z.centroid_lng, z.centroid_lat)::geography,
                           ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                       ) / 1000.0 AS distance_km
                FROM incidents i
                JOIN zones z ON z.id = i.zone_id
                WHERE i.active = true
                  AND ST_DWithin(
                        ST_MakePoint(z.centroid_lng, z.centroid_lat)::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        :radius_m)
                ORDER BY distance_km ASC
                """
            ),
            {"lat": float(lat), "lng": float(lng),
             "radius_m": float(radius_km) * 1000.0},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


async def zones_containing_point(db: AsyncSession, lat: float, lng: float) -> list[str]:
    """Zone ids whose polygon contains the point (geometry), with a centroid
    fallback for rows not yet backfilled (§9 zone intersection)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT id FROM zones
                WHERE deleted = false
                  AND geometry IS NOT NULL
                  AND ST_Contains(geometry, ST_SetSRID(ST_MakePoint(:lng, :lat), 4326))
                UNION
                SELECT id FROM zones
                WHERE deleted = false
                  AND geometry IS NULL
                  AND ST_DWithin(
                        ST_MakePoint(centroid_lng, centroid_lat)::geography,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                        GREATEST(radius_meters, 50))
                """
            ),
            {"lat": float(lat), "lng": float(lng)},
        )
    ).scalars().all()
    return list(rows)
