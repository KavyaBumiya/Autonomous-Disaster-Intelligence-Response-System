"""Route intelligence — disaster-aware primary + alternate route suggestions.

Primary route: real OSRM road routing via `calculate_route` (hazard-adjusted
costs, clearly-labelled haversine fallback). Origin resolution, in order:
    1. explicit origin_lat/origin_lng from the caller (additive field)
    2. nearest coordinate-bearing Resource (located staging asset)
    3. deterministic western zone-entry point (labelled in the response)

Alternate routes remain deterministic detour estimates scaled from the
computed primary distance (contract preserved for the frontend).
"""
import math
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.resource import Resource
from app.models.zone import Zone
from app.services.route_intelligence import calculate_route, haversine_km

router = APIRouter()


class RouteComputeBody(BaseModel):
    zone_id: str
    blocked_roads: str = Field(default="", description="Comma-separated blocked road labels")
    disaster_type: str = "flood"
    origin_lat: float | None = Field(default=None, description="Optional staging origin (additive)")
    origin_lng: float | None = Field(default=None, description="Optional staging origin (additive)")


async def _resolve_origin(
    db: AsyncSession, zone: Zone, body: RouteComputeBody
) -> tuple[float, float, str]:
    """(lat, lng, origin_label) — explicit > nearest asset > zone entry point."""
    if body.origin_lat is not None and body.origin_lng is not None:
        return body.origin_lat, body.origin_lng, "caller-provided origin"

    rows = await db.execute(
        select(Resource).where(Resource.lat.isnot(None), Resource.lng.isnot(None))
    )
    best: Resource | None = None
    best_d = math.inf
    for r in rows.scalars().all():
        d = haversine_km(zone.centroid_lat, zone.centroid_lng, r.lat, r.lng)
        if d < best_d:
            best, best_d = r, d
    if best is not None:
        return best.lat, best.lng, f"nearest located asset ({best.name or best.resource_type})"

    # Deterministic entry point: zone boundary, due west of the centroid.
    radius_m = float(zone.radius_meters or 500)
    d_lat = radius_m / 111_320.0
    cos_lat = max(0.01, math.cos(math.radians(zone.centroid_lat)))
    d_lng = radius_m / (111_320.0 * cos_lat)
    return (
        zone.centroid_lat,
        zone.centroid_lng - d_lng,
        "zone western entry point (no located staging asset)",
    )


@router.post("/compute", tags=["routes"])
async def compute_routes(
    body: RouteComputeBody,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Primary + alternate routes for a zone.

    Primary: OSRM road route with disaster penalties (deterministic,
    no LLM — PRD). Alternates: deterministic detour estimates scaled
    from the computed primary distance.
    """
    result = await db.execute(select(Zone).where(Zone.id == body.zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(404, detail="Zone not found")

    blocked = [b.strip() for b in (body.blocked_roads or "").split(",") if b.strip()]
    origin_lat, origin_lng, origin_label = await _resolve_origin(db, zone, body)

    route = await calculate_route(
        origin_lat,
        origin_lng,
        zone.centroid_lat,
        zone.centroid_lng,
        blocked_roads=blocked,
        db=db,
    )

    primary_km = float(route["distance_km"])
    primary_minutes = max(1, int(round(float(route["duration_minutes"]))))
    speed_kmh = 28.0 if body.disaster_type == "flood" else 35.0

    def _route(distance_km: float, note: str, detour: str | None = None) -> dict:
        minutes = max(3, int(round(distance_km / speed_kmh * 60)))
        return {
            "distance_km": round(distance_km, 2),
            "estimated_minutes": minutes,
            "note": note,
            "detour_reason": detour,
        }

    primary = {
        "distance_km": round(primary_km, 2),
        "estimated_minutes": primary_minutes,
        "note": f"{route['note']} Origin: {origin_label}.",
        "detour_reason": None,
    }

    alternates = []
    for i, road in enumerate(blocked[:3]):
        detour_km = primary_km * (1.35 + 0.2 * i)
        alternates.append(
            _route(
                detour_km,
                f"Estimated detour avoiding: {road}",
                f"Blocked: {road} — use parallel corridor ({i + 1})",
            )
        )

    if not blocked:
        alternates.append(
            _route(primary_km * 1.4, "Secondary arterial alternate", "Lower congestion risk")
        )

    engine = (
        "osrm_route_planner_v1"
        if route.get("source") == "osrm"
        else "deterministic_route_planner_v1"
    )

    response = {
        "zone_id": zone.id,
        "zone_name": zone.name,
        "disaster_type": body.disaster_type,
        "blocked_roads": blocked,
        "primary_route": primary,
        "alternate_routes": alternates,
        "engine": engine,
        # Additive fields (plan §Phase 5) — ignored by existing clients.
        "source": route.get("source"),
        "geometry": route.get("geometry"),
        "cost": route.get("cost"),
        "penalties": route.get("penalties"),
    }

    # WebSocket route_changed (§25) — enrichment only, never breaks the reply
    try:
        from app.services.websocket import emit_route_changed

        await emit_route_changed(
            zone.id,
            {
                "disaster_type": body.disaster_type,
                "primary_route": primary,
                "alternate_count": len(alternates),
                "engine": engine,
                "source": route.get("source"),
            },
        )
    except Exception as exc:  # noqa: BLE001
        import structlog

        structlog.get_logger().warning("route_changed_emit_failed", error=str(exc))

    return response
