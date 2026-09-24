"""
AEGIS-AI — Route Intelligence Service (PRD §5.5)
================================================
Disaster-aware routing — not plain shortest-path.

Cost model (deterministic, no LLM):

    cost = distance_km
         + traffic_penalty      (time-of-day heuristic)
         + flood_penalty        (proximity of segment endpoints to flood zones)
         + bridge_risk_penalty  (placeholder — OSM bridge tags when available)
         + blockage_penalty     (caller-supplied blocked roads / high-priority incidents)

Primary pathfinder: OSRM public demo server (road network).
Fallback: haversine straight-line estimate when OSRM is unreachable
          (DEGRADED MODE — result is clearly labelled).

Exports:
    calculate_route(origin, destination, ...) -> dict
    shelters_for_zone(zone_id, db)            -> list[dict]  (shared helper)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import Resource
from app.models.zone import Zone
from app.models.incident import Incident
from app.models.weather import WeatherReading

logger = structlog.get_logger()

OSRM_BASE = "https://router.project-osrm.org"
OSRM_TIMEOUT_S = 8.0

# Penalty weights (PRD §5.5 — tunable)
W_TRAFFIC = 0.15
W_FLOOD = 0.40
W_BRIDGE = 0.10
W_BLOCKAGE = 0.60
W_WEATHER_RISK = 0.25


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _traffic_penalty(now: datetime | None = None) -> float:
    """Rush-hour heuristic for Indian urban contexts (07–10, 17–20 local)."""
    local = (now or datetime.now(timezone.utc)).hour
    if local in (7, 8, 9, 17, 18, 19):
        return 0.25
    return 0.0


async def calculate_route(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    *,
    blocked_roads: list[str] | None = None,
    avoid_zone_ids: list[str] | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """
    Compute a disaster-aware route between two points.

    Returns:
      {
        "route_id": str,
        "origin": {...}, "destination": {...},
        "distance_km": float,
        "duration_minutes": float,
        "cost": float,                 # hazard-adjusted cost used for ranking
        "penalties": {traffic, flood, bridge, blockage, weather},
        "geometry": [[lng, lat], ...], # for Mapbox
        "source": "osrm" | "fallback_haversine",
        "note": str,
      }
    """
    straight = haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)

    # ── Hazard signals (best-effort when db provided) ────────────────────
    flood_pen = 0.0
    weather_pen = 0.0
    blockage_pen = 0.0
    near_critical: list[str] = []

    if db is not None:
        try:
            # Flood / critical zones near the corridor midpoint
            mid_lat = (origin_lat + dest_lat) / 2
            mid_lng = (origin_lng + dest_lng) / 2
            # ~2 km window
            dlat, dlng = 0.018, 0.018
            zone_rows = await db.execute(
                select(Zone).where(
                    Zone.deleted == False,
                    Zone.centroid_lat.between(mid_lat - dlat, mid_lat + dlat),
                    Zone.centroid_lng.between(mid_lng - dlng, mid_lng + dlng),
                )
            )
            zones = zone_rows.scalars().all()
            for z in zones:
                inc_row = await db.execute(
                    select(Incident).where(
                        Incident.zone_id == z.id,
                        Incident.active == True,
                    ).limit(1)
                )
                inc = inc_row.scalar_one_or_none()
                if not inc:
                    continue
                dist_km = haversine_km(mid_lat, mid_lng, z.centroid_lat, z.centroid_lng)
                if dist_km <= 2.5:
                    severity = 0.3 + min(1.0, (inc.priority_score or 0) / 100.0)
                    flood_pen += severity * max(0.0, 1.0 - dist_km / 2.5)
                    if (inc.priority_score or 0) >= 70:
                        near_critical.append(z.id)

            # Weather risk (latest reading near destination)
            w_row = await db.execute(
                select(WeatherReading)
                .order_by(WeatherReading.polled_at.desc())
                .limit(1)
            )
            w = w_row.scalar_one_or_none()
            if w is not None:
                # risk_score is 0–1 on WeatherReading (see model)
                weather_pen = min(1.0, (w.risk_score or 0.0)) * W_WEATHER_RISK
        except Exception as exc:
            logger.warning("route_hazard_lookup_failed", error=str(exc))

    # ── Blockage / avoided zones ─────────────────────────────────────────
    if blocked_roads:
        blockage_pen = min(1.0, 0.35 * len(blocked_roads))
    if avoid_zone_ids:
        blockage_pen = min(1.0, blockage_pen + 0.25 * len(avoid_zone_ids))

    traffic_pen = _traffic_penalty()
    bridge_pen = 0.05 if straight > 5.0 else 0.0  # longer cross-river detours

    # ── OSRM road route (preferred) ──────────────────────────────────────
    source = "fallback_haversine"
    distance_km = straight
    duration_min = (straight / 30.0) * 60.0  # ~30 km/h emergency average
    geometry: list[list[float]] = [
        [origin_lng, origin_lat],
        [dest_lng, dest_lat],
    ]
    note = "Straight-line estimate — OSRM unavailable (DEGRADED)."

    try:
        async with httpx.AsyncClient(timeout=OSRM_TIMEOUT_S) as client:
            url = (
                f"{OSRM_BASE}/route/v1/driving/"
                f"{origin_lng},{origin_lat};{dest_lng},{dest_lat}"
                f"?overview=full&geometries=geojson&alternatives=false"
            )
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "Ok" and data.get("routes"):
                route0 = data["routes"][0]
                distance_km = float(route0["distance"]) / 1000.0
                duration_min = float(route0["duration"]) / 60.0
                geometry = route0["geometry"]["coordinates"]
                source = "osrm"
                note = "OSRM road route with disaster penalties applied to cost."
    except Exception as exc:
        logger.warning("osrm_failed_using_fallback", error=str(exc))

    # ── Deterministic hazard-adjusted cost (PRD §5.5) ────────────────────
    penalties = {
        "traffic": round(traffic_pen, 3),
        "flood": round(min(1.0, flood_pen), 3),
        "bridge": round(bridge_pen, 3),
        "blockage": round(blockage_pen, 3),
        "weather": round(weather_pen, 3),
    }
    cost = (
        distance_km
        + distance_km * W_TRAFFIC * penalties["traffic"]
        + distance_km * W_FLOOD * penalties["flood"]
        + distance_km * W_BRIDGE * penalties["bridge"]
        + distance_km * W_BLOCKAGE * penalties["blockage"]
        + distance_km * penalties["weather"]
    )
    # Duration also scales with flood/blocked corridors (slower progress)
    adjusted_duration = duration_min * (
        1.0
        + 0.5 * penalties["flood"]
        + 0.8 * penalties["blockage"]
        + 0.3 * penalties["traffic"]
    )

    route_id = (
        f"R-{origin_lat:.4f},{origin_lng:.4f}->{dest_lat:.4f},{dest_lng:.4f}"
    )

    return {
        "route_id": route_id,
        "origin": {"lat": origin_lat, "lng": origin_lng},
        "destination": {"lat": dest_lat, "lng": dest_lng},
        "distance_km": round(distance_km, 2),
        "duration_minutes": round(adjusted_duration, 1),
        "straight_line_km": round(straight, 2),
        "cost": round(cost, 3),
        "penalties": penalties,
        "near_critical_zone_ids": near_critical,
        "geometry": geometry,
        "source": source,
        "blocked_roads": blocked_roads or [],
        "note": note,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


async def shelters_near(
    lat: float,
    lng: float,
    db: AsyncSession,
    limit: int = 5,
    radius_km: float = 15.0,
) -> list[dict]:
    """Shelter resources sorted by distance from a point (capacity-aware)."""
    result = await db.execute(
        select(Resource).where(
            and_(
                Resource.resource_type == "shelter",
                Resource.lat.isnot(None),
                Resource.lng.isnot(None),
            )
        )
    )
    shelters = []
    for r in result.scalars().all():
        d = haversine_km(lat, lng, r.lat or 0.0, r.lng or 0.0)
        if d > radius_km:
            continue
        free = max(0, (r.capacity or 0) - (r.current_load or 0))
        shelters.append(
            {
                "id": r.id,
                "name": r.name,
                "lat": r.lat,
                "lng": r.lng,
                "capacity": r.capacity,
                "current_load": r.current_load,
                "free_capacity": free,
                "available": bool(r.available and free > 0),
                "distance_km": round(d, 2),
            }
        )
    shelters.sort(key=lambda s: (not s["available"], s["distance_km"]))
    return shelters[:limit]
