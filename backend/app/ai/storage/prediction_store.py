"""
Prediction Store — PostGIS-backed prediction persistence.

All geographic prediction results are stored with PostGIS geometry
for spatial querying. Predictions include:
- hazard_type, location, geometry
- time_horizon, risk_level, probability
- confidence, model_id, model_version
- source, source_timestamp, generated_at
- explanation, uncertainty, evidence

Predictions are spatially queryable:
    GET /api/predictions?lat=...&lon=...&radius=...
    GET /api/hazards/flood?bbox=...
    GET /api/risk/city/{city_id}
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


class PredictionStore:
    """PostGIS-backed prediction storage."""

    async def store_prediction(
        self,
        db: AsyncSession,
        *,
        hazard_type: str,
        lat: float,
        lng: float,
        time_horizon: str,
        risk_level: str,
        probability: float,
        confidence: float,
        model_id: str,
        model_version: str,
        source: str,
        source_timestamp: str | None = None,
        explanation: str = "",
        uncertainty: str = "",
        evidence: list[dict[str, Any]] | None = None,
        observed: bool = False,
        prediction: bool = True,
        resolution: str = "unknown",
        geometry: str | None = None,
    ) -> str:
        """Store a prediction with PostGIS geometry. Returns prediction_id."""
        prediction_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        try:
            await db.execute(
                text(
                    """
                    INSERT INTO predictions (
                        id, hazard_type, lat, lng, geometry,
                        time_horizon, risk_level, probability,
                        confidence, model_id, model_version,
                        source, source_timestamp, generated_at,
                        explanation, uncertainty, evidence,
                        observed, prediction, resolution,
                        valid_from, valid_until
                    ) VALUES (
                        :id, :hazard_type, :lat, :lng,
                        ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                        :time_horizon, :risk_level, :probability,
                        :confidence, :model_id, :model_version,
                        :source, :source_timestamp, :generated_at,
                        :explanation, :uncertainty, :evidence,
                        :observed, :prediction, :resolution,
                        :valid_from, :valid_until
                    )
                    """
                ),
                {
                    "id": prediction_id,
                    "hazard_type": hazard_type,
                    "lat": lat,
                    "lng": lng,
                    "time_horizon": time_horizon,
                    "risk_level": risk_level,
                    "probability": probability,
                    "confidence": confidence,
                    "model_id": model_id,
                    "model_version": model_version,
                    "source": source,
                    "source_timestamp": source_timestamp,
                    "generated_at": now.isoformat(),
                    "explanation": explanation,
                    "uncertainty": uncertainty,
                    "evidence": json.dumps(evidence or []),
                    "observed": observed,
                    "prediction": prediction,
                    "resolution": resolution,
                    "valid_from": now.isoformat(),
                    "valid_until": (now.replace(hour=now.hour + 24)).isoformat(),
                },
            )
            await db.flush()
            logger.info(
                "prediction_stored",
                prediction_id=prediction_id,
                hazard_type=hazard_type,
                risk_level=risk_level,
            )
            return prediction_id

        except Exception as exc:
            logger.warning("prediction_store_failed", error=str(exc))
            await db.rollback()
            raise

    async def get_predictions_near(
        self,
        db: AsyncSession,
        lat: float,
        lng: float,
        radius_km: float = 10.0,
        *,
        hazard_type: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get predictions near a point (PostGIS spatial query)."""
        try:
            query = text(
                """
                SELECT id, hazard_type, lat, lng,
                       time_horizon, risk_level, probability,
                       confidence, model_id, model_version,
                       source, generated_at, explanation,
                       uncertainty, evidence, observed, prediction,
                       resolution,
                       ST_Distance(
                           ST_MakePoint(lng, lat)::geography,
                           ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                       ) / 1000.0 AS distance_km
                FROM predictions
                WHERE ST_DWithin(
                    ST_MakePoint(lng, lat)::geography,
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                    :radius_m
                )
                {hazard_filter}
                ORDER BY distance_km ASC
                LIMIT :limit
                """
            )

            hazard_filter = "AND hazard_type = :hazard_type" if hazard_type else ""
            query = query.format(hazard_filter=hazard_filter)

            params: dict[str, Any] = {
                "lat": lat,
                "lng": lng,
                "radius_m": radius_km * 1000,
                "limit": limit,
            }
            if hazard_type:
                params["hazard_type"] = hazard_type

            result = await db.execute(query, params)
            rows = result.mappings().all()
            return [dict(r) for r in rows]

        except Exception as exc:
            logger.warning("prediction_query_failed", error=str(exc))
            return []

    async def get_predictions_by_bbox(
        self,
        db: AsyncSession,
        south: float,
        west: float,
        north: float,
        east: float,
        *,
        hazard_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get predictions within a bounding box."""
        try:
            query = text(
                """
                SELECT id, hazard_type, lat, lng,
                       time_horizon, risk_level, probability,
                       confidence, model_id, model_version,
                       source, generated_at, explanation,
                       uncertainty, evidence, observed, prediction,
                       resolution
                FROM predictions
                WHERE lat BETWEEN :south AND :north
                  AND lng BETWEEN :west AND :east
                {hazard_filter}
                ORDER BY generated_at DESC
                LIMIT :limit
                """
            )

            hazard_filter = "AND hazard_type = :hazard_type" if hazard_type else ""
            query = query.format(hazard_filter=hazard_filter)

            params: dict[str, Any] = {
                "south": south,
                "west": west,
                "north": north,
                "east": east,
                "limit": limit,
            }
            if hazard_type:
                params["hazard_type"] = hazard_type

            result = await db.execute(query, params)
            rows = result.mappings().all()
            return [dict(r) for r in rows]

        except Exception as exc:
            logger.warning("prediction_bbox_query_failed", error=str(exc))
            return []

    async def get_prediction_by_id(
        self,
        db: AsyncSession,
        prediction_id: str,
    ) -> dict[str, Any] | None:
        """Get a single prediction by ID."""
        try:
            result = await db.execute(
                text("SELECT * FROM predictions WHERE id = :id"),
                {"id": prediction_id},
            )
            row = result.mappings().first()
            return dict(row) if row else None
        except Exception as exc:
            logger.warning("prediction_get_failed", prediction_id=prediction_id, error=str(exc))
            return None


# Singleton
_store: PredictionStore | None = None


def get_prediction_store() -> PredictionStore:
    global _store
    if _store is None:
        _store = PredictionStore()
    return _store


import json  # noqa: E402 — used in store_prediction
