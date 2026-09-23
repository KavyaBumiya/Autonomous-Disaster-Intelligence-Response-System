"""
Decision Engine — Phase 1.
Weighted-sum priority scorer with auto-generated XAI reasoning string.
Upgraded from Phase 0: now fed real trust_score from Verification Agent.

Formula:
    priority_score =
        (report_count           * 2  )
      + (severity_score         * 0.4)
      + (weather_risk_score     * 15 )
      + (seismic_risk_score     * 20 )
      + (verification_confidence* 10 )
      + (population_density     * 5  )
    Clamped to [0, 100].

Actions with priority >= 60 are placed in pending_approval.
"""
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident
from app.models.report import Report
from app.models.weather import WeatherReading
from app.models.seismic import SeismicEvent
from app.models.action import Action

logger = structlog.get_logger()

PRIORITY_APPROVAL_THRESHOLD = 60.0

# Population density lookup — static GeoJSON proxy (simplified for MVP)
# Real implementation: PostGIS spatial join with population layer
POPULATION_DENSITY_LOOKUP: dict[str, float] = {
    "vadodara": 1.0,
    "alkapuri": 0.9,
    "fatehgunj": 0.85,
    "sayajigunj": 0.9,
    "manjalpur": 0.7,
}


def _population_factor(zone_name: str | None) -> float:
    if not zone_name:
        return 0.5
    lower = zone_name.lower()
    for key, val in POPULATION_DENSITY_LOOKUP.items():
        if key in lower:
            return val
    return 0.5


async def score_zone(zone_id: str, incident: Incident, db: AsyncSession) -> dict:
    """
    Compute priority score for a zone and generate XAI reasoning.
    Returns dict with priority_score, confidence, xai_reasoning, action_id.
    """
    # ── Gather inputs ─────────────────────────────────────────

    # Report count & avg trust score
    report_result = await db.execute(
        select(func.count(Report.id), func.avg(Report.trust_score)).where(
            and_(Report.zone_id == zone_id, Report.suppressed == False)
        )
    )
    row = report_result.one()
    report_count = int(row[0] or 0)
    avg_trust = float(row[1] or 0.0)

    # Latest weather
    since_weather = datetime.now(timezone.utc) - timedelta(minutes=10)
    w_result = await db.execute(
        select(WeatherReading).where(
            and_(WeatherReading.zone_id == zone_id, WeatherReading.polled_at >= since_weather)
        ).order_by(WeatherReading.polled_at.desc()).limit(1)
    )
    weather = w_result.scalar_one_or_none()
    weather_risk = weather.risk_score if weather else 0.0

    # Latest seismic
    since_seismic = datetime.now(timezone.utc) - timedelta(hours=1)
    s_result = await db.execute(
        select(SeismicEvent).where(
            SeismicEvent.event_time >= since_seismic
        ).order_by(SeismicEvent.magnitude.desc()).limit(1)
    )
    seismic = s_result.scalar_one_or_none()
    seismic_risk = seismic.risk_score if seismic else 0.0

    # Severity from Detection Agent (stored on incident)
    severity_score = float(incident.severity_score or 0.0)

    # Population density
    pop_factor = _population_factor(
        incident.zone.name if incident.zone else None
    )

    # ── Compute score ─────────────────────────────────────────
    raw_score = (
        report_count           * 2.0
        + severity_score       * 0.4
        + weather_risk         * 15.0
        + seismic_risk         * 20.0
        + avg_trust            * 10.0
        + pop_factor           * 5.0
    )
    priority_score = round(min(max(raw_score, 0.0), 100.0), 1)

    # ── XAI reasoning ─────────────────────────────────────────
    lines = [
        f"Zone — Priority Score: {priority_score}/100",
        f"• {report_count} verified reports (contributing +{round(report_count * 2, 1)})",
        f"• Severity score: {severity_score:.0f}/100 from Detection Agent "
        f"(contributing +{round(severity_score * 0.4, 1)})",
    ]
    if weather:
        lines.append(
            f"• Weather risk: {_weather_label(weather.rainfall_mm_hr, weather.wind_speed_kmh)} — "
            f"{weather.rainfall_mm_hr}mm/hr rainfall, {weather.wind_speed_kmh}km/h wind "
            f"(contributing +{round(weather_risk * 15, 1)})"
        )
    else:
        lines.append("• No recent weather data (contributing 0)")

    if seismic:
        lines.append(
            f"• Seismic event M{seismic.magnitude} detected "
            f"(contributing +{round(seismic_risk * 20, 1)})"
        )
    else:
        lines.append("• No seismic activity detected (contributing 0)")

    lines.append(
        f"• Report trust confidence: {avg_trust:.2f} average "
        f"(contributing +{round(avg_trust * 10, 1)})"
    )
    lines.append(
        f"• Population density: {_pop_label(pop_factor)} "
        f"(contributing +{round(pop_factor * 5, 1)})"
    )

    if priority_score >= PRIORITY_APPROVAL_THRESHOLD:
        lines.append(f"• Recommended action: Dispatch nearest available rescue unit.")
        lines.append(f"• Status: PENDING HUMAN APPROVAL")
    else:
        lines.append(f"• Status: MONITORING — below dispatch threshold ({PRIORITY_APPROVAL_THRESHOLD})")

    xai_reasoning = "\n".join(lines)

    # ── Create action if above threshold ─────────────────────
    if priority_score >= PRIORITY_APPROVAL_THRESHOLD:
        await _upsert_action(incident, zone_id, priority_score, xai_reasoning, db)

    confidence = round(min(0.5 + priority_score / 200.0, 0.97), 3)

    return {
        "priority_score": priority_score,
        "confidence": confidence,
        "xai_reasoning": xai_reasoning,
    }


async def _upsert_action(incident: Incident, zone_id: str, priority_score: float,
                          description: str, db: AsyncSession) -> None:
    """Create a pending_approval action if none exists for this incident."""
    existing = await db.execute(
        select(Action).where(
            and_(
                Action.incident_id == incident.id,
                Action.status == "pending_approval",
            )
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        return  # already has a pending action

    action = Action(
        id=str(uuid.uuid4()),
        incident_id=incident.id,
        zone_id=zone_id,
        action_type="dispatch",
        description=description,
        recommended_by="decision_engine",
        status="pending_approval",
        priority_score=priority_score,
    )
    db.add(action)


def _weather_label(rainfall: float, wind: float) -> str:
    if rainfall >= 100 or wind >= 120:
        return "CRITICAL"
    elif rainfall >= 50 or wind >= 80:
        return "HIGH"
    elif rainfall >= 20 or wind >= 40:
        return "MEDIUM"
    return "LOW"


def _pop_label(factor: float) -> str:
    if factor >= 0.8:
        return "HIGH"
    elif factor >= 0.5:
        return "MEDIUM"
    return "LOW"
