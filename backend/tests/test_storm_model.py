"""The storm occurrence model: pressure/humidity wiring, and honest degradation.

The storm model was denied mean sea-level pressure for as long as the poller did
not store it, because a feature the runtime cannot read would have left it
permanently unscoreable. Migration 0011 stores it. These tests pin both halves of
that bargain: the columns reach the fit, and a zone whose history predates the
migration is *declined* rather than scored on an invented value.

No network and no database. The daily aggregation is exercised through a stubbed
session; the feature definitions are imported from `ml.hazards`, the same
functions the dataset builder uses, so the offline and online definitions cannot
drift apart unnoticed.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.engine import prediction_engine as pe
from app.ml import occurrence_model as om
from ml import hazards as hz

STORM = hz.STORM


# ── The shipped artifact ───────────────────────────────────────────────────


class TestShippedStormArtifact:
    def test_artifact_is_present_and_valid(self):
        model = om.get_storm_model()
        assert model.available, model.load_error
        assert model.info()["model_version"].startswith("storm-lr")

    def test_pressure_and_humidity_are_fitted(self):
        columns = om.get_storm_model().info()["feature_columns"]
        assert "pressure_min_3d_hpa" in columns
        assert "humidity_mean_3d_pct" in columns

    def test_still_beats_the_rules_baseline(self):
        metrics = om.get_storm_model().info()["metrics"]
        assert metrics["roc_auc"] > metrics["roc_auc_baseline_rule"]
        assert metrics["roc_auc"] > metrics["roc_auc_base_rate"]

    def test_carries_its_limitations(self):
        assert om.get_storm_model().info()["limitations"]

    def test_a_backwards_pressure_weight_is_named_in_the_limitations(self):
        """Low pressure is a cyclone, so a *positive* weight on the minimum
        pressure reads backwards. It is tolerated only because the artifact
        states plainly that the column is near-inert."""
        artifact = json.loads(
            (om.ARTIFACT_DIR / om.ARTIFACTS["storm"]).read_text(encoding="utf-8")
        )
        weight = dict(zip(artifact["feature_columns"], artifact["coef"]))[
            "pressure_min_3d_hpa"
        ]
        assert abs(weight) < 0.1, f"pressure weight {weight:+.3f} is not a rounding artefact"
        if weight > 0:
            notes = " ".join(artifact["limitations"]).lower()
            assert "pressure" in notes, "a positive pressure weight is undocumented"


# ── Offline extractor ──────────────────────────────────────────────────────


def _extract(day: date, **daily: list) -> dict | None:
    """Run the real extractor over a `antecedent_days`-long window.

    `daily` supplies the final values; earlier days are padded with None so the
    extractor sees exactly the shape it was fitted on.
    """
    span = STORM.antecedent_days
    series: dict[str, list] = {"time": []}
    for name in daily:
        series[name] = [None] * span
    for index in range(span):
        target = day - timedelta(days=span - index)
        series["time"].append(target.isoformat())
        if index >= span - len(next(iter(daily.values()))):
            offset = index - (span - len(next(iter(daily.values()))))
            for name, values in daily.items():
                series[name][index] = values[offset]
    return STORM.extract({"elevation": 240.0, "daily": series}, day, span)


class TestExtractStorm:
    ONSET = date(2026, 1, 15)

    def _steady(self, **overrides) -> dict | None:
        daily = {
            "precipitation_sum": [4.0] * 4,
            "wind_speed_10m_max": [50.0] * 4,
            "temperature_2m_max": [28.0] * 4,
            "pressure_msl_mean": [1010.0] * 4,
            "relative_humidity_2m_mean": [70.0] * 4,
        }
        daily.update(overrides)
        return _extract(self.ONSET, **daily)

    def test_emits_every_required_column(self):
        features = self._steady()
        assert features is not None
        for column in STORM.feature_columns:
            assert column in features, column

    def test_pressure_is_the_window_minimum_not_the_mean(self):
        """A cyclone announces itself as a pressure *fall*. Averaging that away
        would discard the part of the signal that matters."""
        features = self._steady(pressure_msl_mean=[1010.0, 1012.0, 1005.0, 1008.0])
        assert features["pressure_min_3d_hpa"] == pytest.approx(1005.0)

    def test_humidity_is_the_window_mean(self):
        features = self._steady(relative_humidity_2m_mean=[60.0, 70.0, 80.0, 90.0])
        assert features["humidity_mean_3d_pct"] == pytest.approx(80.0)

    def test_absent_pressure_declines_rather_than_defaulting(self):
        """1013 hPa is a plausible-looking constant. Substituting it would assert
        a measurement nobody made."""
        features = self._steady(pressure_msl_mean=[None] * 4)
        assert features["pressure_min_3d_hpa"] is None

    def test_absent_humidity_does_not_read_as_bone_dry_air(self):
        features = self._steady(relative_humidity_2m_mean=[None] * 4)
        assert features["humidity_mean_3d_pct"] is None

    def test_thin_wind_coverage_is_refused(self):
        wind = [50.0] + [None] * 8 + [50.0]
        assert self._steady(wind_speed_10m_max=wind) is None

    def test_the_rule_baseline_sees_only_the_latest_wind(self):
        """`_storm_impact_probability` reads one day's wind, so `wind_max_1d_kmh`
        is withheld from the fit to keep the baseline an honest comparison."""
        features = self._steady(wind_speed_10m_max=[50.0, 50.0, 50.0, 120.0])
        assert features["wind_max_1d_kmh"] == pytest.approx(120.0)
        assert features["wind_max_3d_kmh"] == pytest.approx(120.0)
        expected = (120.0 - hz.RULES_WIND_FLOOR_KMH) / (
            hz.RULES_WIND_CEIL_KMH - hz.RULES_WIND_FLOOR_KMH
        )
        assert STORM.rule_score(features) == pytest.approx(expected)


# ── Runtime wiring ─────────────────────────────────────────────────────────


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _Rows(self._rows)


def _poller_rows(*, pressure=1010.0, humidity=70.0, days=range(1, 11)) -> list:
    """Poller rows in the column order `_daily_history` selects them.

    `pressure=None` / `humidity=None` model rows written before migration 0011.
    """
    today = datetime.now(timezone.utc).date()
    rows = []
    for offset in days:
        day = today - timedelta(days=offset)
        for hour in (6, 12, 18):
            rows.append(
                (
                    datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc),
                    2.0,
                    29.0,
                    45.0,
                    humidity,
                    pressure,
                )
            )
    return sorted(rows)


class TestDailyAggregation:
    async def test_pressure_and_humidity_are_averaged_per_day(self):
        rows = _poller_rows()
        rows.append(rows[0][:5] + (900.0,))  # a fourth, low sample on the oldest day
        history = await pe._daily_history("z", _Session(sorted(rows)), 10)
        oldest = min(history)
        assert history[oldest]["pressure_msl_mean"] == pytest.approx((1010 * 3 + 900) / 4)
        assert history[oldest]["relative_humidity_2m_mean"] == pytest.approx(70.0)

    async def test_a_day_with_no_pressure_reads_as_missing_not_zero(self):
        rows = [(r[0], r[1], r[2], r[3], None, None) for r in _poller_rows()]
        history = await pe._daily_history("z", _Session(rows), 10)
        for record in history.values():
            assert record["pressure_msl_mean"] is None
            assert record["relative_humidity_2m_mean"] is None

    async def test_one_null_sample_does_not_sink_the_day_mean(self):
        """A partially-migrated day averages the samples it actually has, rather
        than dividing by every reading the poller happened to take."""
        rows = _poller_rows()
        today = datetime.now(timezone.utc).date()
        gap = today - timedelta(days=3)
        rows = [
            (r[0], r[1], r[2], r[3], None, None)
            if r[0].date() == gap and r[0].hour != 6
            else r
            for r in rows
        ]
        history = await pe._daily_history("z", _Session(sorted(rows)), 10)
        assert history[gap]["pressure_msl_mean"] == pytest.approx(1010.0)


class TestEngineFeatures:
    async def _features(self, **kwargs):
        return await pe._occurrence_features(
            "storm", "z1", _Session(_poller_rows(**kwargs))
        )

    async def test_full_history_yields_pressure_and_humidity(self):
        features = await self._features()
        assert features is not None
        assert features["pressure_min_3d_hpa"] == pytest.approx(1010.0)
        assert features["humidity_mean_3d_pct"] == pytest.approx(70.0)

    async def test_a_low_pressure_window_reaches_the_model(self):
        features = await self._features(pressure=980.0)
        assert features["pressure_min_3d_hpa"] == pytest.approx(980.0)

    async def test_a_thin_history_is_refused(self):
        features = await pe._occurrence_features(
            "storm", "z1", _Session(_poller_rows(days=range(1, 4)))
        )
        assert features is None

    async def test_pre_migration_history_produces_no_pressure_feature(self):
        """Not a crash, and not a default: the feature is simply absent, and
        `assess()` is what refuses to score it."""
        features = await self._features(pressure=None, humidity=None)
        assert features is not None
        assert features["pressure_min_3d_hpa"] is None
        assert features["humidity_mean_3d_pct"] is None


class TestDegradation:
    PRE_MIGRATION = {
        "wind_max_3d_kmh": 45.0,
        "pressure_min_3d_hpa": None,
        "humidity_mean_3d_pct": None,
        "precip_3d_mm": 144.0,
        "temp_max_mean_3d_c": 29.0,
        "elevation_m": 242.29,
    }

    def test_a_zone_without_pressure_is_declined_not_guessed(self):
        model = om.get_storm_model()
        assert model.assess(self.PRE_MIGRATION) is None
        assert model.probability(self.PRE_MIGRATION) is None

    def test_a_zone_with_pressure_scores(self):
        features = dict(
            self.PRE_MIGRATION,
            pressure_min_3d_hpa=985.0,
            humidity_mean_3d_pct=92.0,
        )
        value = om.get_storm_model().probability(features)
        assert value is not None and 0.0 <= value <= 1.0

    def test_driver_share_is_a_share(self):
        """It is reported as a proportion, so it cannot exceed 1.0.

        Dividing the driver's contribution by the *net* movement away from the
        intercept produced 1.19 on the first live response, because the non-driver
        columns partly cancelled the driver. Both sides must count magnitude.
        """
        features = dict(
            self.PRE_MIGRATION,
            pressure_min_3d_hpa=985.0,
            humidity_mean_3d_pct=92.0,
        )
        assessment = om.get_storm_model().assess(features)
        assert assessment is not None
        assert 0.0 <= assessment.driver_share <= 1.0

        # And it is genuinely the driver's share, not just a clamped number:
        # adding up the per-feature magnitudes by hand must reproduce it.
        drivers = set(om.DRIVER_NAMES["storm"])
        total = sum(abs(v) for v in assessment.contributions.values())
        expected = sum(
            abs(v) for k, v in assessment.contributions.items() if k in drivers
        ) / total
        assert assessment.driver_share == pytest.approx(round(expected, 3))

    def test_pressure_is_near_inert_and_the_artifact_says_so(self):
        """The honest state of affairs after adding pressure: it earns almost
        nothing and its fitted sign is backwards. The score must not be allowed
        to imply a working cyclone signal it does not have, so this pins both
        halves -- the effect really is negligible, and the artifact names it.
        """
        artifact = json.loads(
            (om.ARTIFACT_DIR / om.ARTIFACTS["storm"]).read_text(encoding="utf-8")
        )
        weight = dict(zip(artifact["feature_columns"], artifact["coef"]))[
            "pressure_min_3d_hpa"
        ]
        scale = dict(zip(artifact["feature_columns"], artifact["scaler"]["scale"]))[
            "pressure_min_3d_hpa"
        ]
        # A 50 hPa swing is the depression -> category-1 gap, and must stay small.
        assert abs(weight) / scale * 50 < 0.15

        calm = dict(self.PRE_MIGRATION, pressure_min_3d_hpa=1020.0,
                    humidity_mean_3d_pct=70.0)
        deep = dict(self.PRE_MIGRATION, pressure_min_3d_hpa=970.0,
                    humidity_mean_3d_pct=70.0)
        model = om.get_storm_model()
        assert abs(model.probability(deep) - model.probability(calm)) < 0.05

        notes = " ".join(artifact["limitations"]).lower()
        assert "pressure" in notes
        assert "earn" in notes or "near zero" in notes

    def test_an_unusable_artifact_falls_back_instead_of_scoring(self):
        model = om.OccurrenceModel("storm", Path(os.devnull))
        assert model.available is False
        assert model.probability(self.PRE_MIGRATION) is None