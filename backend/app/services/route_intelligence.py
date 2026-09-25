"""
AEGIS-AI — Route Intelligence Service (PRD §5.5)
================================================
Disaster-aware routing — not plain shortest-path.

Cost model (deterministic, no LLM):

    cost = distance_km
         + traffic_penalty      (time-of-day heuristic)
         + flood_penalty        (proximity of segment endpoints to flood zones)
         + bridge_risk_penalty  (cached OSM bridge features near the corridor —
                                 replaces the old straight>5km heuristic)
         + blockage_penalty     (caller-supplied blocked roads + field reports
                                 mentioning blockages along the corridor)
         + weather_penalty      (latest weather risk)
         + satellite_penalty    (satellite evidence when present; provider is
                                 not configured today → always 0, never
                                 fabricated — §32)

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

import structlog
from sqlalchemy import select, and_, or_, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.base import ConnectorError
from app.integrations.gis.osrm import OsrmConnector
from app.models.resource import Resource
from app.models.zone import Zone
from app.models.incident import Incident
from app.models.weather import WeatherReading

logger = structlog.get_logger()

# Penalty weights (PRD §5.5 — tunable)
W_TRAFFIC = 0.15
W_FLOOD = 0.40
W_BRIDGE = 0.10
W_BLOCKAGE = 0.60
W_WEATHER_RISK = 0.25

# Phase 11 — corridor signals
BRIDGE_PROXIMITY_DEG = 0.002          # ~200 m corridor half-width
BRIDGE_PENALTY_PER_FEATURE = 0.06
BRIDGE_PENALTY_MAX = 0.40
FIELD_REPORT_WINDOW_HOURS = 6
FIELD_REPORT_PENALTY_PER_HIT = 0.15
SATELLITE_PENALTY_PER_OBS = 0.10
SATELLITE_PENALTY_MAX = 0.30
SATELLITE_SOURCES = ("satellite", "sentinel", "landsat", "modis")
BLOCKAGE_KEYWORDS = (
    "road closed",
    "road blocked",
    "street blocked",
    "route blocked",
    "bridge collapsed",
    "bridge washed",
    "underwater",
    "waterlogging",
    "water logged",
    "highway closed",
    "passage blocked",
)


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


async def corridor_signals(
    origin_lat: float,
    origin_lng: float,
    dest_lat: float,
    dest_lng: float,
    geometry: list[list[float]],
    db: AsyncSession,
) -> dict[str, Any]:
    """Phase 11 — deterministic corridor risk signals from cached data only.

    Corridor bbox derives from the resolved route polyline (road detours can
    leave the straight-line envelope). Returns {bridge_count, bridge_gis_data,
    field_report_hits, satellite_observations} — every count is real; missing
    data reports 0 with an availability flag (never fabricated, §7/§32).
    """
    pad = 0.01
    if geometry and len(geometry) >= 2:
        lons = [c[0] for c in geometry]
        lats = [c[1] for c in geometry]
        south, north = min(lats) - pad, max(lats) + pad
        west, east = min(lons) - pad, max(lons) + pad
    else:
        south = min(origin_lat, dest_lat) - pad
        north = max(origin_lat, dest_lat) + pad
        west = min(origin_lng, dest_lng) - pad
        east = max(origin_lng, dest_lng) + pad

    out: dict[str, Any] = {
        "bridge_count": 0,
        "bridge_gis_data": False,
        "field_report_hits": 0,
        "satellite_observations": 0,
    }

    # ── Bridge features near the route polyline (cached OSM/GIS only) ────
    try:
        from app.models.infrastructure import Infrastructure

        rows = (
            await db.execute(
                select(Infrastructure.lat, Infrastructure.lng).where(
                    and_(
                        Infrastructure.category == "bridge",
                        Infrastructure.lat.between(south, north),
                        Infrastructure.lng.between(west, east),
                    )
                ).limit(500)
            )
        ).all()
        total_features = (
            await db.execute(
                select(sa_func.count(Infrastructure.id)).where(
                    and_(
                        Infrastructure.lat.between(south, north),
                        Infrastructure.lng.between(west, east),
                    )
                )
            )
        ).scalar() or 0
        out["bridge_gis_data"] = total_features > 0

        if rows and len(geometry) >= 2:
            from shapely.geometry import LineString, Point

            line = LineString([(c[0], c[1]) for c in geometry])
            for lat, lng in rows:
                if line.distance(Point(lng, lat)) <= BRIDGE_PROXIMITY_DEG:
                    out["bridge_count"] += 1
        else:
            out["bridge_count"] = len(rows)  # bbox fallback (2-point geometry)
    except Exception as exc:  # signals are enrichment — never break routing
        logger.warning("route_bridge_signal_failed", error=str(exc))

    # ── Field reports mentioning blockages near the corridor ─────────────
    try:
        from datetime import timedelta

        from app.models.report import Report

        since = datetime.now(timezone.utc) - timedelta(hours=FIELD_REPORT_WINDOW_HOURS)
        texts = (
            await db.execute(
                select(Report.message_text, Report.transcript).where(
                    and_(
                        Report.suppressed == False,  # noqa: E712
                        Report.lat.isnot(None),
                        Report.lng.isnot(None),
                        Report.lat.between(south, north),
                        Report.lng.between(west, east),
                        Report.created_at >= since,
                    )
                ).limit(200)
            )
        ).all()
        hits = 0
        for message_text, transcript in texts:
            blob = ((message_text or "") + " " + (transcript or "")).lower()
            if any(kw in blob for kw in BLOCKAGE_KEYWORDS):
                hits += 1
        out["field_report_hits"] = hits
    except Exception as exc:
        logger.warning("route_field_report_signal_failed", error=str(exc))

    # ── Satellite evidence (provider not configured today → 0, §32) ─────
    try:
        from app.models.external import ExternalObservation

        ors = [ExternalObservation.source.ilike(f"{s}%") for s in SATELLITE_SOURCES]
        sat = (
            await db.execute(
                select(sa_func.count(ExternalObservation.id)).where(
                    and_(
                        or_(*ors),
                        ExternalObservation.lat.isnot(None),
                        ExternalObservation.lng.isnot(None),
                        ExternalObservation.lat.between(south, north),
                        ExternalObservation.lng.between(west, east),
                    )
                )
            )
        ).scalar() or 0
        out["satellite_observations"] = int(sat)
    except Exception as exc:
        logger.warning("route_satellite_signal_failed", error=str(exc))

    return out


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
        osrm = OsrmConnector()
        r0 = await osrm.route(origin_lat, origin_lng, dest_lat, dest_lng)
        if r0 is not None:
            distance_km = r0["distance_m"] / 1000.0
            duration_min = r0["duration_s"] / 60.0
            if r0["geometry"]:
                geometry = r0["geometry"]
            source = "osrm"
            note = "OSRM road route with disaster penalties applied to cost."
    except ConnectorError as exc:
        logger.warning(
            "osrm_failed_using_fallback",
            provider=exc.provider,
            error=exc.message,
            status_code=exc.status_code,
        )
    except Exception as exc:
        logger.warning("osrm_failed_using_fallback", error=str(exc))

    # ── Phase 11: corridor signals on the resolved geometry ─────────────
    # Replaces the old `straight > 5.0` bridge heuristic with real cached
    # OSM bridge features; adds field-report blockages + satellite evidence
    # (provider not configured → honest zeros, §32).
    signals: dict[str, Any] = {
        "bridge_count": 0,
        "bridge_gis_data": False,
        "field_report_hits": 0,
        "satellite_observations": 0,
    }
    if db is not None:
        try:
            signals = await corridor_signals(
                origin_lat, origin_lng, dest_lat, dest_lng, geometry, db
            )
        except Exception as exc:
            logger.warning("route_corridor_signals_failed", error=str(exc))

    bridge_pen = (
        min(BRIDGE_PENALTY_MAX, BRIDGE_PENALTY_PER_FEATURE * signals["bridge_count"])
        if signals["bridge_count"]
        else 0.0
    )
    field_report_pen = min(
        1.0, FIELD_REPORT_PENALTY_PER_HIT * signals["field_report_hits"]
    )
    satellite_pen = min(
        SATELLITE_PENALTY_MAX,
        SATELLITE_PENALTY_PER_OBS * signals["satellite_observations"],
    )
    blockage_pen = min(1.0, blockage_pen + field_report_pen)

    # ── Deterministic hazard-adjusted cost (PRD §5.5) ────────────────────
    penalties = {
        "traffic": round(traffic_pen, 3),
        "flood": round(min(1.0, flood_pen), 3),
        "bridge": round(bridge_pen, 3),
        "blockage": round(blockage_pen, 3),
        "weather": round(weather_pen, 3),
        "satellite": round(satellite_pen, 3),
    }
    cost = (
        distance_km
        + distance_km * W_TRAFFIC * penalties["traffic"]
        + distance_km * W_FLOOD * penalties["flood"]
        + distance_km * W_BRIDGE * penalties["bridge"]
        + distance_km * W_BLOCKAGE * penalties["blockage"]
        + distance_km * penalties["weather"]
        + distance_km * penalties["satellite"]
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
        "penalty_details": {
            "bridge_features_near_route": signals["bridge_count"],
            "bridge_gis_data": signals["bridge_gis_data"],
            "field_report_hits": signals["field_report_hits"],
            "satellite_observations": signals["satellite_observations"],
            "satellite_note": (
                "provider not configured — no observations (never fabricated)"
                if signals["satellite_observations"] == 0
                else "satellite observations present"
            ),
        },
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
