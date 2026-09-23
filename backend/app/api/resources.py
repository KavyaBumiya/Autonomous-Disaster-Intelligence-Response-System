"""Resource management endpoints — Phase 3.
Handles resource registration, status updates, and commander-led assignment
to incidents.
"""
from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import require_role, get_current_user
from app.core.database import get_db
from app.models.resource import Resource
from app.models.incident import Incident
from app.engine.resource_commander import command_resources

router = APIRouter()


@router.get("", tags=["resources"])
async def list_resources(
    resource_type: str | None = Query(None, regex="^(team|vehicle|supply|shelter)$"),
    zone_id: str | None = Query(None),
    available: bool | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
):
    """List resources with optional filtering."""
    q = select(Resource)
    filters = []

    if resource_type:
        filters.append(Resource.resource_type == resource_type)
    if zone_id:
        filters.append(Resource.assigned_zone_id == zone_id)
    if available is not None:
        filters.append(Resource.available == available)

    if filters:
        q = q.where(and_(*filters))

    result = await db.execute(q.order_by(Resource.name))
    resources = result.scalars().all()

    return {
        "resources": [
            {
                "resource_id": r.id,
                "name": r.name,
                "resource_type": r.resource_type,
                "capacity": r.capacity,
                "current_load": r.current_load,
                "available": r.available,
                "lat": r.lat,
                "lng": r.lng,
                "assigned_zone_id": r.assigned_zone_id,
            }
            for r in resources
        ],
        "total": len(resources),
    }


@router.post("", status_code=201, tags=["resources"])
async def register_resource(
    name: str = Form(...),
    resource_type: str = Form(..., regex="^(team|vehicle|supply|shelter)$"),
    capacity: int = Form(default=1),
    lat: float | None = Form(default=None),
    lng: float | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(["commander"])),
):
    """Register a new rescue resource (team, vehicle, supply depot, shelter)."""
    rid = str(uuid.uuid4())
    resource = Resource(
        id=rid,
        name=name,
        resource_type=resource_type,
        capacity=capacity,
        current_load=0,
        available=True,
        lat=lat,
        lng=lng,
        assigned_zone_id=None,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)

    return {
        "resource_id": resource.id,
        "name": resource.name,
        "resource_type": resource.resource_type,
        "capacity": resource.capacity,
        "current_load": resource.current_load,
        "available": resource.available,
        "message": f"Resource '{name}' registered successfully",
    }


@router.post("/{incident_id}/assign-resources", tags=["resources"])
async def assign_resources_to_incident(
    incident_id: str,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(["commander"])),
):
    """Resource commander assigns available resources to an incident."""
    # Load incident
    result = await db.execute(select(Incident).where(Incident.id == incident_id))
    incident = result.scalar_one_or_none()
    if not incident:
        raise HTTPException(404, detail="Incident not found")

    # Run resource commander allocation
    result = await command_resources(incident, db)
    await db.commit()

    return {
        "incident_id": incident.id,
        "assigned_resources": result["assigned_resources"],
        "action_id": result["action_id"],
        "priority_score": incident.priority_score,
        "message": result["message"],
    }


@router.put("/{resource_id}", tags=["resources"])
async def update_resource(
    resource_id: str,
    available: bool | None = None,
    current_load: int | None = None,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_role(["commander"])),
):
    """Update resource status (available/load) — commander only."""
    result = await db.execute(select(Resource).where(Resource.id == resource_id))
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(404, detail="Resource not found")

    if available is not None:
        resource.available = available
    if current_load is not None:
        resource.current_load = max(0, min(resource.capacity, current_load))

    resource.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(resource)

    return {
        "resource_id": resource.id,
        "name": resource.name,
        "available": resource.available,
        "current_load": resource.current_load,
        "message": f"Resource '{resource.name}' updated successfully",
    }