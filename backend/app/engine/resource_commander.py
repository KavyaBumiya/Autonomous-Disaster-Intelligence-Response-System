"""
Resource Commander v1 — Phase 3.
Resource allocation engine that assigns available rescue units to incidents
based on distance, capacity, and priority scoring.

Algorithm:
1. Fetch all available resources (available=True, current_load < capacity)
2. Compute distance from each resource to incident zone centroid
3. Score resources: distance_weight * dist + capacity_weight * (1 - current_load/capacity)
4. Assign top-N resources to the incident
5. Create Action records of type "dispatch" with resource assignments
6. Emit WebSocket events for resource assignment changes

Phase 2 Integration:
- behaviour_risk_score: Higher risk incidents get resources assigned faster
- supply_urgency: Critical shortages prompt immediate dispatch
"""
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.resource import Resource
from app.models.action import Action
from app.models.incident import Incident
from app.services.websocket import emit_action_state_changed, emit_incident_priority_updated

logger = structlog.get_logger()

# Default number of resources to assign per incident (configurable)
DEFAULT_RESOURCE_COUNT = 3

# Scoring weights: distance (0-1) + capacity availability (0-1)
DISTANCE_WEIGHT = 0.6
CAPACITY_WEIGHT = 0.4

# Phase 2 integration weights
BEHAVIOUR_WEIGHT = 0.15  # behaviour risk influence on scoring
SUPPLY_WEIGHT = 0.10     # supply urgency influence on scoring


async def command_resources(incident: Incident, db: AsyncSession,
                            behaviour_risk_score: float = 0.0,
                            supply_urgency: float = 0.0) -> dict:
    """
    Assign available resources to an incident.

    Parameters:
    - incident: the incident to assign resources for
    - db: database session
    - behaviour_risk_score: float 0-1 from Behaviour AI assessment (higher = more urgent)
    - supply_urgency: float 0-1 from Supply Chain forecast (higher = critical shortage)

    Returns dict with:
    - assigned_resources: List[dict] with resource details
    - action_id: str — the created Action record ID
    - priority_score: float — updated priority after resource assignment
    """
    # ── Step 1: Fetch available resources ───────────────────────────────
    result = await db.execute(
        select(Resource).where(
            and_(
                Resource.available == True,
                Resource.current_load < Resource.capacity,
            )
        )
    )
    all_resources = result.scalars().all()

    if not all_resources:
        logger.info("No available resources for incident", incident_id=incident.id)
        return {
            "assigned_resources": [],
            "action_id": None,
            "priority_score": incident.priority_score or 0.0,
            "message": "No available resources at this time.",
        }

    # ── Step 2: Score resources by proximity to incident zone ───────────
    zone_id = incident.zone_id
    if not zone_id:
        logger.warning("Incident has no zone_id", incident_id=incident.id)
        # Cannot compute distance without zone; assign randomly or skip
        # For MVP: assign first N available resources
        selected = all_resources[:DEFAULT_RESOURCE_COUNT]
    else:
        # Load zone centroid
        from app.models.zone import Zone
        zone_result = await db.execute(select(Zone).where(Zone.id == zone_id))
        zone = zone_result.scalar_one_or_none()

        if not zone:
            logger.warning("Zone not found for incident", incident_id=incident.id, zone_id=zone_id)
            selected = all_resources[:DEFAULT_RESOURCE_COUNT]
        else:
            centroid_lat = zone.centroid_lat
            centroid_lng = zone.centroid_lng

