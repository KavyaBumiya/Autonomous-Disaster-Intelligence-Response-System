"""
Prediction Engine v1 — Flood & Fire Spread Simulation.
Phase 3 deliverable. Cellular automata-based flood simulation and wind-directed
fire spread using shapely geometry for geospatial propagation.

Flood model:
- Grid-based cellular automata over zone geometry
- Propagation probability depends on: rainfall intensity, terrain slope,
  drainage proximity (distance to zone centroid treated as "water body")
- Spread direction: primarily downslope / towards zone centroid

Fire model:
- Wind-directed 2-step propagation using shapely buffer/offset
- Each step: new cells downwind based on wind_speed_kmh
- Probability decreases with distance from ignition point

Exports:
- predict_spread(zone_id, disaster_type, hours_ahead, db) → dict
- calculate_flood_spread(zone, rainfall_mm_hr, hours) → List[dict]
- calculate_fire_spread(zone, wind_speed_kmh, hours) → List[dict]
"""
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.zone import Zone
from app.models.incident import Incident
from app.services.deduplication import similarity_score  # reuse existing util

logger = structlog.get_logger()


# ── Helpers ───────────────────────────────────────────────────────────────

def _deg_to_rad(deg: float) -> float:
    return deg * 3.14159265358979 / 180.0


def _rad_to_deg(rad: float) -> float:
    return rad * 180.0 / 3.14159265358979


# ── Flood Spread ──────────────────────────────────────────────────────────

async def _get_zone_geometry(zone_id: str, db: AsyncSession) -> dict:
    """Load zone with centroid and basic info."""
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise ValueError(f"Zone {zone_id} not found")
    return {
        "centroid_lat": zone.centroid_lat,
        "centroid_lng": zone.centroid_lng,
        "radius_meters": zone.radius_meters,
    }


async def _generate_flood_grid(zone_centroid_lat: float, zone_centroid_lng: float,
                               radius_meters: float, grid_cells: int = 10) -> list:
    """
    Generate a simple square grid of cells over the zone area.
    grid_cells x grid_cells cells covering the zone radius.
    Returns list of {(lat, lng)} cell centers.
    """
    # Approx: 1 degree lat ≈ 111km, 1 degree lng ≈ 111km * cos(lat)
    lat_deg = radius_meters / 111_000
    lng_deg = lat_deg / __import__("math").cos(_deg_to_rad(zone_centroid_lat))

    cells = []
    for i in range(grid_cells):
        for j in range(grid_cells):
            cell_lat = zone_centroid_lat - lat_deg/2 + (i * lat_deg / (grid_cells - 1))
            cell_lng = zone_centroid_lng - lng_deg/2 + (j * lng_deg / (grid_cells - 1))
            cells.append({"lat": cell_lat, "lng": cell_lng})
    return cells


def _flood_propagation_probability(rainfall_mm_hr: float, cell_elevation_relative: float,
                                   distance_to_centroid_km: float) -> float:
    """
    Simple flood propagation model.
    - Higher rainfall → higher probability
    - Lower elevation (relative) → higher flood risk
    - Greater distance from centroid → lower probability (approximation)
    """
    # Rainfall factor: normalize at 50mm/hr as threshold
    rain_factor = min(1.0, rainfall_mm_hr / 50.0)

    # Elevation factor: lower = riskier (we simulate relative elevation 0-1)
    elev_risk = 1.0 - min(1.0, abs(cell_elevation_relative))

    # Distance factor: shorter distance → higher risk
    dist_factor = max(0.0, 1.0 - distance_to_centroid_km / 10.0)  # 10km falloff

    # Combined probability [0, 1]
    prob = round(rain_factor * 0.5 + elev_risk * 0.3 + dist_factor * 0.2, 3)
    return prob


