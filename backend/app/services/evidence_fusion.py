"""
Evidence fusion service (PRD §15) — deterministic multi-source bundling.

Inputs (all read-only, DB only — no network inside the scoring path):
    citizen reports · weather_readings · seismic_events · infrastructure ·
    predictions (when stored)

Output: a structured evidence bundle where every section carries
`available` + a human `reason` when data is missing (§7 — never fabricate),
plus an optional risk scalar for the decision engine's configurable 7th
factor (weight from settings.evidence_factor_weight, default 0.0 so the
PRD 6-factor contract stays byte-identical).

Also persists per-incident `evidence` rows (refresh semantics: replace
existing rows for the same incident+source) so XAI can attribute them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.external import Evidence
from app.models.infrastructure import Infrastructure
from app.models.report import Report
from app.models.seismic import SeismicEvent
from app.models.weather import WeatherReading
from app.models.zone import Zone
from app.services.route_intelligence import haversine_km

logger = structlog.get_logger()

# ── Deterministic tunables ────────────────────────────────────────────────
SEISMIC_WINDOW_HOURS = 24
SEISMIC_RADIUS_KM = 500.0
EXPOSURE_RADIUS_KM = 1.0
MAX_EXPOSURE_COUNT = 10.0       # 10 critical facilities within radius = max exposure
INFRA_BOX_LIMIT = 3000
WEATHER_WINDOW_MINUTES = 30
W_SEISMIC_PROXIMITY = 0.6       # external-risk blend (fused signals only)
W_INFRA_EXPOSURE = 0.4

# section name → (Evidence.source, Evidence.observation_type)
_SECTION_SOURCE = {
    "citizen_reports": ("citizen_reports", "corroboration"),
    "weather": ("open-meteo", "weather"),
    "seismic": ("usgs", "seismic"),
    "infrastructure": ("osm/overpass", "infrastructure"),
    "predictions": ("prediction_engine", "prediction"),
}

_CRITICAL_CATEGORIES = ("hospital", "clinic", "shelter")


class EvidenceFusionService:
    """Builds §15 evidence bundles and persists them as `evidence` rows."""

    async def build_bundle(
        self, zone_id: str, incident: Any, db: AsyncSession
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        zone = (
            await db.execute(select(Zone).where(Zone.id == zone_id))
        ).scalar_one_or_none()

        bundle: dict[str, Any] = {
            "incident_id": getattr(incident, "id", None),
            "zone_id": zone_id,
            "generated_at": now.isoformat(),
            "sections": {},
        }

        if zone is None:
            bundle["sections"] = {
                name: {"available": False, "reason": "zone not found", "confidence": 0.0}
                for name in _SECTION_SOURCE
            }
            bundle["aggregate"] = {
                "available_sections": 0,
                "mean_confidence": 0.0,
                "risk_signals": [],
                "external_raw": 0.0,
            }
            return bundle

        lat, lng = float(zone.centroid_lat), float(zone.centroid_lng)
        radius_m = float(zone.radius_meters or 500)

        seismic = self._seismic(lat, lng, now, await self._recent_seismic(now, db))
        sections = {
            "citizen_reports": await self._reports(zone_id, db),
            "weather": await self._weather(zone_id, now, db),
            "seismic": seismic,
            "infrastructure": await self._infrastructure(lat, lng, radius_m, db),
            "predictions": {
                "available": False,
                "reason": "no stored projection for zone",
                "confidence": 0.0,
            },
        }
        bundle["sections"] = sections

        bundle["aggregate"] = self._aggregate(sections)
        return bundle

    def external_factor(self, bundle: dict[str, Any]) -> tuple[float, str]:
        """(raw 0..1, human label) — the optional 7th-factor input."""
        agg = bundle.get("aggregate") or {}
        raw = float(agg.get("external_raw") or 0.0)
        signals = agg.get("risk_signals") or []
        if not signals:
            return 0.0, "no external risk signals available"
        return raw, "; ".join(signals)

    async def incident_attribution(
        self, incident_id: str, db: AsyncSession
    ) -> list[dict[str, Any]]:
        """§33 — provider + retrieved_at attribution rows for an incident's
        persisted evidence (used by narratives and /api/command/explain).
        Never raises; returns [] on failure."""
        try:
            rows = (
                await db.execute(
                    select(Evidence)
                    .where(Evidence.incident_id == incident_id)
                    .order_by(Evidence.retrieved_at.desc())
                    .limit(25)
                )
            ).scalars().all()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "evidence_attribution_failed",
                incident_id=incident_id,
                error=type(exc).__name__,
            )
            return []
        out: list[dict[str, Any]] = []
        for r in rows:
            section = next(iter((r.payload or {}).values()), {}) or {}
            out.append(
                {
                    "source": r.source,
                    "observation_type": r.observation_type,
                    "provider": section.get("provider") or r.source,
                    "confidence": float(r.confidence),
                    "retrieved_at": (
                        r.retrieved_at.isoformat() if r.retrieved_at else None
                    ),
                    "available": bool(section.get("available", True)),
                    "reason": section.get("reason"),
                }
            )
        return out

    async def persist_incident_evidence(
        self, incident_id: str, bundle: dict[str, Any], db: AsyncSession
    ) -> int:
        """Replace this incident's evidence rows for every available source.
        Flush-only (the caller's transaction owns the commit).
        Returns rows written. Never raises (fusion is enrichment, §7)."""
        try:
            written = 0
            retrieved = datetime.now(timezone.utc)
            for name, payload in (bundle.get("sections") or {}).items():
                if not payload.get("available"):
                    continue
                source, obs_type = _SECTION_SOURCE.get(name, (name, name))
                await db.execute(
                    delete(Evidence).where(
                        Evidence.incident_id == incident_id,
                        Evidence.source == source,
                    )
                )
                db.add(
                    Evidence(
                        id=str(uuid.uuid4()),
                        incident_id=incident_id,
                        source=source,
                        observation_type=obs_type,
                        payload={name: payload},
                        confidence=float(payload.get("confidence") or 1.0),
                        retrieved_at=retrieved,
                    )
                )
                written += 1
            await db.flush()
            return written
        except Exception as exc:  # noqa: BLE001 — must not break scoring
            logger.warning(
                "evidence_persist_failed",
                incident_id=incident_id,
                error=type(exc).__name__,
            )
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001
                pass
            return 0

    # ── Aggregate ─────────────────────────────────────────────────────────

    def _aggregate(self, sections: dict[str, dict[str, Any]]) -> dict[str, Any]:
        available = [s for s in sections.values() if s.get("available")]
        signals: list[str] = []

        proximity_risk = 0.0
        exposure = 0.0
        seismic_ok = bool(sections["seismic"].get("available"))
        infra_ok = bool(sections["infrastructure"].get("available"))
        if seismic_ok:
            proximity_risk = float(sections["seismic"].get("proximity_risk") or 0.0)
            signals.append(sections["seismic"]["signal"])
        if infra_ok:
            exposure = float(sections["infrastructure"].get("exposure") or 0.0)
            signals.append(sections["infrastructure"]["signal"])

        external_raw = 0.0
        if seismic_ok or infra_ok:
            external_raw = min(
                1.0,
                proximity_risk * W_SEISMIC_PROXIMITY + exposure * W_INFRA_EXPOSURE,
            )

        confidences = [float(s.get("confidence") or 0.0) for s in available]
        return {
            "available_sections": len(available),
            "mean_confidence": round(sum(confidences) / len(confidences), 3)
            if confidences
            else 0.0,
            "risk_signals": signals,
            "external_raw": round(external_raw, 3),
        }

    # ── Section builders ──────────────────────────────────────────────────

    async def _reports(self, zone_id: str, db: AsyncSession) -> dict[str, Any]:
        row = (
            await db.execute(
                select(
                    func.count(Report.id),
                    func.avg(Report.trust_score),
                    func.max(Report.created_at),
                ).where(and_(Report.zone_id == zone_id, Report.suppressed == False))  # noqa: E712
            )
        ).one()
        count = int(row[0] or 0)
        if count == 0:
            return {
                "available": False,
                "reason": "no corroborating reports",
                "confidence": 0.0,
            }
        avg_trust = round(float(row[1] or 0.0), 3)
        return {
            "available": True,
            "count": count,
            "avg_trust": avg_trust,
            "latest_at": row[2].isoformat() if row[2] else None,
            "signal": f"corroboration={count} reports (avg trust {avg_trust:.2f})",
            "confidence": avg_trust,
        }

    async def _weather(
        self, zone_id: str, now: datetime, db: AsyncSession
    ) -> dict[str, Any]:
        since = now - timedelta(minutes=WEATHER_WINDOW_MINUTES)
        w = (
            await db.execute(
                select(WeatherReading)
                .where(
                    and_(
                        WeatherReading.zone_id == zone_id,
                        WeatherReading.polled_at >= since,
                    )
                )
                .order_by(WeatherReading.polled_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if w is None:
            return {
                "available": False,
                "reason": "no weather reading in last "
                f"{WEATHER_WINDOW_MINUTES} minutes",
                "confidence": 0.0,
            }
        risk = float(w.risk_score or 0.0)
        return {
            "available": True,
            "source": "open-meteo",
            "rainfall_mm_hr": float(w.rainfall_mm_hr or 0.0),
            "wind_speed_kmh": float(w.wind_speed_kmh or 0.0),
            "temperature_c": float(w.temperature_c) if w.temperature_c is not None else None,
            "risk_score": risk,
            "weather_description": w.weather_description or "",
            "retrieved_at": w.polled_at.isoformat() if w.polled_at else None,
            "signal": f"weather risk {risk:.2f}",
            "confidence": 0.9,
        }

    async def _recent_seismic(self, now: datetime, db: AsyncSession) -> list[SeismicEvent]:
        since = now - timedelta(hours=SEISMIC_WINDOW_HOURS)
        rows = (
            await db.execute(
                select(SeismicEvent)
                .where(SeismicEvent.event_time >= since)
                .order_by(SeismicEvent.event_time.desc())
                .limit(100)
            )
        ).scalars().all()
        return list(rows)

    def _seismic(
        self, lat: float, lng: float, now: datetime, events: list[SeismicEvent]
    ) -> dict[str, Any]:
        nearest: SeismicEvent | None = None
        nearest_km = float("inf")
        for ev in events:
            d = haversine_km(lat, lng, ev.lat, ev.lng)
            if d < nearest_km:
                nearest, nearest_km = ev, d
        if nearest is None or nearest_km > SEISMIC_RADIUS_KM:
            return {
                "available": False,
                "reason": f"no seismic event within {SEISMIC_RADIUS_KM:.0f} km "
                f"in last {SEISMIC_WINDOW_HOURS} h",
                "confidence": 0.0,
            }
        risk = float(nearest.risk_score or 0.0)
        proximity_risk = risk * max(0.0, 1.0 - nearest_km / SEISMIC_RADIUS_KM)
        return {
            "available": True,
            "source": "usgs",
            "usgs_id": nearest.usgs_id,
            "magnitude": float(nearest.magnitude or 0.0),
            "place": nearest.place_description,
            "distance_km": round(nearest_km, 1),
            "risk_score": risk,
            "proximity_risk": round(proximity_risk, 3),
            "event_time": nearest.event_time.isoformat() if nearest.event_time else None,
            "signal": (
                f"seismic M{nearest.magnitude} at {nearest_km:.0f} km "
                f"(proximity risk {proximity_risk:.2f})"
            ),
            "confidence": 1.0,
        }

    async def _infrastructure(
        self, lat: float, lng: float, radius_m: float, db: AsyncSession
    ) -> dict[str, Any]:
        d_lat = (radius_m + EXPOSURE_RADIUS_KM * 1000.0) / 111_320.0
        cos_lat = max(0.01, __import__("math").cos(__import__("math").radians(lat)))
        d_lng = (radius_m + EXPOSURE_RADIUS_KM * 1000.0) / (111_320.0 * cos_lat)
        rows = (
            await db.execute(
                select(Infrastructure)
                .where(
                    Infrastructure.lat.between(lat - d_lat, lat + d_lat),
                    Infrastructure.lng.between(lng - d_lng, lng + d_lng),
                )
                .limit(INFRA_BOX_LIMIT)
            )
        ).scalars().all()
        if not rows:
            return {
                "available": False,
                "reason": "no cached GIS features for zone "
                "(refresh zone infrastructure)",
                "confidence": 0.0,
            }

        counts: dict[str, int] = {}
        critical = 0
        nearest_hospital: dict[str, Any] | None = None
        nearest_hospital_km = float("inf")
        for r in rows:
            counts[r.category] = counts.get(r.category, 0) + 1
            if r.category in _CRITICAL_CATEGORIES and haversine_km(
                lat, lng, r.lat, r.lng
            ) <= EXPOSURE_RADIUS_KM:
                critical += 1
            if r.category in ("hospital", "clinic"):
                d = haversine_km(lat, lng, r.lat, r.lng)
                if d < nearest_hospital_km:
                    nearest_hospital_km = d
                    nearest_hospital = {
                        "name": r.name,
                        "distance_km": round(d, 2),
                    }

        exposure = min(1.0, critical / MAX_EXPOSURE_COUNT)
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        return {
            "available": True,
            "source": "osm/overpass",
            "feature_count": len(rows),
            "counts": counts,
            "critical_within_km": critical,
            "exposure_radius_km": EXPOSURE_RADIUS_KM,
            "exposure": round(exposure, 3),
            "nearest_hospital": nearest_hospital,
            "signal": f"infrastructure exposure {exposure:.2f} ({summary})",
            "confidence": 1.0,
        }


# shared instance (score_zone calls this every scoring pass)
evidence_fusion = EvidenceFusionService()
