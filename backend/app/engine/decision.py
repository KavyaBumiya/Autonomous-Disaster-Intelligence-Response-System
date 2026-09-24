"""
AEGIS-AI — Deterministic Decision Engine
=========================================
PRD §6: Priority formula (weights sum to 100%):

    Priority =
        30%  Victim Severity       (victim_count × severity_score)
      + 20%  Number of People      (report_count corroborating)
      + 15%  Infrastructure Risk   (weather risk + road closure signal)
      + 15%  Hazard Severity       (Detection Agent severity_score)
      + 10%  Time Sensitivity      (age of incident — newer = more urgent)
      + 10%  Prediction Risk       (seismic + flood/fire spread signal)

    Clamped to [0, 100].

Configurable thresholds (PRD §6):
    0–39   Low
    40–69  Medium
    70–84  High
    85–100 Critical

Actions pending commander approval are created when priority ≥ APPROVAL_THRESHOLD.

ARCHITECTURE CONSTRAINT:
  The LLM MUST NOT modify, override, or substitute this calculation.
  The engine receives structured evidence and produces the score deterministically.
  Groq may EXPLAIN the output but never generate the number.
"""
from __future__ import annotations

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

# ── Configurable thresholds ───────────────────────────────────────────────
APPROVAL_THRESHOLD = 70.0    # priority ≥ this → pending_approval action created

THRESHOLDS = {
    "critical": 85.0,
    "high":     70.0,
    "medium":   40.0,
    "low":      0.0,
}

# ── PRD-aligned factor weights (must sum to 1.0) ─────────────────────────
W_VICTIM_SEVERITY    = 0.30   # 30% — victim count × normalised severity
W_PEOPLE             = 0.20   # 20% — corroborating report count signal
W_INFRA_RISK         = 0.15   # 15% — weather risk (proxy for infra impact)
W_HAZARD_SEVERITY    = 0.15   # 15% — Detection Agent severity score
W_TIME_SENSITIVITY   = 0.10   # 10% — recency of first report
W_PREDICTION_RISK    = 0.10   # 10% — seismic + secondary hazard signal

# normalisation denominators (max expected raw values → 1.0)
_MAX_VICTIM_SCORE   = 100.0   # victim_count × severity normalised to this
_MAX_REPORT_SIGNAL  = 20.0    # 20+ corroborating reports = maximum signal
_MAX_AGE_HOURS      = 24.0    # incidents > 24h old lose time-sensitivity weight

# ── Static population density lookup (Vadodara neighbourhoods) ───────────
_POPULATION_DENSITY: dict[str, float] = {
    "vadodara":   1.0,
    "alkapuri":   0.9,
    "fatehgunj":  0.85,
    "sayajigunj": 0.9,
    "manjalpur":  0.7,
    "karelibaug": 0.8,
    "gorwa":      0.65,
    "harni":      0.6,
}


def _population_factor(zone_name: str | None) -> float:
    if not zone_name:
        return 0.5
    lower = zone_name.lower()
    for key, val in _POPULATION_DENSITY.items():
        if key in lower:
            return val
    return 0.5


def priority_band(score: float) -> str:
    if score >= THRESHOLDS["critical"]:
        return "CRITICAL"
    if score >= THRESHOLDS["high"]:
        return "HIGH"
    if score >= THRESHOLDS["medium"]:
        return "MEDIUM"
    return "LOW"


# ── Main scoring function ─────────────────────────────────────────────────

