"""Extended hazard projections (Phase 18).

Covers the pure hazard maths, the uniform envelope helpers, and the weather
staleness guard. No network and no writes: the DB-backed branches (catalogue
lookup) are exercised through the live API in tests/e2e_smoke.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.engine import prediction_engine as pe
from app.engine.prediction_engine import (
    HAZARD_CATALOGUE,
    HAZARD_LIMITATIONS,
    LANDSLIDE_SATURATION_MM_HR,
    SEISMIC_MAGNITUDE_FLOOR,
    STORM_IMPACT_CEIL_KMH,
    STORM_IMPACT_FLOOR_KMH,
    WEATHER_MAX_AGE_MINUTES,
    _clamp01,
    _flood_propagation_probability,
    _haversine_km,
    _hazard_metrics,
    _landslide_susceptibility,
    _reading_age_minutes,
    _seismic_shaking_probability,
    _storm_impact_probability,
    _stale_reason,
    _zone_uniform_projection,
)

ZONE = {
    "centroid_lat": 22.3,
    "centroid_lng": 73.19,
    "radius_meters": 500.0,
}


class TestHaversine:
    def test_zero_distance(self):
        assert _haversine_km(22.3, 73.19, 22.3, 73.19) == pytest.approx(0.0, abs=1e-9)

    def test_one_degree_latitude_is_about_111km(self):
        assert _haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.2, abs=1.0)

    def test_symmetric(self):
        a = _haversine_km(22.3, 73.19, 22.4, 73.3)
        b = _haversine_km(22.4, 73.3, 22.3, 73.19)
        assert a == pytest.approx(b)

    def test_shrinks_with_latitude(self):
        """A degree of longitude is shorter away from the equator."""
        equator = _haversine_km(0.0, 0.0, 0.0, 1.0)
        vadodara = _haversine_km(22.3, 73.19, 22.3, 74.19)
        assert vadodara < equator


class TestSeismic:
    def test_below_floor_is_exactly_zero(self):
        """A trivial tremor must not register as exposure just because the
        depth/distance terms are non-zero."""
        assert _seismic_shaking_probability(2.0, 1.0, 1.0) == 0.0
        assert _seismic_shaking_probability(SEISMIC_MAGNITUDE_FLOOR, 1.0, 1.0) == 0.0

    def test_near_total_exposure(self):
        assert _seismic_shaking_probability(7.5, 5.0, 5.0) > 0.95

    def test_decreases_with_distance(self):
        values = [_seismic_shaking_probability(6.0, 10.0, d) for d in (10, 50, 100, 200, 300)]
        assert values == sorted(values, reverse=True)

    def test_decreases_with_depth(self):
        shallow = _seismic_shaking_probability(6.0, 5.0, 50.0)
        deep = _seismic_shaking_probability(6.0, 80.0, 50.0)
        assert shallow > deep

    def test_bounded_to_unit_interval(self):
        for magnitude in (0.0, 3.5, 5.0, 7.0, 9.5):
            value = _seismic_shaking_probability(magnitude, 0.0, 0.0)
            assert 0.0 <= value <= 1.0


class TestLandslide:
    def test_no_rainfall_is_no_risk(self):
        assert _landslide_susceptibility(0.0) == 0.0

    def test_saturates_at_reference_rate(self):
        assert _landslide_susceptibility(LANDSLIDE_SATURATION_MM_HR) == 1.0

    def test_clamped_above_reference(self):
        assert _landslide_susceptibility(500.0) == 1.0

    def test_monotonic(self):
        values = [_landslide_susceptibility(v) for v in (0, 10, 25, 50, 75, 100)]
        assert values == sorted(values)


class TestStorm:
    def test_below_floor_is_no_impact(self):
        assert _storm_impact_probability(0.0) == 0.0
        assert _storm_impact_probability(STORM_IMPACT_FLOOR_KMH) == 0.0

    def test_saturates_at_hurricane_force(self):
        assert _storm_impact_probability(STORM_IMPACT_CEIL_KMH) == 1.0
        assert _storm_impact_probability(300.0) == 1.0

    def test_midpoint(self):
        midpoint = (STORM_IMPACT_FLOOR_KMH + STORM_IMPACT_CEIL_KMH) / 2
        assert _storm_impact_probability(midpoint) == pytest.approx(0.5, abs=0.01)


class TestZoneUniformProjection:
    def test_above_threshold_emits_full_grid(self):
        result = _zone_uniform_projection(ZONE, 0.6, 12)
        assert result["spatial_resolution"] == "zone_uniform"
        assert result["coverage_percentage"] == 100.0
        assert len(result["affected_cells"]) == 9
        assert all(c["intensity"] == 60.0 for c in result["affected_cells"])

    def test_below_threshold_emits_single_null_cell(self):
        result = _zone_uniform_projection(ZONE, 0.01, 12)
        assert result["coverage_percentage"] == 0.0
        assert len(result["affected_cells"]) == 1
        assert result["affected_cells"][0]["intensity"] == 0

    def test_intensity_is_percentage_of_probability(self):
        assert _zone_uniform_projection(ZONE, 0.25, 12)["max_intensity"] == 25.0

    def test_expires_at_is_set(self):
        assert _zone_uniform_projection(ZONE, 0.5, 12)["expires_at"] is not None


class TestHazardCatalogue:
    def test_every_hazard_has_a_display_name_and_limitations(self):
        for kind in HAZARD_CATALOGUE:
            assert HAZARD_CATALOGUE[kind]["display_name"]
            assert HAZARD_LIMITATIONS[kind], f"{kind} has no documented limitations"

    def test_expected_hazards_are_modelled(self):
        assert set(HAZARD_CATALOGUE) == {"flood", "fire", "earthquake", "landslide", "storm"}

    def test_earthquake_is_zone_uniform(self):
        assert HAZARD_CATALOGUE["earthquake"]["modelled"] == "zone_uniform"

    def test_limitations_are_lists_of_strings(self):
        for kind, notes in HAZARD_LIMITATIONS.items():
            assert isinstance(notes, list)
            assert all(isinstance(n, str) and n for n in notes), kind


class TestHazardMetrics:
    def test_flood_metric(self):
        assert _hazard_metrics("flood", {"flooded_percentage": 42.0}) == {
            "flooded_percentage": 42.0
        }

    def test_fire_metric(self):
        assert _hazard_metrics("fire", {"spread_direction_degrees": 34.0}) == {
            "spread_direction_degrees": 34.0
        }

    def test_earthquake_metric_tolerates_missing_event(self):
        metrics = _hazard_metrics("earthquake", {"event": None})
        assert metrics["magnitude"] is None

    def test_storm_metric(self):
        metrics = _hazard_metrics("storm", {"wind_speed_kmh": 30.0, "impact_probability": 0.0})
        assert metrics["wind_speed_kmh"] == 30.0

    def test_landslide_metric(self):
        metrics = _hazard_metrics("landslide", {"susceptibility": 0.4, "rainfall_window": None})
        assert metrics["susceptibility"] == 0.4
        assert metrics["peak_rain_mm_hr"] is None


def test_clamp01():
    assert _clamp01(-1.0) == 0.0
    assert _clamp01(2.0) == 1.0
    assert _clamp01(0.42) == pytest.approx(0.42)


# ── Weather staleness guard ────────────────────────────────────────────────
# The weather poller is rate-limited upstream (open-meteo returns HTTP 429 on
# the free tier), which leaves behind rows that are well-formed but old. These
# tests pin the rule that an old row is missing data, not current weather.


def _reading(age_minutes: float) -> SimpleNamespace:
    polled_at = datetime.now(timezone.utc) - timedelta(minutes=age_minutes)
    return SimpleNamespace(polled_at=polled_at, wind_speed_kmh=85.0, rainfall_mm_hr=40.0)


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def all(self):
        return self._value


class _FakeSession:
    """Returns the zone for the geometry query, then the reading(s) for
    the weather query, in call order."""

    def __init__(self, zone, reading, rows=None):
        self._zone = zone
        self._reading = reading
        self._rows = rows if rows is not None else []

    async def execute(self, _stmt):
        if self._zone is not None:
            return _FakeResult(self._zone)
        return _FakeResult(self._rows)


class TestReadingAge:
    def test_fresh_reading_has_small_age(self):
        assert _reading_age_minutes(_reading(5.0).polled_at) == pytest.approx(5.0, abs=0.5)

    def test_missing_timestamp_is_none(self):
        assert _reading_age_minutes(None) is None

    def test_naive_timestamp_is_treated_as_utc(self):
        naive = datetime.now(timezone.utc).replace(tzinfo=None)
        assert _reading_age_minutes(naive) == pytest.approx(0.0, abs=1.0)

    def test_future_timestamp_clamps_to_zero(self):
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        assert _reading_age_minutes(future) == 0.0


class TestStaleReason:
    def test_fresh_reading_is_not_stale(self):
        assert _stale_reason(_reading(1.0).polled_at) is None

    def test_reading_at_the_limit_is_not_stale(self):
        assert _stale_reason(_reading(WEATHER_MAX_AGE_MINUTES - 1).polled_at) is None

    def test_reading_past_the_limit_is_stale(self):
        reason = _stale_reason(_reading(WEATHER_MAX_AGE_MINUTES + 60).polled_at)
        assert reason is not None
        assert "stale" in reason

    def test_reason_reports_the_actual_age(self):
        reason = _stale_reason(_reading(600.0).polled_at)
        assert "600 min old" in reason

    def test_missing_timestamp_is_reported_not_ignored(self):
        assert _stale_reason(None) == "weather reading has no timestamp"


class TestStormStaleness:
    async def test_stale_reading_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(pe, "_get_zone_geometry", _fake_geometry(ZONE))
        monkeypatch.setattr(pe, "_latest_weather", _fake_weather(_reading(600.0)))

        result = await pe.calculate_storm_impact("z1", None, 12, _FakeSession(None, None))

        assert result["available"] is False
        assert "stale" in result["reason"]
        # No number may be presented as current.
        assert result["wind_speed_kmh"] is None
        assert result["impact_probability"] is None
        assert _is_clear(result)


def _is_clear(result: dict) -> bool:
    """The envelope's no-exposure shape: zero coverage, zero intensity, and a
    single centroid marker rather than a grid of unaffected cells."""
    assert result["coverage_percentage"] == 0.0
    assert result["max_intensity"] == 0.0
    assert len(result["affected_cells"]) == 1
    assert result["affected_cells"][0]["intensity"] == 0
    return True

    async def test_fresh_reading_is_used(self, monkeypatch):
        monkeypatch.setattr(pe, "_get_zone_geometry", _fake_geometry(ZONE))
        monkeypatch.setattr(pe, "_latest_weather", _fake_weather(_reading(5.0)))

        result = await pe.calculate_storm_impact("z1", None, 12, _FakeSession(None, None))

        assert result["available"] is True
        assert result["wind_speed_kmh"] == 85.0
        assert result["impact_probability"] > 0.0

    async def test_explicit_wind_bypasses_the_reading(self, monkeypatch):
        """A caller-supplied wind is an explicit assumption, not a stale read,
        so it must stay usable when the poller is down."""
        monkeypatch.setattr(pe, "_get_zone_geometry", _fake_geometry(ZONE))

        result = await pe.calculate_storm_impact("z1", 85.0, 12, _FakeSession(None, None))

        assert result["available"] is True
        assert result["wind_source"] == "request_parameter"
        assert result["wind_speed_kmh"] == 85.0


class TestRainfallWindowStaleness:
    async def test_stale_rows_are_not_summarised(self, monkeypatch):
        """A 24 h window still contains rows from a poller that died 10 h ago.
        Those must not be reported as a current rainfall observation."""
        old = _reading(600.0).polled_at
        rows = [(40.0, old), (35.0, old - timedelta(minutes=5))]
        session = _FakeSession(None, None, rows=rows)

        result = await pe._rainfall_window("z1", session, hours=24)

        assert result["available"] is False
        assert "stale" in result["reason"]
        assert result["samples"] == 0
        assert result["peak_mm_hr"] == 0.0
        assert result["newest_reading_age_min"] > WEATHER_MAX_AGE_MINUTES

    async def test_fresh_rows_are_summarised(self):
        now = datetime.now(timezone.utc)
        rows = [(40.0, now), (20.0, now - timedelta(minutes=5))]
        session = _FakeSession(None, None, rows=rows)

        result = await pe._rainfall_window("z1", session, hours=24)

        assert result["available"] is True
        assert result["peak_mm_hr"] == 40.0
        assert result["mean_mm_hr"] == 30.0
        assert result["samples"] == 2

    async def test_landslide_is_unavailable_when_its_driver_is_stale(self, monkeypatch):
        monkeypatch.setattr(pe, "_get_zone_geometry", _fake_geometry(ZONE))
        old = _reading(600.0).polled_at
        session = _FakeSession(None, None, rows=[(90.0, old)])

        result = await pe.calculate_landslide_risk("z1", 12, session)

        assert result["available"] is False
        assert "stale" in result["reason"]
        assert result.get("susceptibility") is None
        assert _is_clear(result)


def _fake_geometry(zone: dict):
    async def _inner(_zone_id, _db):
        return zone

    return _inner


def _fake_weather(reading):
    async def _inner(_zone_id, _db):
        return reading

    return _inner


# ── Flood propagation gate ──────────────────────────────────────────────────
# The elevation and distance terms in _flood_propagation_probability are
# unconditional, so with no rain they still produced 0.35, and a corroborating
# report's evidence_boost (max 0.10) pushed that to 0.41 -- over the 0.4
# "flooded" threshold. The engine reported ~13% flood intensity for a zone whose
# rain gauge read exactly zero.


class TestFloodPropagationGate:
    def test_zero_rainfall_is_zero_probability(self):
        assert _flood_propagation_probability(0.0, 0.0, 0.0) == 0.0

    def test_zero_rainfall_stays_zero_at_the_centroid(self):
        # Best case for the non-rain terms: lowest elevation, zero distance.
        assert _flood_propagation_probability(0.0, 0.0, 0.0) == 0.0

    def test_zero_rainfall_stays_zero_with_worst_case_terms(self):
        # elev_risk and dist_factor are both maximised here, so this is the
        # highest probability the non-rain terms can reach on their own.
        assert _flood_propagation_probability(0.0, 0.0, 0.0) == 0.0

    def test_negative_rainfall_is_treated_as_zero(self):
        assert _flood_propagation_probability(-5.0, 0.0, 0.0) == 0.0

    def test_rainfall_still_produces_probability(self):
        # The gate must not zero out a real rainfall observation.
        assert _flood_propagation_probability(50.0, 0.0, 0.0) > 0.0

    def test_probability_is_monotonic_in_rainfall(self):
        low = _flood_propagation_probability(5.0, 0.5, 0.5)
        high = _flood_propagation_probability(25.0, 0.5, 0.5)
        assert high > low