# Score each resource by distance + capacity factor
            # Phase 2 integration: behaviour risk + supply urgency modifiers
            behaviour_modifier = 1.0 + BEHAVIOUR_WEIGHT * behaviour_risk_score  # 1.0-1.15 range
            supply_modifier = 1.0 + SUPPLY_WEIGHT * supply_urgency        # 1.0-1.10 range
            scored = []
            for r in all_resources:
                # Distance approximation: we'll use a simple placeholder
                # In production: haversine or PostGIS spatial query
                dist_km = _resource_distance_km(r, centroid_lat, centroid_lng)
                capacity_factor = 1.0 - (r.current_load / max(r.capacity, 1))
                # Normalized scores: distance (0-1, 50km = max), capacity factor (0-1)
                dist_score = min(1.0, dist_km / 50.0)  # 50km normalizes to 1.0
                cap_score = capacity_factor
                # Apply Phase 2 modifiers: higher risk/urgency increases score (dispatch priority)
                adjusted_score = (DISTANCE_WEIGHT * dist_score + CAPACITY_WEIGHT * cap_score
                                * behaviour_modifier * supply_modifier)
                scored.append((adjusted_score, r))
            scored.sort(key=lambda x: x[0], reverse=True)
            selected = [r for _, r in scored[:DEFAULT_RESOURCE_COUNT]]

    # ── Step 3: Update resource availability & load ─────────────────────
    assigned_ids = []
    for r in selected:
        r.available = False
        r.current_load = min(r.capacity, r.current_load + 1)  # increment load
        assigned_ids.append(r.id)
        await db.flush()

    # ── Step 4: Create Action record ────────────────────────────────────
    action_id = str(uuid.uuid4())
    resource_names = ", ".join([r.name for r in selected])
    description = (
        f"Resource allocation for {incident.disaster_type or 'incident' } — "
        f"{resource_names}. {DEFAULT_RESOURCE_COUNT} units dispatched. "
        f"Behaviour risk: {behaviour_risk_score:.1f}, Supply urgency: {supply_urgency:.1f}."
    )

    action = Action(
        id=action_id,
        incident_id=incident.id,
        zone_id=zone_id or "",
        action_type="dispatch",
        description=description,
        recommended_by="resource_commander",
        status="pending_approval",
        priority_score=incident.priority_score or 0.0,
    )
    db.add(action)
    await db.flush()

    # ── Step 5: Emit WebSocket events ───────────────────────────────────
    await emit_action_state_changed(
        action_id=action.id,
        zone_id=zone_id or incident.zone_id or "",
        new_status="pending_approval",
        changed_by_role="resource_commander",
    )

    # Also emit incident priority updated if priority changed
    old_priority = incident.priority_score
    # Base priority bump + Phase 2 adjustments
    behaviour_factor = 1.0 + 0.5 * behaviour_risk_score  # higher risk = larger priority bump
    supply_factor = 1.0 + 0.3 * supply_urgency         # critical shortage = larger bump
    incident.priority_score = round(min(
        (incident.priority_score or 0.0) + 10.0 * behaviour_factor * supply_factor, 100.0), 1)
    await emit_incident_priority_updated(
        zone_id=zone_id or incident.zone_id or "",
        incident_id=incident.id,
        old_priority=old_priority,
        new_priority=incident.priority_score,
        xai_reasoning=f"Resources assigned: {resource_names}. "
                      f"Behaviour risk: {behaviour_risk_score:.1f}, "
                      f"Supply urgency: {supply_urgency:.1f}. "
                      f"Priority adjusted for dispatch.",
        disaster_type=incident.disaster_type,
    )

    # ── Step 6: Return result ───────────────────────────────────────────
    resource_details = [
        {
            "resource_id": r.id,
            "name": r.name,
            "resource_type": r.resource_type,
            "capacity": r.capacity,
            "current_load": r.current_load,
            "lat": r.lat,
            "lng": r.lng,
            "available": r.available,
        }
        for r in selected
    ]

    logger.info("Resources assigned to incident", incident_id=incident.id,
                assigned_count=len(selected), action_id=action.id)

    return {
        "assigned_resources": resource_details,
        "action_id": action.id,
        "priority_score": incident.priority_score,
        "message": f"{len(selected)} resources assigned to incident {incident.id}",
    }


def _resource_distance_km(resource: Resource, centroid_lat: float, centroid_lng: float) -> float:
    """
    Calculate distance in km between resource (lat/lng) and zone centroid
    using the haversine formula for accuracy.
    In production: PostGIS ST_Distance_Sphere for optimal performance.
    """
    from math import radians, sin, cos, sqrt, asin
    R = 6371.0  # Earth radius in km
    if resource.lat is None or resource.lng is None:
        return 50.0  # default fallback distance
    lat1 = radians(resource.lat)
    lat2 = radians(centroid_lat)
    dlng = radians(centroid_lng - resource.lng)
    a = sin((radians(centroid_lat) - radians(resource.lat)) / 2) ** 2 + \
        cos(lat1) * cos(lat2) * sin(dlng / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _math_haversine_approx(lat_diff: float, lng_diff: float) -> float:
    """Very approximate distance in km given lat/lng differences."""
    # Actually use proper haversine instead of the rough blend
    from math import radians, sin, cos, sqrt, asin
    R = 6371.0
    lat1 = 0.0
    lat2 = lat_diff
    lng1 = 0.0
    lng2 = lng_diff
    lat1_r = radians(lat1)
    lat2_r = radians(lat2)
    lng_diff_r = radians(lng2)
    a = sin((lat2_r - lat1_r) / 2) ** 2 + cos(lat1_r) * cos(lat2_r) * sin(lng_diff_r / 2) ** 2
    return 2 * R * asin(sqrt(a))