"""Route intelligence — deterministic alternate-route suggestions."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.database import get_db
from app.models.zone import Zone

router = APIRouter()


class RouteComputeBody(BaseModel):
    zone_id: str
    blocked_roads: str = Field(default="", description="Comma-separated blocked road labels")
    disaster_type: str = "flood"


@router.post("/compute", tags=["routes"])
async def compute_routes(
    body: RouteComputeBody,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """Deterministic primary + alternate route estimates for a zone.

    LLM is intentionally not used (PRD: deterministic orchestration).
    Distances scale with zone radius and blocked-road count.
    """
    result = await db.execute(select(Zone).where(Zone.id == body.zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        from fastapi import HTTPException

        raise HTTPException(404, detail="Zone not found")

    blocked = [b.strip() for b in (body.blocked_roads or "").split(",") if b.strip()]
    base_km = max(1.0, (zone.radius_meters or 500) / 1000.0 * 2.5)
    # Rough speed assumption for emergency vehicle in urban flood conditions
    speed_kmh = 28.0 if body.disaster_type == "flood" else 35.0

    def _route(distance_km: float, note: str, detour: str | None = None) -> dict:
        minutes = max(3, int(round(distance_km / speed_kmh * 60)))
        return {
            "distance_km": round(distance_km, 2),
            "estimated_minutes": minutes,
            "note": note,
            "detour_reason": detour,
        }

    primary = _route(base_km, "Fastest corridor from staging area to zone centroid")
    alternates = []
    for i, road in enumerate(blocked[:3]):
        detour_km = base_km * (1.35 + 0.2 * i)
        alternates.append(
            _route(
                detour_km,
                f"Detour avoiding: {road}",
                f"Blocked: {road} — use parallel corridor ({i + 1})",
            )
        )

    if not blocked:
        # Offer one slightly longer alternate even without input
        alternates.append(
            _route(base_km * 1.4, "Secondary arterial alternate", "Lower congestion risk")
        )

    return {
        "zone_id": zone.id,
        "zone_name": zone.name,
        "disaster_type": body.disaster_type,
        "blocked_roads": blocked,
        "primary_route": primary,
        "alternate_routes": alternates,
        "engine": "deterministic_route_planner_v1",
    }
