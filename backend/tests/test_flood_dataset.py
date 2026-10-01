"""Dataset builder and trainer: the maths, and the guards that protect it.

These are the pieces that fail silently. A mis-aligned feature vector produces
a plausible-looking model; a diverging optimiser produces a model that scores
perfectly in-sample and does nothing out-of-sample. Every test here is offline
-- no GDACS, no Open-Meteo -- so a rebuild failure is always a code failure.
"""
from __future__ import annotations

import json
import math
from datetime import date, timedelta

import numpy as np
import pytest

from ml import flood_dataset as fd
from ml import train_flood_model as tf


# ── Antecedent feature extraction ─────────────────────────────────────────


def _archive_entry(day_totals: dict[date, float], elevation: float = 100.0) -> dict:
    return {
        "elevation": elevation,
        "daily": {
            "time": [d.isoformat() for d in sorted(day_totals)],
            "precipitation_sum": [day_totals[d] for d in sorted(day_totals)],
        },
    }


def _ten_days_before(onset: date, totals: list[float]) -> dict[date, float]:
    """Map 10 consecutive days ending the day before onset onto totals."""
    window_end = onset - timedelta(days=1)
    return {
        window_end - timedelta(days=9 - i): value
        for i, value in enumerate(totals)
    }


class TestFeatureExtraction:
    def test_window_excludes_the_onset_day_itself(self):
        onset = date(2024, 8, 15)
        series = _ten_days_before(onset, [1.0] * 10)
        baseline = fd._extract_features(_archive_entry(series), onset)
        assert baseline["precip_10d_mm"] == pytest.approx(10.0)

        # Rain falling on and after the onset must not leak backwards into the
        # antecedent window, or every event would look like it caused itself.
        for offset in (0, 1, 2):
            series[onset + timedelta(days=offset)] = 900.0
        after = fd._extract_features(_archive_entry(series), onset)
        assert after["precip_10d_mm"] == pytest.approx(10.0)
        assert after["peak_precip_3d_mm"] == pytest.approx(1.0)

    def test_peak_and_total_are_read_correctly(self):
        onset = date(2024, 8, 15)
        totals = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 40.0]
        features = fd._extract_features(_archive_entry(_ten_days_before(onset, totals)), onset)
        assert features["peak_precip_3d_mm"] == 40.0
        assert features["precip_10d_mm"] == pytest.approx(85.0)
        assert features["dry_spell_days"] == 0.0

    def test_dry_spell_counts_backwards_from_the_most_recent_day(self):
        onset = date(2024, 8, 15)
        # Rain on the fifth-most-recent day, and none in the four days since.
        totals = [0.0] * 5 + [10.0] + [0.0, 0.0, 0.0, 0.0]
        features = fd._extract_features(_archive_entry(_ten_days_before(onset, totals)), onset)
        assert features["dry_spell_days"] == 4.0

    def test_dry_spell_stops_at_the_first_wet_day(self):
        onset = date(2024, 8, 15)
        # A single wet day three back truncates the spell; the five dry days
        # older than it are deliberately not counted.
        totals = [0.0] * 6 + [12.0] + [0.0, 0.0, 0.0]
        features = fd._extract_features(_archive_entry(_ten_days_before(onset, totals)), onset)
        assert features["dry_spell_days"] == 3.0

    def test_dry_spell_runs_the_full_window_when_it_never_rains(self):
        onset = date(2024, 8, 15)
        features = fd._extract_features(
            _archive_entry(_ten_days_before(onset, [0.0] * 10)), onset
        )
        assert features["dry_spell_days"] == 10.0

    def test_just_under_the_dry_threshold_still_counts_as_dry(self):
        onset = date(2024, 8, 15)
        totals = [0.5] * 10
        features = fd._extract_features(_archive_entry(_ten_days_before(onset, totals)), onset)
        assert features["dry_spell_days"] == 10.0

    def test_location_absent_from_the_series_is_dropped_not_zeroed(self):
        # An all-zero feature row would look like a genuine decade-long drought.
        entry = _archive_entry({date(2001, 1, 1): 5.0})
        assert fd._extract_features(entry, date(2024, 8, 15)) is None

    def test_missing_daily_block_is_dropped(self):
        assert fd._extract_features({"daily": {}}, date(2024, 8, 15)) is None
        assert fd._extract_features({}, date(2024, 8, 15)) is None


# ── Metrics ───────────────────────────────────────────────────────────────


