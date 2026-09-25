"""Phase 17 — Intelligence unit tests (§40–41).

Deterministic scoring paths only (no network, no LLM):
    evidence_fusion  — aggregate scoring + external_factor (7th factor)
    clustering       — hazard compatibility rules
    trust_scoring    — component extensions + overall bounds
    route_intelligence — adapter contract (source/geometry/cost/penalties)
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.clustering import _hazard_compatible
from app.services.evidence_fusion import (
    W_INFRA_EXPOSURE,
    W_SEISMIC_PROXIMITY,
    EvidenceFusionService,
)
from app.services.route_intelligence import haversine_km
from app.services.trust_scoring import (
    _compute_corroboration_score,
    _compute_text_quality_score,
    compute_trust_score,
)

_fusion = EvidenceFusionService()


def _sections(
    *,
    seismic: dict | None = None,
    infrastructure: dict | None = None,
    reports: dict | None = None,
) -> dict:
    return {
        "citizen_reports": reports
        or {"available": False, "reason": "no corroborating reports", "confidence": 0.0},
        "weather": {"available": False, "reason": "no recent reading", "confidence": 0.0},
        "seismic": seismic or {"available": False, "reason": "no events", "confidence": 0.0},
        "infrastructure": infrastructure
        or {"available": False, "reason": "no cached features", "confidence": 0.0},
        "predictions": {"available": False, "reason": "no stored projection", "confidence": 0.0},
    }


# ── Evidence fusion: aggregate + 7th factor ─────────────────────────────────

def test_aggregate_all_unavailable_is_zero():
    agg = _fusion._aggregate(_sections())
    assert agg["available_sections"] == 0
    assert agg["external_raw"] == 0.0
    assert agg["risk_signals"] == []
    assert agg["mean_confidence"] == 0.0

    raw, label = _fusion.external_factor({"aggregate": agg})
    assert raw == 0.0
    assert label == "no external risk signals available"


def test_aggregate_blends_seismic_and_infrastructure():
    sections = _sections(
        seismic={"available": True, "proximity_risk": 1.0, "signal": "seismic 40 km away",
                 "confidence": 0.9},
        infrastructure={"available": True, "exposure": 1.0, "signal": "3 hospitals in radius",
                        "confidence": 0.8},
    )
    agg = _fusion._aggregate(sections)

    expected = min(1.0, 1.0 * W_SEISMIC_PROXIMITY + 1.0 * W_INFRA_EXPOSURE)
    assert agg["external_raw"] == round(expected, 3)
    assert agg["available_sections"] == 2
    assert agg["risk_signals"] == ["seismic 40 km away", "3 hospitals in radius"]
    assert agg["mean_confidence"] == round((0.9 + 0.8) / 2, 3)

    raw, label = _fusion.external_factor({"aggregate": agg})
    assert raw == agg["external_raw"]
    assert "seismic 40 km away" in label and "3 hospitals" in label


def test_aggregate_external_raw_is_capped_at_one():
    sections = _sections(
        seismic={"available": True, "proximity_risk": 1.0, "signal": "s", "confidence": 1.0},
        infrastructure={"available": True, "exposure": 10.0, "signal": "i", "confidence": 1.0},
    )
    assert _fusion._aggregate(sections)["external_raw"] == 1.0


def test_aggregate_seismic_only_uses_seismic_weight():
    sections = _sections(
        seismic={"available": True, "proximity_risk": 0.5, "signal": "s", "confidence": 0.7},
    )
    agg = _fusion._aggregate(sections)
    assert agg["external_raw"] == round(0.5 * W_SEISMIC_PROXIMITY, 3)
    assert agg["risk_signals"] == ["s"]


# ── Clustering: hazard compatibility ────────────────────────────────────────

def test_hazard_compatible_rules():
    # known-but-different hazards never merge
    assert _hazard_compatible("flood", "fire") == (False, None)
    # same known hazard merges
    assert _hazard_compatible("flood", "flood") == (True, "flood")
    # one side unknown → compatible, known side is the label
    assert _hazard_compatible(None, "fire") == (True, "fire")
    assert _hazard_compatible("earthquake", None) == (True, "earthquake")
    assert _hazard_compatible(None, None) == (True, None)
    # case/space insensitive
    assert _hazard_compatible("Flood ", "flood") == (True, "flood")


# ── Trust scoring extensions ────────────────────────────────────────────────

def test_corroboration_score_bounds_and_plateau():
    assert _compute_corroboration_score(0) == 0.0
    assert _compute_corroboration_score(-3) == 0.0
    score5 = _compute_corroboration_score(5)
    assert 0.0 < score5 <= 0.5
    # monotonic non-decreasing …
    assert _compute_corroboration_score(10) >= score5
    # … plateau: 0.1 + 0.1 * min(n, 10) / 10 → 0.2 at n ≥ 10, hard cap 0.5
    assert _compute_corroboration_score(10) == 0.2
    assert _compute_corroboration_score(100) == 0.2
    assert _compute_corroboration_score(100) <= 0.5


def test_text_quality_empty_text_is_low():
    report = SimpleNamespace(message_text="", transcript="")
    assert _compute_text_quality_score(report) == 0.1


def test_text_quality_good_report_scores_high():
    report = SimpleNamespace(
        message_text="Flooding near the river bridge. Two families trapped, need help now.",
        transcript="",
    )
    score = _compute_text_quality_score(report)
    assert score > 0.5


def test_compute_trust_score_shape_and_bounds():
    report = SimpleNamespace(
        message_text="Major fire at the warehouse. People trapped, please send help immediately.",
        transcript="",
        lat=22.3,
        lng=73.2,
        reported_at=datetime.now(timezone.utc),
        image_url=None,
        image_data=None,
        disaster_type="fire",
    )
    out = compute_trust_score(
        report,
        weather_reading=None,
        user_history={},
        report_count_in_zone=3,
    )
    for key in (
        "trust_score", "corroboration", "metadata", "geospatial",
        "text_quality", "source_reliability", "reason",
    ):
        assert key in out, key
    assert 0.0 <= out["trust_score"] <= 1.0
    for key in ("corroboration", "metadata", "geospatial", "text_quality", "source_reliability"):
        assert 0.0 <= out[key] <= 1.0, key
    assert isinstance(out["reason"], str) and out["reason"]


def test_compute_trust_score_empty_report_still_bounded():
    report = SimpleNamespace(message_text="", transcript="", lat=None, lng=None)
    out = compute_trust_score(report, report_count_in_zone=0)
    assert 0.0 <= out["trust_score"] <= 1.0
    assert out["reason"]


# ── Route adapter contract ──────────────────────────────────────────────────

def test_haversine_zero_and_known_distance():
    assert haversine_km(22.3, 73.2, 22.3, 73.2) == 0.0
    # 1 degree of latitude ≈ 111.2 km
    assert 110.0 < haversine_km(0.0, 0.0, 1.0, 0.0) < 112.5


async def test_calculate_route_osrm_success_contract():
    """Successful OSRM path keeps the /api/routes/compute contract shape."""
    from unittest.mock import AsyncMock

    from app.integrations.base import ConnectorError  # noqa: F401 (contract import)
    from app.services.route_intelligence import calculate_route

    fake = {
        "distance_m": 5432.1,
        "duration_s": 600.0,
        "geometry": [[73.2, 22.3], [73.25, 22.35], [73.3, 22.4]],
        "route_count": 1,
    }
    with patch(
        "app.services.route_intelligence.OsrmConnector.route",
        new=AsyncMock(return_value=fake),
    ):
        route = await calculate_route(22.3, 73.2, 22.4, 73.3, db=None)

    # legacy contract fields (§5.5 — never renamed/removed)
    for key in ("route_id", "origin", "destination", "distance_km",
                "duration_minutes", "note", "computed_at"):
        assert key in route, key
    # additive Phase 5 fields
    assert route["source"] == "osrm"
    assert route["geometry"] == fake["geometry"]
    assert isinstance(route["cost"], float)
    for key in ("traffic", "flood", "bridge", "blockage", "weather", "satellite"):
        assert key in route["penalties"], key
        assert 0.0 <= route["penalties"][key] <= 1.0
    assert route["distance_km"] == round(5432.1 / 1000.0, 2)
    assert route["duration_minutes"] == round(600.0 / 60.0, 1)
    assert route["cost"] >= route["distance_km"]


async def test_calculate_route_fallback_contract():
    """OSRM down → labelled fallback, same contract keys (§31)."""
    from unittest.mock import AsyncMock

    from app.integrations.base import ConnectorError
    from app.services.route_intelligence import calculate_route

    with patch(
        "app.services.route_intelligence.OsrmConnector.route",
        new=AsyncMock(side_effect=ConnectorError("osrm", "HTTP 503")),
    ):
        route = await calculate_route(22.3, 73.2, 22.4, 73.3, db=None)

    assert route["source"] == "fallback_haversine"
    assert "DEGRADED" in route["note"]
    for key in ("route_id", "origin", "destination", "distance_km",
                "duration_minutes", "cost", "penalties", "geometry", "computed_at"):
        assert key in route, key
    assert len(route["geometry"]) >= 2
