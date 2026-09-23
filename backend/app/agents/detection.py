"""
Detection Agent v0 — Phase 0 stub retained as-is.
Keyword-based disaster type classifier + weather/seismic cross-check.
Upgraded to transformer ensemble in Phase 2.
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentInput, AgentOutput
from app.models.report import Report
from app.models.weather import WeatherReading
from app.models.seismic import SeismicEvent

logger = structlog.get_logger()

DISASTER_KEYWORDS = {
    "flood": ["flood", "flooded", "flooding", "inundated", "waterlogged", "submerged"],
    "earthquake": ["earthquake", "quake", "tremor", "seismic", "aftershock"],
    "fire": ["fire", "blaze", "burning", "flames", "wildfire", "smoke"],
    "cyclone": ["cyclone", "hurricane", "typhoon", "storm", "tornado"],
    "landslide": ["landslide", "mudslide", "rockfall", "debris"],
}


async def run(agent_input: AgentInput, db: AsyncSession) -> AgentOutput:
    """
    Classify disaster type for the given incident/zone.
    Returns AgentOutput with disaster_type, severity_score, confidence.
    """
    report_ids = agent_input.report_ids
    zone_id = agent_input.zone_id

    # Load report texts
    result = await db.execute(
        select(Report).where(Report.id.in_(report_ids))
    )
    reports = result.scalars().all()

    combined_text = " ".join(
        (r.message_text or r.transcript or "") for r in reports
    ).lower()

    # Step 1: Keyword frequency counts
    type_scores: dict[str, int] = {}
    for dtype, keywords in DISASTER_KEYWORDS.items():
        count = sum(combined_text.count(kw) for kw in keywords)
        if count:
            type_scores[dtype] = count

    # Step 2: Weather cross-check (last 10 min)
    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    weather_result = await db.execute(
        select(WeatherReading).where(
            and_(WeatherReading.zone_id == zone_id, WeatherReading.polled_at >= since)
        ).order_by(WeatherReading.polled_at.desc()).limit(1)
    )
    latest_weather = weather_result.scalar_one_or_none()

    if latest_weather:
        if latest_weather.rainfall_mm_hr >= 50:
            type_scores["flood"] = type_scores.get("flood", 0) + 3
        if latest_weather.wind_speed_kmh >= 80:
            type_scores["cyclone"] = type_scores.get("cyclone", 0) + 3

    # Step 3: Seismic cross-check
    seismic_result = await db.execute(
        select(SeismicEvent).where(
            SeismicEvent.event_time >= datetime.now(timezone.utc) - timedelta(hours=1)
        ).order_by(SeismicEvent.magnitude.desc()).limit(1)
    )
    latest_seismic = seismic_result.scalar_one_or_none()

    if latest_seismic and latest_seismic.magnitude >= 4.5:
        type_scores["earthquake"] = type_scores.get("earthquake", 0) + 5

    if not type_scores:
        disaster_type = "unknown"
        confidence = 0.3
        severity_score = 10.0
    else:
        disaster_type = max(type_scores, key=type_scores.get)
        total = sum(type_scores.values())
        confidence = round(min(type_scores[disaster_type] / max(total, 1) + 0.3, 0.92), 3)
        severity_score = min(len(reports) * 5 + type_scores[disaster_type] * 3, 100)

    reasoning_parts = [
        f"Classification: {disaster_type} (confidence {confidence}).",
        f"Based on: {len(reports)} reports.",
    ]
    if latest_weather:
        reasoning_parts.append(
            f"Rainfall {latest_weather.rainfall_mm_hr}mm/hr, wind {latest_weather.wind_speed_kmh}km/h."
        )
    if latest_seismic and latest_seismic.magnitude >= 4.5:
        reasoning_parts.append(
            f"Seismic event M{latest_seismic.magnitude} detected within 1h."
        )

    return AgentOutput(
        agent_name="detection_agent_v0",
        incident_id=agent_input.incident_id,
        output_type="classification",
        payload={
            "disaster_type": disaster_type,
            "severity_score": round(severity_score, 1),
            "type_scores": type_scores,
        },
        confidence=confidence,
        reasoning=" ".join(reasoning_parts),
    )