class TestMetrics:
    def test_roc_auc_of_a_perfect_ranking_is_one(self):
        y = np.array([0.0, 0.0, 1.0, 1.0])
        assert tf.roc_auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)

    def test_roc_auc_of_a_reversed_ranking_is_zero(self):
        y = np.array([0.0, 0.0, 1.0, 1.0])
        assert tf.roc_auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == pytest.approx(0.0)

    def test_roc_auc_of_tied_scores_is_one_half(self):
        y = np.array([0.0, 1.0])
        assert tf.roc_auc(y, np.array([0.5, 0.5])) == pytest.approx(0.5)

    def test_average_precision_of_a_perfect_ranking_is_one(self):
        y = np.array([0.0, 0.0, 1.0, 1.0])
        assert tf.average_precision(y, np.array([0.1, 0.2, 0.8, 0.9])) == pytest.approx(1.0)

    def test_average_precision_of_a_reversed_ranking_is_the_worst_ordering(self):
        # Average precision is not centred on the base rate, so the worst
        # ordering scores low-but-nonzero rather than zero.
        y = np.array([0.0, 0.0, 1.0, 1.0])
        worst = tf.average_precision(y, np.array([0.9, 0.8, 0.2, 0.1]))
        best = tf.average_precision(y, np.array([0.1, 0.2, 0.8, 0.9]))
        assert worst < best

    def test_average_precision_penalises_a_late_single_hit(self):
        # One positive ranked last, among four: precision 1/4 at rank 4.
        y = np.array([1.0, 0.0, 0.0, 0.0])
        assert tf.average_precision(y, np.array([0.1, 0.4, 0.3, 0.2])) == pytest.approx(0.25)

    def test_tied_scores_are_ordered_by_row_position(self):
        # Average precision has no defined value under a tie unless the
        # ordering is pinned, so this pins it and documents the choice.
        positive_rows_last = tf.average_precision(
            np.array([0.0, 0.0, 1.0, 1.0]), np.zeros(4)
        )
        positive_rows_first = tf.average_precision(
            np.array([1.0, 1.0, 0.0, 0.0]), np.zeros(4)
        )
        assert positive_rows_last < positive_rows_first

    def test_average_precision_of_a_single_class_target_is_nan_not_a_crash(self):
        # A degenerate fold must not be allowed to poison the aggregate.
        assert math.isnan(tf.average_precision(np.zeros(4), np.zeros(4)))

    def test_brier_score_of_a_perfect_call_is_zero(self):
        y = np.array([0.0, 1.0])
        assert tf.brier(y, np.array([0.0, 1.0])) == pytest.approx(0.0)


# ── Fitting ───────────────────────────────────────────────────────────────


class TestFitting:
    def _separable(self, n: int = 200):
        rng = np.random.default_rng(7)
        x = rng.normal(size=(n, 2))
        y = (x[:, 0] + 0.5 * x[:, 1] > 0).astype(float)
        return x, y

    def test_finds_a_direction_that_separates_separable_data(self):
        # Judged by ranking, not by mean: a well-separated balanced set has a
        # mean probability of ~0.5 by construction.
        x, y = self._separable()
        coef, intercept = tf.fit_logistic(x, y)
        assert coef[0] > 0
        assert tf.roc_auc(y, tf.predict_proba(x, coef, intercept)) == pytest.approx(1.0)

    def test_a_fitted_model_beats_an_uninformed_constant(self):
        x, y = self._separable()
        coef, intercept = tf.fit_logistic(x, y)
        fitted = tf.brier(y, tf.predict_proba(x, coef, intercept))
        assert fitted < tf.brier(y, np.full_like(y, y.mean()))

    def test_weights_stay_finite_and_bounded(self):
        # The Newton step diverges if its sign is flipped; this catches it.
        x, y = self._separable()
        coef, intercept = tf.fit_logistic(x, y)
        assert all(math.isfinite(v) for v in coef)
        assert abs(intercept) < 50.0
        assert all(abs(v) < 50.0 for v in coef)

    def test_a_constant_column_does_not_divide_by_zero(self):
        x = np.column_stack([np.ones(50), np.linspace(0, 1, 50)])
        y = np.array([0.0] * 25 + [1.0] * 25)
        _, mean, scale = tf._standardise(x)
        assert scale[0] == 1.0

    def test_l2_shrinks_coefficients_towards_zero(self):
        x, y = self._separable()
        weak, _ = tf.fit_logistic(x, y, l2=0.01)
        strong, _ = tf.fit_logistic(x, y, l2=50.0)
        assert float(np.linalg.norm(strong)) < float(np.linalg.norm(weak))


# ── The shipped dataset ───────────────────────────────────────────────────


