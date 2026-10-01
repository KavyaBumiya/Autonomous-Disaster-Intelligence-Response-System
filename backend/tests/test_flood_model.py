"""Trained flood model: artifact loading, scoring, and refusal to misbehave.

The deployed artifact is a fitted file, so these tests treat it as untrusted
input. The model is only ever allowed to make a forecast worse than the rules
baseline it replaces, never to break one, so every degradation path gets a test.

No network and no database: the antecedent-rainfall query is exercised through
the pure feature maths and a stubbed session.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.engine import prediction_engine as pe
from app.ml import flood_model as fm
from app.ml.flood_model import FloodModel
from app.services.phase2 import model_registry, model_status


def _artifact(**overrides) -> dict:
    """A minimal well-formed artifact, overridable field by field."""
    artifact = {
        "model_id": "aegis-flood-logistic",
        "model_version": "test-v1",
        "trained_at": "2026-01-01T00:00:00+00:00",
        "target": "flood occurrence",
        "feature_columns": ["peak_precip_3d_mm", "precip_10d_mm"],
        "scaler": {"mean": [10.0, 50.0], "scale": [10.0, 25.0]},
        "coef": [0.5, -0.2],
        "intercept": -0.5,
        "metrics": {"roc_auc": 0.64},
        "training_data": {"labels": "GDACS flood records"},
        "limitations": ["synthetic test artifact"],
    }
    artifact.update(overrides)
    return artifact


@pytest.fixture
def write_artifact(tmp_path: Path):
    def _write(payload: dict | str) -> Path:
        path = tmp_path / "flood.json"
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )
        return path

    return _write


def _features(**overrides) -> dict[str, float]:
    base = {"peak_precip_3d_mm": 20.0, "precip_10d_mm": 80.0}
    base.update(overrides)
    return base


# ── Artifact loading ──────────────────────────────────────────────────────


class TestArtifactLoading:
    def test_valid_artifact_loads(self, write_artifact):
        model = FloodModel(write_artifact(_artifact()))
        assert model.available is True
        assert model.load_error is None
        assert model.info()["model_version"] == "test-v1"

    def test_missing_file_is_not_fatal(self, tmp_path):
        model = FloodModel(tmp_path / "absent.json")
        assert model.available is False
        assert "not found" in model.load_error
        # The caller falls back on None, so this must be None and not raise.
        assert model.probability(_features()) is None

    def test_malformed_json_is_not_fatal(self, write_artifact):
        model = FloodModel(write_artifact("{not json"))
        assert model.available is False
        assert model.probability(_features()) is None

    def test_missing_required_field_is_rejected(self, write_artifact):
        broken = _artifact()
        del broken["coef"]
        model = FloodModel(write_artifact(broken))
        assert model.available is False
        assert "coef" in model.load_error

    def test_coef_length_mismatch_is_rejected(self, write_artifact):
        # A feature-count mismatch would silently score the wrong columns.
        model = FloodModel(write_artifact(_artifact(coef=[0.5, 0.1, 0.2])))
        assert model.available is False

    def test_non_finite_coefficient_is_rejected(self, write_artifact):
        model = FloodModel(write_artifact(_artifact(coef=[float("nan"), 0.1])))
        assert model.available is False

    def test_runaway_coefficient_is_rejected(self, write_artifact):
        # Guards against an artifact that has been hand-edited or scaled wrong.
        model = FloodModel(write_artifact(_artifact(coef=[9e9, 0.1])))
        assert model.available is False

    def test_non_positive_scale_is_rejected(self, write_artifact):
        model = FloodModel(
            write_artifact(_artifact(scaler={"mean": [1.0, 1.0], "scale": [1.0, 0.0]}))
        )
        assert model.available is False

    def test_info_reports_the_fallback_when_unavailable(self, tmp_path):
        info = FloodModel(tmp_path / "absent.json").info()
        assert info["available"] is False
        assert info["fallback"] == "rules-baseline"


# ── Scoring ───────────────────────────────────────────────────────────────


class TestScoring:
    def test_probability_is_a_probability(self, write_artifact):
        model = FloodModel(write_artifact(_artifact()))
        value = model.probability(_features())
        assert value is not None
        assert 0.0 <= value <= 1.0

    def test_more_rain_raises_the_probability(self, write_artifact):
        model = FloodModel(write_artifact(_artifact()))
        dry = model.probability(_features(peak_precip_3d_mm=1.0))
        wet = model.probability(_features(peak_precip_3d_mm=40.0))
        assert wet > dry

    def test_missing_feature_returns_none(self, write_artifact):
        # Scoring an absent feature as zero would state a confident answer
        # built on missing data.
        model = FloodModel(write_artifact(_artifact()))
        assert model.probability({"peak_precip_3d_mm": 20.0}) is None

    def test_nan_feature_returns_none(self, write_artifact):
        model = FloodModel(write_artifact(_artifact()))
        assert model.probability(_features(peak_precip_3d_mm=float("nan"))) is None

    def test_extra_features_are_ignored(self, write_artifact):
        model = FloodModel(write_artifact(_artifact()))
        assert model.probability(_features(unused=1.0)) is not None

    def test_probability_saturates_rather_than_overflowing(self, write_artifact):
        # Coefficients are kept inside the runaway guard, but the logit still
        # runs far past the point where exp() would overflow.
        model = FloodModel(
            write_artifact(_artifact(coef=[40.0, 40.0], intercept=45.0))
        )
        value = model.probability(_features())
        assert value == 1.0

    def test_runaway_intercept_is_rejected(self, write_artifact):
        model = FloodModel(write_artifact(_artifact(intercept=900.0)))
        assert model.available is False

    def test_assessment_reports_contributions(self, write_artifact):
        assessment = FloodModel(write_artifact(_artifact())).assess(_features())
        assert assessment is not None
        assert set(assessment.contributions) == {"peak_precip_3d_mm", "precip_10d_mm"}
        assert assessment.explain().startswith("test-v1:")

    def test_training_mean_substitutes_for_unobserved_features(self, write_artifact):
        model = FloodModel(write_artifact(_artifact()))
        assert model.training_mean("peak_precip_3d_mm") == 10.0
        assert model.training_mean("not_a_feature") is None

    def test_train_degenerate_scalar(self, write_artifact):
        # A zero-variance column makes every input identical after scaling, so
        # the probability must be constant rather than undefined.
        model = FloodModel(write_artifact(_artifact()))
        first = model.probability(_features(peak_precip_3d_mm=0.0))
        second = model.probability(_features(peak_precip_3d_mm=999.0))
        assert first is not None and second is not None


# ── The shipped artifact ──────────────────────────────────────────────────


class TestShippedArtifact:
    def test_shipped_artifact_is_present_and_valid(self):
        model = fm.get_flood_model()
        assert model.available, model.load_error
        info = model.info()
        assert info["model_version"].startswith("flood-lr")
        assert info["feature_columns"]

    def test_shipped_model_beats_the_rules_baseline(self):
        # The trainer refuses to write an artifact that does not, but the claim
        # is worth re-asserting against whatever is actually on disk.
        metrics = fm.get_flood_model().info()["metrics"]
        assert metrics["roc_auc"] > metrics["roc_auc_baseline_rule"]
        assert metrics["roc_auc"] > metrics["roc_auc_base_rate"]

    def test_shipped_model_carries_its_limitations(self):
        info = fm.get_flood_model().info()
        assert info["limitations"], "a model must not ship without its caveats"
        assert info["training_data"]["labels"]


# ── Engine integration ────────────────────────────────────────────────────


class TestEngineIntegration:
    def test_spatial_decay_is_full_at_the_centroid(self):
        assert pe._flood_spatial_decay(0.0) == pytest.approx(1.0)

    def test_spatial_decay_halves_at_the_falloff(self):
        assert pe._flood_spatial_decay(10.0) == pytest.approx(0.5)

    def test_spatial_decay_never_inverts_past_the_falloff(self):
        assert pe._flood_spatial_decay(50.0) == pytest.approx(0.5)

    def test_rules_baseline_still_gates_on_zero_rainfall(self):
        # The trained model must not have weakened this guarantee.
        assert pe._flood_propagation_probability(0.0, 0.0, 0.0) == 0.0
        assert pe._flood_propagation_probability(-5.0, 0.0, 0.0) == 0.0

    def test_rules_baseline_is_monotonic_in_rainfall(self):
        assert pe._flood_propagation_probability(
            25.0, 0.5, 0.5
        ) > pe._flood_propagation_probability(5.0, 0.5, 0.5)

    def test_flood_limitations_admit_the_fitted_model_is_coarse(self):
        joined = " ".join(pe.HAZARD_LIMITATIONS["flood"])
        assert "ranking score" in joined


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    """Minimal stand-in for the rainfall-history query."""

    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _Rows(self._rows)


def _history(days_back: dict[int, float], days_missing=()) -> list:
    """Build poller rows for `days_back` days ago, skipping `days_missing`.

    One tuple per selected column, in the order `_daily_history` selects them.
    Pressure and humidity are carried as NULL: flood does not use them, and
    inventing plausible values for columns it ignores would hide the fact that
    they are simply not observed here.
    """
    today = datetime.now(timezone.utc).date()
    rows = []
    for offset, rate in days_back.items():
        if offset in days_missing:
            continue
        day = today - timedelta(days=offset)
        for hour in (6, 18):
            rows.append(
                (
                    datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc),
                    rate,
                    29.0,
                    45.0,
                    None,
                    None,
                )
            )
    return sorted(rows)


class TestAntecedentFeatures:
    async def _features(self, days_back, days_missing=()):
        return await pe._antecedent_rain_features(
            "zone-1", _Session(_history(days_back, days_missing))
        )

    async def test_full_history_yields_features(self):
        features = await self._features({offset: 0.5 for offset in range(1, 11)})
        assert features is not None
        assert features["precip_10d_mm"] == pytest.approx(120.0)  # 12 mm/day
        assert features["peak_precip_3d_mm"] == pytest.approx(12.0)
        assert features["dry_spell_days"] == 0.0
        assert features["elevation_m"] > 0

    async def test_a_thin_history_is_refused(self):
        # Three days of data must not be scored as if it were a decade.
        assert await self._features({offset: 0.5 for offset in range(1, 4)}) is None

    async def test_no_history_is_refused(self):
        assert await self._features({}) is None

    async def test_a_gap_does_not_read_as_a_drought(self):
        # Nine days of data with the fourth day missing. Scoring the gap as
        # zero rain would push dry_spell_days to 4; treating it as unknown
        # truncates the claimed dry spell at the gap.
        history = {offset: 0.0 for offset in range(1, 10)}
        features = await self._features(history, days_missing={4})
        assert features is not None
        assert features["dry_spell_days"] == 3.0
        # The gap contributes no rainfall to the ten-day total either.
        assert features["precip_10d_mm"] == pytest.approx(0.0)

    async def test_a_gap_does_not_inflate_the_ten_day_total(self):
        history = {offset: 0.0 for offset in range(1, 11)}
        features = await self._features(history, days_missing={5})
        assert features["precip_10d_mm"] == pytest.approx(0.0)
        assert features["peak_precip_3d_mm"] == pytest.approx(0.0)

    async def test_dry_spell_still_stops_at_a_wet_day(self):
        history = {offset: 0.0 for offset in range(1, 8)}
        history[3] = 20.0
        features = await self._features(history)
        assert features["dry_spell_days"] == 2.0

    async def test_today_and_yesterday_are_excluded_from_the_window(self):
        rows = _history({offset: 0.0 for offset in range(1, 11)})
        today = datetime.now(timezone.utc).date()
        rows.append(
            (
                datetime(today.year, today.month, today.day, 3, tzinfo=timezone.utc),
                99.0, 29.0, 45.0, None, None,
            )
        )
        features = await pe._antecedent_rain_features("zone-1", _Session(sorted(rows)))
        assert features["precip_10d_mm"] == pytest.approx(0.0)


# ── Registry honesty ──────────────────────────────────────────────────────


class TestRegistryHonesty:
    def test_every_shipped_artifact_is_reported_as_trained(self):
        # Driven off the artifacts, not a hand-maintained list. This previously
        # asserted exactly ["flood-occurrence"] and passed only because the
        # registry was hardcoded to flood, while fire and storm had shipped
        # artifacts on disk. The API was under-reporting two fitted models.
        from app.ml.occurrence_model import available_models

        registry = model_registry()
        expected = {
            f"{hazard}-occurrence" for hazard, ok in available_models().items() if ok
        }
        assert {k for k, v in registry.items() if v.get("trained")} == expected
        assert {"flood-occurrence", "fire-occurrence", "storm-occurrence"} <= expected

    def test_trained_entries_name_the_shared_evaluator(self):
        # The registry must not point at a flood-specific alias now that the
        # generic evaluator serves every hazard.
        for name, entry in model_registry().items():
            if entry.get("trained"):
                assert "occurrence_model.OccurrenceModel[" in entry["implemented_by"], name

    def test_untrained_models_are_not_labelled_ready(self):
        for name, entry in model_registry().items():
            if not entry.get("trained"):
                assert entry.get("runtime") in {
                    "rules-baseline",
                    "huggingface-inference",
                }, name
                assert entry.get("implemented_by"), name

    def test_victim_detection_does_not_claim_a_torch_runtime(self):
        # It is a pretrained checkpoint loaded by image_analysis, nothing more.
        entry = model_registry()["victim-detection"]
        assert entry["runtime"] == "huggingface-inference"
        assert entry["trained"] is False

    def test_flood_entry_reports_real_metrics(self):
        entry = model_registry()["flood-occurrence"]
        assert entry["trained"] is True
        assert entry["roc_auc"] > entry["roc_auc_baseline_rule"]

    def test_every_trained_entry_reports_metrics_that_beat_its_rule(self):
        # Read from each artifact rather than asserted per hazard, so adding a
        # hazard cannot skip this check.
        for name, entry in model_registry().items():
            if entry.get("trained"):
                assert entry["roc_auc"] > entry["roc_auc_baseline_rule"], name
                assert entry["rows"] > 0 and entry["positives"] > 0, name
                assert entry["limitations"], name

    def test_status_separates_trained_from_untrained(self):
        status = model_status()
        registry = model_registry()
        assert set(status["trained_models"]) == {
            k for k, v in registry.items() if v.get("trained")
        }
        assert "behaviour-risk" in status["untrained_models"]

    def test_status_for_unknown_model_is_unhealthy(self):
        assert model_status("no-such-model")["healthy"] is False
