"""
Rule-based flood risk analysis from IoT telemetry.

This is deliberately NOT an ML model. It applies fixed thresholds to observed
water level and flow velocity and returns a structured risk assessment. The
thresholds mirror the frontend's own banding (simulation.ts) so the backend
and frontend agree on what "warning" and "critical" mean.

Every output distinguishes OBSERVED TELEMETRY from RULE-BASED ALERT. No
confidence is produced because none is calculated — a threshold crossing is a
deterministic observation, not a probabilistic claim.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Thresholds in metres, matching frontend/src/lib/flood/simulation.ts
# Water level is measured as distance from ultrasonic sensor to water surface.
# Lower distance = higher water level (inverse relationship).
# > 60 mm = NORMAL, 30-60 mm = MEDIUM, 20-30 mm = HIGH, <= 20 mm = CRITICAL
WATER_LEVEL_LOW_M = 0.06
WATER_LEVEL_MEDIUM_M = 0.03
WATER_LEVEL_HIGH_M = 0.02
WATER_LEVEL_CRITICAL_M = 0.02

# Thresholds in m/s, matching frontend/src/lib/flood/simulation.ts
# < 1.0 = LOW, 1.0-1.99 = MEDIUM, 2.0-2.99 = HIGH, >= 3.0 = CRITICAL
FLOW_VELOCITY_LOW_MS = 1.0
FLOW_VELOCITY_MEDIUM_MS = 2.0
FLOW_VELOCITY_HIGH_MS = 2.0
FLOW_VELOCITY_CRITICAL_MS = 3.0

# A device that has not reported for this long is considered stale, and its
# last reading must not be presented as a current observation.
DEVICE_STALE_AFTER_MINUTES = 30.0


@dataclass
class FloodRiskAssessment:
    """Structured result of applying flood thresholds to one reading."""

    risk_level: str          # "NORMAL" | "WARNING" | "CRITICAL"
    risk_score: float         # 0.0 - 1.0, the max normalised band severity
    basis: list[str] = field(default_factory=list)
    water_level_band: str = "LOW"
    flow_velocity_band: str = "LOW"
    observed: dict = field(default_factory=dict)
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "risk_score": self.risk_score,
            "basis": self.basis,
            "water_level_band": self.water_level_band,
            "flow_velocity_band": self.flow_velocity_band,
            "observed": self.observed,
            "generated_at": self.generated_at,
            "model": "rule_based_thresholds",
            "model_version": "v1",
        }


def _band(value: float, low: float, medium: float, high: float, critical: float, *, inverse: bool = False) -> tuple[str, int]:
    """Return (band_name, severity 0-3) for a value against four thresholds.

    When inverse=True, lower values are more dangerous (e.g. distance from
    ultrasonic sensor to water surface).
    """
    if inverse:
        if value <= critical:
            return "CRITICAL", 3
        if value <= high:
            return "HIGH", 2
        if value <= medium:
            return "MEDIUM", 1
        if value <= low:
            return "LOW", 0
        return "LOW", 0
    if value >= critical:
        return "CRITICAL", 3
    if value >= high:
        return "HIGH", 2
    if value >= medium:
        return "MEDIUM", 1
    if value >= low:
        return "LOW", 0
    return "LOW", 0


def assess_flood_risk(
    *,
    water_level_m: float,
    flow_velocity_ms: float,
    device_timestamp: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
) -> FloodRiskAssessment:
    """Apply flood thresholds to one telemetry reading.

    The risk level is the MORE SEVERE of the two bands. The score is the max
    normalised severity (0.0, 0.33, 0.67, 1.0) so it can be compared across
    readings without implying a probability.
    """
    from datetime import datetime, timezone

    wl_band, wl_sev = _band(
        water_level_m, WATER_LEVEL_LOW_M, WATER_LEVEL_MEDIUM_M, WATER_LEVEL_HIGH_M, WATER_LEVEL_CRITICAL_M, inverse=True
    )
    fv_band, fv_sev = _band(
        flow_velocity_ms, FLOW_VELOCITY_LOW_MS, FLOW_VELOCITY_MEDIUM_MS, FLOW_VELOCITY_HIGH_MS, FLOW_VELOCITY_CRITICAL_MS
    )

    max_sev = max(wl_sev, fv_sev)
    score = round(max_sev / 3.0, 3)

    if max_sev >= 3:
        level = "CRITICAL"
    elif max_sev >= 1:
        level = "WARNING"
    else:
        level = "NORMAL"

    basis: list[str] = []
    if wl_sev > 0:
        basis.append("water_level")
    if fv_sev > 0:
        basis.append("flow_velocity")

    return FloodRiskAssessment(
        risk_level=level,
        risk_score=score,
        basis=basis,
        water_level_band=wl_band,
        flow_velocity_band=fv_band,
        observed={
            "water_level_m": water_level_m,
            "flow_velocity_ms": flow_velocity_ms,
            "device_timestamp": device_timestamp,
            "lat": lat,
            "lng": lng,
        },
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