class TestDatasetFile:
    def test_dataset_exists_and_is_labelled(self):
        assert fd.DEFAULT_CSV.exists(), "run `python -m ml.flood_dataset`"

    def test_dataset_has_both_classes(self):
        dataset = tf.load_dataset()
        assert dataset.y.min() == 0 and dataset.y.max() == 1

    def test_features_contain_no_nans(self):
        dataset = tf.load_dataset()
        assert np.isfinite(dataset.x).all()

    def test_rain_actually_separates_the_classes(self):
        # If this stops holding, the labels and the features have come
        # unmoored and the fit would be meaningless.
        dataset = tf.load_dataset()
        index = fd.FEATURE_COLUMNS.index("peak_precip_3d_mm")
        wet = dataset.x[dataset.y > 0.5, index].mean()
        dry = dataset.x[dataset.y < 0.5, index].mean()
        assert wet > dry

    def test_no_collinear_feature_pairs(self):
        assert tf.report_collinearity(tf.load_dataset()) == []


# ── Shipped artifact ──────────────────────────────────────────────────────


class TestArtifact:
    def _artifact(self) -> dict:
        assert tf.ARTIFACT_PATH.exists(), "run `python -m ml.train_flood_model`"
        return json.loads(tf.ARTIFACT_PATH.read_text(encoding="utf-8"))

    def test_artifact_beats_the_rules_baseline_out_of_fold(self):
        metrics = self._artifact()["metrics"]
        assert metrics["roc_auc"] > metrics["roc_auc_baseline_rule"]

    def test_artifact_reports_out_of_fold_metrics_not_in_sample_ones(self):
        artifact = self._artifact()
        assert artifact["metrics"]["roc_auc"] < artifact["in_sample"]["roc_auc"]

    def test_artifact_records_its_provenance(self):
        provenance = self._artifact()["training_data"]
        assert "GDACS" in provenance["labels"]
        assert provenance["positives"] > 0
        # The key is `distinct_events`: one row per de-duplicated GDACS record, so
        # it falling below `positives` would mean episodes are being counted as
        # independent events.
        assert provenance["distinct_events"] > 0
        assert provenance["distinct_events"] == provenance["positives"]

    def test_artifact_states_the_sampling_prior_caveat(self):
        # The single most misleading thing about this model is that its
        # intercept encodes a 1:2 sampling frame. That must not be droppable.
        limitations = " ".join(self._artifact()["limitations"])
        assert "sampling frame" in limitations or "base rate" in limitations

    def test_trainer_refuses_to_ship_a_model_that_cannot_beat_the_rule(
        self, tmp_path, monkeypatch
    ):
        # A model that loses to the existing arithmetic would be an opaque
        # regression, so the write is blocked rather than warned about.
        #
        # Patched on `ml.train`, not on this alias module: `train()` delegates to
        # `_train.train`, which resolves `cross_validate` in its own globals, so
        # patching the alias here would leave the real cross-validation running.
        import ml.train as trainer

        monkeypatch.setattr(trainer, "cross_validate", lambda spec, dataset: {
            # Above 0.5 so the coin-flip gate lets it through, and below the
            # rule's 0.60 so it is the *rule* gate this exercises, not an
            # earlier one.
            "roc_auc": 0.58,
            "roc_auc_baseline_rule": 0.60,
            "roc_auc_base_rate": 0.50,
            "average_precision": 0.35,
            "average_precision_base_rate": 0.3,
            "brier": 0.3,
            "brier_base_rate": 0.2,
            "positive_rate": 0.37,
            "rows": 389.0,
            "positives": 144.0,
            # `train()` reads this to name the strongest column in the report,
            # before the publication gate ever runs.
            "strongest_feature": 1.0,
        })
        target = tmp_path / "should-not-exist.json"
        with pytest.raises(RuntimeError, match="does not beat"):
            tf.train(artifact_path=target, verbose=False)
        assert not target.exists()

    def test_trainer_refuses_a_model_that_cannot_beat_a_coin_flip(
        self, tmp_path, monkeypatch
    ):
        # The other half of the gate. A rule that is *not* shipped would sail
        # past the rule comparison, so without this check a noise model could
        # be published wherever there was no arithmetic to beat.
        import ml.train as trainer

        monkeypatch.setattr(trainer, "cross_validate", lambda spec, dataset: {
            "roc_auc": 0.48,
            "roc_auc_baseline_rule": 0.60,
            "roc_auc_base_rate": 0.50,
            "average_precision": 0.3,
            "average_precision_base_rate": 0.3,
            "brier": 0.35,
            "brier_base_rate": 0.2,
            "positive_rate": 0.37,
            "rows": 389.0,
            "positives": 144.0,
            "strongest_feature": 1.0,
        })
        target = tmp_path / "should-not-exist.json"
        with pytest.raises(RuntimeError, match="coin flip"):
            tf.train(artifact_path=target, verbose=False)
        assert not target.exists()
