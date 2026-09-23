"""Heatmap data endpoints — Phase 4.

Provides grid-based heatmap data for dashboard visualization including:
- Priority score heatmap
- Victim density heatmap
- Trust score heatmap
- Disaster type heatmap

Heatmaps are computed from incident reports, victim counts,
and trust scores aggregated by zone.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.incident import Incident
from app.models.report import Report
from app.models.zone import Zone
from app.models.user import User


router = APIRouter(prefix="/api/heatmaps", tags=["heatmaps"])


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _grid_key(zone_id: str, disaster_type: str | None) -> str:
    """Create a stable grid identifier for heatmap cells."""
    return f"heatmap:{zone_id}:{disaster_type or 'all'}"


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/priority", tags=["heatmaps"])
async def heatmap_priority(
    zone_id: str | None = None,
    disaster_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Priority score heatmap — zones weighted by priority_score.

    Returns aggregated priority data grouped by zone.
    Higher priority scores indicate higher urgency for resource dispatch.
    """
    try:
        query = (
            select(Zone.id, Zone.name, Zone.centroid_lat, Zone.centroid_lng)
            .where(Zone.deleted == False)
        )

        if zone_id:
            query = query.where(Zone.id == zone_id)

        zones_result = await db.execute(query)
        zones = zones_result.all()

        # For each zone, get the latest priority from associated incidents
        result_cells: list[dict[str, Any]] = []
        for z in zones:
            zone_id_val = str(z.id)
            # Get latest active incident priority for this zone
            incident_result = await db.execute(
                select(Incident.priority_score)
                .where(Incident.zone_id == zone_id_val, Incident.status == "active")
                .order_by(Incident.polled_at.desc())
                .limit(1)
            )
            priority_row = incident_result.scalar_one_or_none()
            priority_score = float(priority_row) if priority_row else 0.0

            # Also check zone's stored priority_score
            zone_priority = float(z.priority_score) if z.priority_score else 0.0
            final_priority = max(priority_score, zone_priority)

            result_cells.append(
                {
                    "grid_id": _grid_key(zone_id_val, disaster_type),
                    "zone_id": zone_id_val,
                    "zone_name": z.name or zone_id_val,
                    "centroid_lat": float(z.centroid_lat or 0.0),
                    "centroid_lng": float(z.centroid_lng or 0.0),
                    "priority_score": round(final_priority, 1),
                    "disaster_type": disaster_type or (z.name or ""),
                }
            )

        return {
            "heatmap_type": "priority",
            "cells": result_cells,
            "grid_size": len(result_cells),
            "bounding_box": {
                "min_lat": min(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "max_lat": max(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "min_lng": min(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
                "max_lng": max(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
            },
        }

    except Exception as e:
        raise HTTPException(500, detail=f"Heatmap computation error: {str(e)}")


@router.get("/victim-density", tags=["heatmaps"])
async def heatmap_victim_density(
    zone_id: str | None = None,
    disaster_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Victim density heatmap — victims per grid cell.

    Returns victim count aggregated by zone, normalized by area
    where available, to produce a density score.
    """
    try:
        query = (
            select(Zone.id, Zone.name, Zone.centroid_lat, Zone.centroid_lng)
            .where(Zone.deleted == False)
        )

        if zone_id:
            query = query.where(Zone.id == zone_id)

        zones_result = await db.execute(query)
        zones = zones_result.all()

        result_cells: list[dict[str, Any]] = []
        for z in zones:
            zone_id_val = str(z.id)
            # Get victim count from associated incidents
            victim_result = await db.execute(
                select(func.count(Incident.id))
                .where(
                    Incident.zone_id == zone_id_val,
                    Incident.status == "active",
                    Incident.victim_count.isnot(None),
                )
            )
            total_victims = int(victim_result.scalar_one_or_none() or 0)

            # Estimate area from radius: area = π * r², r = radius_meters / 2
            area_km2 = 3.14159 * ((float(z.radius_meters or 500) / 2) / 1000) ** 2
            density = round(total_victims / max(area_km2, 0.01), 2)  # victims per km²

            result_cells.append(
                {
                    "grid_id": _grid_key(zone_id_val, disaster_type),
                    "zone_id": zone_id_val,
                    "zone_name": z.name or zone_id_val,
                    "centroid_lat": float(z.centroid_lat or 0.0),
                    "centroid_lng": float(z.centroid_lng or 0.0),
                    "victim_count": total_victims,
                    "area_km2": round(area_km2, 1),
                    "victim_density": density,
                    "disaster_type": disaster_type or (z.name or ""),
                }
            )

        return {
            "heatmap_type": "victim_density",
            "cells": result_cells,
            "grid_size": len(result_cells),
            "bounding_box": {
                "min_lat": min(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "max_lat": max(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "min_lng": min(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
                "max_lng": max(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
            },
        }

    except Exception as e:
        raise HTTPException(500, detail=f"Heatmap computation error: {str(e)}")


@router.get("/trust-score", tags=["heatmaps"])
async def heatmap_trust_score(
    zone_id: str | None = None,
    disaster_type: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Trust score heatmap — aggregated trust scores from reports.

    Returns the average trust score per zone, indicating
    the reliability/report quality of incident data.
    """
    try:
        query = (
            select(Zone.id, Zone.name, Zone.centroid_lat, Zone.centroid_lng)
            .where(Zone.deleted == False)
        )

        if zone_id:
            query = query.where(Zone.id == zone_id)

        zones_result = await db.execute(query)
        zones = zones_result.all()

        result_cells: list[dict[str, Any]] = []
        for z in zones:
            zone_id_val = str(z.id)
            # Get average trust score from reports in this zone
            trust_result = await db.execute(
                select(func.avg(Report.trust_score))
                .where(Report.zone_id == zone_id_val, Report.suppressed == False)
            )
            avg_trust = float(trust_result.scalar_one_or_none() or 0.0)

            result_cells.append(
                {
                    "grid_id": _grid_key(zone_id_val, disaster_type),
                    "zone_id": zone_id_val,
                    "zone_name": z.name or zone_id_val,
                    "centroid_lat": float(z.centroid_lat or 0.0),
                    "centroid_lng": float(z.centroid_lng or 0.0),
                    "average_trust_score": round(avg_trust, 2),
                    "report_count": 0,  # TODO: count reports per zone
                    "disaster_type": disaster_type or (z.name or ""),
                }
            )

        return {
            "heatmap_type": "trust_score",
            "cells": result_cells,
            "grid_size": len(result_cells),
            "bounding_box": {
                "min_lat": min(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "max_lat": max(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "min_lng": min(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
                "max_lng": max(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
            },
        }

    except Exception as e:
        raise HTTPException(500, detail=f"Heatmap computation error: {str(e)}")


@router.get("/disaster-type", tags=["heatmaps"])
async def heatmap_disaster_type(
    zone_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Disaster type heatmap — distribution of disaster types across zones.

    Returns counts of each disaster type (flood, fire, earthquake, etc.)
    per zone, useful for categorization and prioritization.
    """
    try:
        query = (
            select(Zone.id, Zone.name, Zone.centroid_lat, Zone.centroid_lng)
            .where(Zone.deleted == False)
        )

        if zone_id:
            query = query.where(Zone.id == zone_id)

        zones_result = await db.execute(query)
        zones = zones_result.all()

        # Count incidents by disaster type per zone
        result_cells: list[dict[str, Any]] = []
        for z in zones:
            zone_id_val = str(z.id)
            disaster_result = await db.execute(
                select(Incident.disaster_type, func.count(Incident.id))
                .where(Incident.zone_id == zone_id_val, Incident.status == "active")
                .group_by(Incident.disaster_type)
            )
            disaster_counts: dict[str, int] = {}
            total_incidents = 0
            for row in disaster_result:
                dt = row[0] or "unknown"
                count = int(row[1] or 0)
                disaster_counts[dt] = count
                total_incidents += count

            result_cells.append(
                {
                    "grid_id": _grid_key(zone_id_val, None),
                    "zone_id": zone_id_val,
                    "zone_name": z.name or zone_id_val,
                    "centroid_lat": float(z.centroid_lat or 0.0),
                    "centroid_lng": float(z.centroid_lng or 0.0),
                    "disaster_type_counts": disaster_counts,
                    "total_incidents": total_incidents,
                    "disaster_type": ", ".join(disaster_counts.keys())[:50]
                    if disaster_counts
                    else "none",
                }
            )

        return {
            "heatmap_type": "disaster_type",
            "cells": result_cells,
            "grid_size": len(result_cells),
            "bounding_box": {
                "min_lat": min(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "max_lat": max(c["centroid_lat"] for c in result_cells) if result_cells else 0.0,
                "min_lng": min(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
                "max_lng": max(c["centroid_lng"] for c in result_cells) if result_cells else 0.0,
            },
        }

    except Exception as e:
        raise HTTPException(500, detail=f"Heatmap computation error: {str(e)}")


@router.get("/combined", tags=["heatmaps"])
async def heatmap_combined(
    zone_id: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Combined heatmap — all metric types in one response.

    Returns priority, victim density, and trust score data
    for all zones in a single request, reducing API calls
    for dashboard initialization.
    """
    try:
        # Parallel queries for each metric
        priority_task = heatmap_priority(zone_id=zone_id, db=db)
        victim_task = heatmap_victim_density(zone_id=zone_id, db=db)
        trust_task = heatmap_trust_score(zone_id=zone_id, db=db)

        priority_data = await priority_task
        victim_data = await victim_task
        trust_data = await trust_task

        # Align cells by grid_id
        priority_cells = {c["grid_id"]: c for c in priority_data["cells"]}
        victim_cells = {c["grid_id"]: c for c in victim_data["cells"]}
        trust_cells = {c["grid_id"]: c for c in trust_data["cells"]}

        all_grid_ids = set(priority_cells.keys()) | set(victim_cells.keys()) | set(trust_cells.keys())

        combined_cells: list[dict[str, Any]] = []
        for gid in all_grid_ids:
            pc = priority_cells.get(gid, {})
            vc = victim_cells.get(gid, {})
            tc = trust_cells.get(gid, {})

            combined_cells.append(
                {
                    "grid_id": gid,
                    "zone_id": pc.get("zone_id", vc.get("zone_id", tc.get("zone_id", ""))),
                    "zone_name": pc.get("zone_name", vc.get("zone_name", tc.get("zone_name", ""))),
                    "priority_score": pc.get("priority_score"),
                    "victim_density": vc.get("victim_density"),
                    "average_trust_score": tc.get("average_trust_score"),
                    "disaster_type": pc.get("disaster_type"),
                }
            )

        return {
            "heatmap_type": "combined",
            "cells": combined_cells,
            "grid_size": len(combined_cells),
            "bounding_box": {
                "min_lat": min(
                    c.get("centroid_lat", 0.0) for c in combined_cells
                ),
                "max_lat": max(
                    c.get("centroid_lat", 0.0) for c in combined_cells
                ),
                "min_lng": min(
                    c.get("centroid_lng", 0.0) for c in combined_cells
                ),
                "max_lng": max(
                    c.get("centroid_lng", 0.0) for c in combined_cells
                ),
            },
        }

    except Exception as e:
        raise HTTPException(500, detail=f"Heatmap computation error: {str(e)}")