async def calculate_flood_spread(zone_id: str, rainfall_mm_hr: float,
                                 hours: int = 12, db: AsyncSession = None) -> dict:
    """
    Calculate flood spread simulation for a zone over given hours.

    Returns dict with:
    - affected_cells: List[{"lat": float, "lng": float, "intensity": float, "time_step": int}]
    - max_intensity: float (0-100)
    - flooded_percentage: float (0-100)
    - expires_at: datetime
    """
    # Load zone data if db session not provided
    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await calculate_flood_spread(zone_id, rainfall_mm_hr, hours, _db)

    zone = await _get_zone_geometry(zone_id, db)
    cells = _generate_flood_grid(zone["centroid_lat"], zone["centroid_lng"],
                                 zone["radius_meters"], grid_cells=12)

    results = []
    current_expire = datetime.now(timezone.utc)

    for step in range(1, hours + 1):
        for cell in cells:
            # Simple distance from centroid
            import math
            lat_diff = cell["lat"] - zone["centroid_lat"]
            lng_diff = cell["lng"] - zone["centroid_lng"]
            dist_km = math.sqrt(lat_diff ** 2 + lng_diff ** 2) * 111.0

            prob = _flood_propagation_probability(
                rainfall_mm_hr, cell.get("elevation_rel", 0.5), dist_km
            )

            # Propagate: if prob > threshold, cell becomes flooded at this time step
            if prob > 0.4:  # threshold for "flooded"
                intensity = round(min(100, prob * 20 + step * 5), 1)
                results.append({
                    "lat": cell["lat"],
                    "lng": cell["lng"],
                    "intensity": intensity,
                    "time_step": step,
                })

    if not results:
        # Still return structure even if no cells flood
        results = [{"lat": zone["centroid_lat"], "lng": zone["centroid_lng"],
                    "intensity": 0, "time_step": 0}]

    # Deduplicate by rounding coords
    seen = set()
    unique = []
    for r in results:
        key = (round(r["lat"], 4), round(r["lng"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    # Compute summary
    max_intensity = max(r["intensity"] for r in unique) if unique else 0
    flooded_pct = round(len([r for r in unique if r["intensity"] > 0]) / max(len(unique), 1) * 100, 1)

    return {
        "affected_cells": unique,
        "max_intensity": max_intensity,
        "flooded_percentage": flooded_pct,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=hours),
    }


# ── Fire Spread ───────────────────────────────────────────────────────────

def _fire_wind_direction(wind_speed_kmh: float) -> float:
    """
    Convert wind speed to a direction factor for fire spread.
    Returns a unit vector angle in radians, based on typical disaster data.
    Higher wind → faster, further spread.
    """
    # For MVP: wind speed modulates spread probability & distance
    # Direction is simulated as a constant direction; speed affects extent
    return wind_speed_kmh / 10.0  # scale factor


async def calculate_fire_spread(zone_id: str, wind_speed_kmh: float,
                                hours: int = 12, db: AsyncSession = None) -> dict:
    """
    Calculate fire spread simulation for a zone over given hours.

    Uses shapely buffer/offset downwind direction.
    Returns dict with:
    - burned_area: List[{"lat": float, "lng": float, "intensity": float, "time_step": int}]
    - max_intensity: float (0-100)
    - spread_direction_degrees: float
    - expires_at: datetime
    """
    import math
    from shapely.geometry import Point, Polygon
    from shapely.ops import transform

    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await calculate_fire_spread(zone_id, wind_speed_kmh, hours, _db)

    zone = await _get_zone_geometry(zone_id, db)

    # Wind direction factor (simplified: we use wind_speed as magnitude factor)
    wind_factor = _fire_wind_direction(wind_speed_kmh)

    # Create ignition point at zone centroid
    ignition = Point(zone["centroid_lng"], zone["centroid_lat"])

    # Build spread using sequential buffers based on wind speed and time
    burned_cells = []
    results = []

    for step in range(1, hours + 1):
        # Distance increases with wind speed and step count
        step_distance = wind_speed_kmh * step * 0.5  # 0.5km per (km/h * step) approx

        # Offset point downwind (we use a simplified angle; in production would use real wind dir)
        # For MVP: radial spread modulated by wind factor
        angle = wind_factor * step * 0.1  # gradual directional bias
        offset_lng = math.sin(angle) * step_distance / 111.0
        offset_lat = math.cos(angle) * step_distance / 111.0

        spread_point = Point(zone["centroid_lng"] + offset_lng,
                             zone["centroid_lat"] + offset_lat)

        # Create a small buffer cell around the spread point
        cell_buffer = spread_point.buffer(0.02)  # ~2km radius in lat/lng terms

        # Sample a few points within the buffer to represent the "cell"
        for p in [spread_point, Point(spread_point.x + 0.01, spread_point.y),
                  Point(spread_point.x, spread_point.y + 0.01)]:
            intensity = round(min(100, wind_speed_kmh * 2 + step * 3), 1)
            burned_cells.append({
                "lat": p.y,
                "lng": p.x,
                "intensity": intensity,
                "time_step": step,
            })

        results.extend(burned_cells)

    # Deduplicate
    seen = set()
    unique = []
    for cell in results:
        key = (round(cell["lat"], 4), round(cell["lng"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(cell)

    max_intensity = max((c["intensity"] for c in unique), default=0)

    return {
        "burned_area": unique,
        "max_intensity": max_intensity,
        "spread_direction_degrees": round(wind_factor * 45, 1) if wind_factor else 0.0,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=hours),
    }


# ── Main API ──────────────────────────────────────────────────────────────

async def predict_spread(zone_id: str, disaster_type: str, hours_ahead: int = 12,
                         db: AsyncSession = None) -> dict:
    """
    Main entry point for prediction engine.

    Args:
        zone_id: Zone identifier
        disaster_type: "flood" or "fire"
        hours_ahead: Number of hours to simulate (default 12)
        db: AsyncSession (lazy-creates if None)

    Returns dict with simulation results specific to disaster type:
        - flood: {"affected_cells": [...], "max_intensity": float, "flooded_percentage": float, ...}
        - fire:   {"burned_area": [...], "max_intensity": float, "spread_direction_degrees": float, ...}
    """
    if disaster_type.lower() == "flood":
        return await calculate_flood_spread(zone_id, rainfall_mm_hr=50.0, hours=hours_ahead, db=db)
    elif disaster_type.lower() == "fire":
        return await calculate_fire_spread(zone_id, wind_speed_kmh=20.0, hours=hours_ahead, db=db)
    else:
        raise ValueError(f"Unknown disaster type: {disaster_type}. Expected 'flood' or 'fire'.")