async def score_zone(zone_id: str, incident: Incident, db: AsyncSession) -> dict:
    """
    Deterministically compute the priority score for a zone/incident.

    Returns a dict with:
        priority_score  – float [0, 100]
        confidence      – float [0, 0.97]
        xai_reasoning   – structured evidence string
        priority_band   – LOW / MEDIUM / HIGH / CRITICAL
        factor_values   – dict of raw factor inputs (for XAI)
    """

    # ── 1. Victim severity factor ────────────────────────────────────────
    #  Uses incident.victim_count (from CV agent) × severity_score (from detection)
    victim_count   = int(incident.victim_count or 0)
    severity_score = float(incident.severity_score or 0.0)   # 0–100 from Detection Agent
    # Normalise: (victim_count * severity) / max_victim_score
    # A single confirmed victim at max severity = 1.0; scales linearly up to cap
    victim_raw     = min(1.0, (victim_count * (severity_score / 100.0) * 20.0) / _MAX_VICTIM_SCORE)
    victim_contrib = W_VICTIM_SEVERITY * victim_raw * 100.0

    # ── 2. People / report corroboration ────────────────────────────────
    rpt_result = await db.execute(
        select(func.count(Report.id), func.avg(Report.trust_score)).where(
            and_(Report.zone_id == zone_id, Report.suppressed == False)
        )
    )
    row          = rpt_result.one()
    report_count = int(row[0] or 0)
    avg_trust    = float(row[1] or 0.0)

    # Weighted by trust score so that high-trust reports count more
    people_raw    = min(1.0, (report_count * avg_trust) / _MAX_REPORT_SIGNAL)
    people_contrib = W_PEOPLE * people_raw * 100.0

    # ── 3. Infrastructure risk (weather proxy) ───────────────────────────
    since_weather = datetime.now(timezone.utc) - timedelta(minutes=30)
    w_result      = await db.execute(
        select(WeatherReading).where(
            and_(
                WeatherReading.zone_id == zone_id,
                WeatherReading.polled_at >= since_weather,
            )
        ).order_by(WeatherReading.polled_at.desc()).limit(1)
    )
    weather      = w_result.scalar_one_or_none()
    weather_risk = weather.risk_score if weather else 0.0
    infra_contrib = W_INFRA_RISK * weather_risk * 100.0

    # ── 4. Hazard severity (Detection Agent) ────────────────────────────
    hazard_contrib = W_HAZARD_SEVERITY * (severity_score / 100.0) * 100.0

    # ── 5. Time sensitivity ──────────────────────────────────────────────
    #  Newer incidents are more time-sensitive.
    #  Decays linearly: 1.0 at t=0, 0.0 at t=24h.
    now        = datetime.now(timezone.utc)
    created_at = incident.created_at
    if created_at and created_at.tzinfo is None:
        from datetime import timezone as tz
        created_at = created_at.replace(tzinfo=tz.utc)

    age_hours      = min(_MAX_AGE_HOURS, (now - created_at).total_seconds() / 3600.0) if created_at else _MAX_AGE_HOURS
    time_raw       = max(0.0, 1.0 - age_hours / _MAX_AGE_HOURS)
    time_contrib   = W_TIME_SENSITIVITY * time_raw * 100.0

    # ── 6. Prediction risk (seismic + secondary hazards) ────────────────
    since_seismic = datetime.now(timezone.utc) - timedelta(hours=2)
    s_result      = await db.execute(
        select(SeismicEvent).where(
            SeismicEvent.event_time >= since_seismic
        ).order_by(SeismicEvent.magnitude.desc()).limit(1)
    )
    seismic      = s_result.scalar_one_or_none()
    seismic_risk = seismic.risk_score if seismic else 0.0
    # Combined prediction signal: seismic + weather amplification
    prediction_raw   = min(1.0, seismic_risk * 0.6 + weather_risk * 0.4)
    predict_contrib  = W_PREDICTION_RISK * prediction_raw * 100.0

    # ── Compute final score ──────────────────────────────────────────────
    raw_score      = (
        victim_contrib
        + people_contrib
        + infra_contrib
        + hazard_contrib
        + time_contrib
        + predict_contrib
    )
    priority_score = round(min(max(raw_score, 0.0), 100.0), 1)
    band           = priority_band(priority_score)
    confidence     = round(min(0.97, 0.40 + priority_score / 200.0), 3)

    # ── Population density modifier (informational, not in score) ────────
    pop_factor = _population_factor(incident.zone.name if incident.zone else None)

    # ── Build XAI reasoning ──────────────────────────────────────────────
    factor_values = {
        "victim_count":      victim_count,
        "severity_score":    severity_score,
        "victim_raw":        round(victim_raw, 3),
        "report_count":      report_count,
        "avg_trust":         round(avg_trust, 3),
        "people_raw":        round(people_raw, 3),
        "weather_risk":      round(weather_risk, 3),
        "hazard_severity":   severity_score,
        "age_hours":         round(age_hours, 1),
        "time_raw":          round(time_raw, 3),
        "seismic_risk":      round(seismic_risk, 3),
        "prediction_raw":    round(prediction_raw, 3),
        "pop_factor":        round(pop_factor, 2),
    }

    lines = [
        f"PRIORITY SCORE: {priority_score}/100  [{band}]",
        f"Confidence: {confidence:.0%}",
        "",
        "FACTOR BREAKDOWN (PRD §6 formula):",
        f"  [30%] Victim Severity    {victim_contrib:>5.1f} pts  "
        f"({victim_count} victims, severity {severity_score:.0f}/100)",
        f"  [20%] People/Corroboration {people_contrib:>4.1f} pts  "
        f"({report_count} reports, avg trust {avg_trust:.2f})",
        f"  [15%] Infrastructure Risk  {infra_contrib:>4.1f} pts  "
        f"(weather risk {weather_risk:.2f}{'  — ' + weather.weather_description if weather and weather.weather_description else ''})",
        f"  [15%] Hazard Severity    {hazard_contrib:>5.1f} pts  "
        f"(Detection Agent: {severity_score:.0f}/100)",
        f"  [10%] Time Sensitivity   {time_contrib:>5.1f} pts  "
        f"(incident age {age_hours:.1f}h)",
        f"  [10%] Prediction Risk    {predict_contrib:>5.1f} pts  "
        f"(seismic {seismic_risk:.2f}, weather {weather_risk:.2f})",
        "",
        "ENVIRONMENTAL SIGNALS:",
    ]

    if weather:
        lines.append(
            f"  Weather: {weather.rainfall_mm_hr}mm/hr rainfall, "
            f"{weather.wind_speed_kmh}km/h wind  [{_weather_label(weather.rainfall_mm_hr, weather.wind_speed_kmh)}]"
        )
    else:
        lines.append("  Weather: No recent data")

    if seismic:
        lines.append(f"  Seismic: M{seismic.magnitude} event detected {seismic.place_description or ''}")
    else:
        lines.append("  Seismic: No recent activity")

    lines.append(f"  Population density: {_pop_label(pop_factor)} ({pop_factor:.0%})")
    lines.append(f"  Disaster type: {incident.disaster_type or 'unclassified'}")
    lines.append("")

    if priority_score >= APPROVAL_THRESHOLD:
        lines.append(f"► RECOMMENDED ACTION: Dispatch nearest available rescue unit.")
        lines.append(f"► STATUS: PENDING HUMAN APPROVAL")
    else:
        lines.append(f"► STATUS: MONITORING — below dispatch threshold ({APPROVAL_THRESHOLD})")

    xai_reasoning = "\n".join(lines)

    # ── Create action if above approval threshold ────────────────────────
    if priority_score >= APPROVAL_THRESHOLD:
        await _upsert_action(incident, zone_id, priority_score, xai_reasoning, db)

    return {
        "priority_score": priority_score,
        "confidence":     confidence,
        "xai_reasoning":  xai_reasoning,
        "priority_band":  band,
        "factor_values":  factor_values,
    }


async def _upsert_action(
    incident: Incident,
    zone_id: str,
    priority_score: float,
    description: str,
    db: AsyncSession,
) -> None:
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
        return

    action = Action(
        id=str(uuid.uuid4()),
        incident_id=incident.id,
        zone_id=zone_id,
        action_type="dispatch",
        description=description,
        recommended_by="decision_engine_v2",
        status="pending_approval",
        priority_score=priority_score,
    )
    db.add(action)
    logger.info(
        "action_created",
        incident_id=incident.id,
        priority=priority_score,
        band=priority_band(priority_score),
    )


# ── Label helpers ─────────────────────────────────────────────────────────

def _weather_label(rainfall: float, wind: float) -> str:
    if rainfall >= 100 or wind >= 120:
        return "CRITICAL"
    if rainfall >= 50 or wind >= 80:
        return "HIGH"
    if rainfall >= 20 or wind >= 40:
        return "MEDIUM"
    return "LOW"


def _pop_label(factor: float) -> str:
    if factor >= 0.8:
        return "HIGH"
    if factor >= 0.5:
        return "MEDIUM"
    return "LOW"
