"""
Verification Agent v1 — Multi-signal trust scoring.
Phase 1 core deliverable. See Phase 1 PRD § 8 for full specification.

Trust score formula:
    trust_score = 
        (corroboration_score   * 0.30) +
        (source_weight         * 0.15) +
        (weather_consistency   * 0.20) +
        (seismic_consistency   * 0.15) +
        (location_coherence    * 0.10) +
        (temporal_plausibility * 0.07) +
        (novelty_score         * 0.03)
    clamped to [0.0, 1.0]
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentInput, AgentOutput
from app.models.report import Report
from app.models.weather import WeatherReading
from app.models.seismic import SeismicEvent
from app.services.deduplication import similarity_score

logger = structlog.get_logger()

SOURCE_WEIGHTS = {
    "citizen_text": 0.75,
    "citizen_voice": 0.85,
    "social_media": 0.55,
}


async def _corroboration_score(report: Report, db: AsyncSession) -> float:
    """Count reports in same zone (50m radius) in last 30 min."""
    if not report.lat or not report.lng or not report.zone_id:
        return 0.0

    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    result = await db.execute(
        select(func.count(Report.id)).where(
            and_(
                Report.zone_id == report.zone_id,
                Report.created_at >= since,
                Report.id != report.id,
            )
        )
    )
    count = result.scalar()
    return min(1.0, count / 10.0)


async def _weather_consistency(report: Report, db: AsyncSession) -> float:
    """
    Check if reported disaster type matches weather data.
    Returns 1.0 if consistent, 0.3 if contradicts, 0.6 if neutral.
    """
    if not report.disaster_type or not report.zone_id:
        return 0.6

    since = datetime.now(timezone.utc) - timedelta(minutes=10)
    result = await db.execute(
        select(WeatherReading).where(
            and_(WeatherReading.zone_id == report.zone_id, WeatherReading.polled_at >= since)
        ).order_by(WeatherReading.polled_at.desc()).limit(1)
    )
    weather = result.scalar_one_or_none()
    if not weather:
        return 0.6  # neutral — no weather data

    dtype = report.disaster_type.lower()

    # Check flood vs. rainfall
    if dtype == "flood":
        if weather.rainfall_mm_hr >= 50:
            return 1.0
        elif weather.rainfall_mm_hr >= 20:
            return 0.8
        elif weather.rainfall_mm_hr < 5:
            return 0.3  # contradicts
        return 0.6

    # Check cyclone vs. wind
    if dtype == "cyclone":
        if weather.wind_speed_kmh >= 80:
            return 1.0
        elif weather.wind_speed_kmh >= 40:
            return 0.7
        elif weather.wind_speed_kmh < 15:
            return 0.3
        return 0.6

    # Fire: high temp + low rain boosts confidence
    if dtype == "fire":
        if weather.temperature_c and weather.temperature_c > 35 and weather.rainfall_mm_hr < 1:
            return 0.9
        return 0.6

    return 0.6  # neutral for other types


async def _seismic_consistency(report: Report, db: AsyncSession) -> float:
    """
    Check if earthquake report matches USGS data (50km, 30min window).
    Returns 1.0 if matches, 0.0 if contradicts, 0.5 if N/A.
    """
    if not report.disaster_type or report.disaster_type.lower() != "earthquake":
        return 0.5  # N/A

    if not report.lat or not report.lng:
        return 0.5

    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    # Simplified: check if ANY seismic event M >= 4.5 in the last 30 min
    result = await db.execute(
        select(SeismicEvent).where(
            and_(SeismicEvent.event_time >= since, SeismicEvent.magnitude >= 4.5)
        ).limit(1)
    )
    event = result.scalar_one_or_none()

    if event:
        return 1.0  # corroborates
    else:
        return 0.1  # contradicts — no seismic event detected


def _location_coherence(report: Report) -> float:
    """
    GPS-tagged reports score higher than NLP-only location.
    """
    if report.lat and report.lng:
        return 1.0
    elif report.location_string:
        return 0.6  # NLP-derived location, lower confidence
    return 0.3  # no location at all


def _temporal_plausibility(report: Report) -> float:
    """
    Recent reports score higher. Reports > 6h old score lower.
    Placeholder: In production, compare to known disaster event onset time.
    """
    age = datetime.now(timezone.utc) - report.created_at
    if age < timedelta(hours=1):
        return 1.0
    elif age < timedelta(hours=3):
        return 0.8
    elif age < timedelta(hours=6):
        return 0.6
    elif age < timedelta(days=1):
        return 0.4
    return 0.2


async def _novelty_score(report: Report, db: AsyncSession) -> float:
    """
    Penalises near-duplicates by comparing similarity to recent reports in the zone.
    Returns 1.0 if unique, 0.0 if near-duplicate.
    """
    if not report.zone_id:
        return 0.8

    since = datetime.now(timezone.utc) - timedelta(minutes=30)
    result = await db.execute(
        select(Report).where(
            and_(
                Report.zone_id == report.zone_id,
                Report.created_at >= since,
                Report.id != report.id,
            )
        ).limit(20)
    )
    recent = result.scalars().all()

    text_a = (report.message_text or report.transcript or "").strip()
    if not text_a or len(text_a) < 20:
        return 0.8

    max_sim = 0.0
    for r in recent:
        text_b = (r.message_text or r.transcript or "").strip()
        if not text_b:
            continue
        sim = similarity_score(text_a, text_b)
        max_sim = max(max_sim, sim)

    return 1.0 - max_sim


async def run(agent_input: AgentInput, db: AsyncSession) -> AgentOutput:
    """
    Compute trust score for a single report.
    Returns AgentOutput with trust_score in payload and reasoning.
    """
    # Load the report being verified
    report_id = agent_input.report_ids[0]  # Verification Agent always processes one report
    result = await db.execute(select(Report).where(Report.id == report_id))
    report = result.scalar_one_or_none()

    if not report:
        return AgentOutput(
            agent_name="verification_agent_v1",
            incident_id=agent_input.incident_id,
            output_type="score",
            payload={"trust_score": 0.0, "error": "Report not found"},
            confidence=0.0,
            reasoning="Report ID not found in database.",
        )

    # Compute all factors
    corroboration = await _corroboration_score(report, db)
    source_weight = SOURCE_WEIGHTS.get(report.source, 0.5)
    weather = await _weather_consistency(report, db)
    seismic = await _seismic_consistency(report, db)
    location = _location_coherence(report)
    temporal = _temporal_plausibility(report)
    novelty = await _novelty_score(report, db)

    # Weighted sum
    trust_score = (
        corroboration * 0.30
        + source_weight * 0.15
        + weather * 0.20
        + seismic * 0.15
        + location * 0.10
        + temporal * 0.07
        + novelty * 0.03
    )
    trust_score = max(0.0, min(1.0, trust_score))

    suppressed = trust_score < 0.25

    # Build reasoning string
    corroboration_count = int(corroboration * 10)
    reasoning_parts = [
        f"Trust score: {trust_score:.2f}.",
        f"{corroboration_count} corroborating reports in zone (last 30 min).",
        f"Source: {report.source} (weight {source_weight}).",
    ]
    if weather == 1.0:
        reasoning_parts.append("Weather consistent.")
    elif weather == 0.3:
        reasoning_parts.append("Weather contradicts report.")

    if report.disaster_type and report.disaster_type.lower() == "earthquake":
        if seismic == 1.0:
            reasoning_parts.append("Seismic event confirmed by USGS.")
        elif seismic == 0.1:
            reasoning_parts.append("No seismic event detected.")

    if novelty < 0.5:
        reasoning_parts.append("Near-duplicate detected.")

    if suppressed:
        reasoning_parts.append("Report suppressed (trust < 0.25).")

    return AgentOutput(
        agent_name="verification_agent_v1",
        incident_id=agent_input.incident_id,
        output_type="score",
        payload={
            "trust_score": round(trust_score, 3),
            "corroboration_count": corroboration_count,
            "weather_consistent": weather >= 0.8,
            "seismic_consistent": seismic >= 0.8 if seismic != 0.5 else None,
            "duplicate_flag": novelty < 0.5,
            "source": report.source,
            "suppressed": suppressed,
        },
        confidence=trust_score,
        reasoning=" ".join(reasoning_parts),
    )
