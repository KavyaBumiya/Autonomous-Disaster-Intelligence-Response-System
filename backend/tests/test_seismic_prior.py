"""Tests for the USGS seismic background-rate prior.

Pure logic and a hand-built artifact, so nothing here touches the network or the
database. The shipped artifact is checked separately, at the bottom.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pytest

from app.ml import seismic_prior as sp
from ml import seismic_prior as build

# Vadodara -- where every configured zone sits, and deliberately the emptiest
# case in this file.
QUIET_LAT, QUIET_LNG = 22.31, 73.19
# Tokyo, to prove the rate is not a constant and that cells really are summed.
ACTIVE_LAT, ACTIVE_LNG = 35.68, 139.69


def _artifact(cells, **overrides) -> dict:
    # `cells` is a dict of records in most tests and a bare set of keys in the
    # "is it still valid" cases, so the catalogue count is only summed when the
    # records carry one.
    if isinstance(cells, dict):
        catalogue = sum(c["events"] for c in cells.values())
        stored = len(cells)
    else:
        catalogue, stored = 0, len(cells)
    base = {
        "model_id": "aegis-seismic-prior",
        "model_version": "usgs-comcat-rate-v1",
        "hazard": "seismic",
        "kind": "background_rate",
        "min_magnitude": 5.0,
        "years": 25.0,
        "cell_degrees": 0.5,
        "events_in_catalogue": catalogue,
        "cells_stored": stored,
        "cells": cells,
        "limitations": ["a limitation worth carrying"],
    }
    base.update(overrides)
    return base


def _cell_key(lat: float, lng: float) -> str:
    """The artifact key for the half-degree cell containing a point."""
    return f"{int(lat // 0.5)}:{int(lng // 0.5)}"


def _key(lat_index: int, lng_index: int) -> str:
    """The artifact key for a cell addressed by its indices."""
    return f"{lat_index}:{lng_index}"


def _record(events: int, peak: float = 6.0) -> dict:
    return {
        "events": events,
        "max_magnitude": peak,
        "events_per_year": events / 25.0,
        "m6_plus_events": 1,
    }


def _write(tmp_path: Path, artifact: dict) -> Path:
    path = tmp_path / "prior.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


class TestDegradation:
    """A missing or broken artifact must not take the endpoint down."""

    def test_a_missing_artifact_declines_rather_than_raising(self, tmp_path):
        prior = sp.SeismicPrior(tmp_path / "absent.json")
        assert prior.available is False
        assert prior.load_error
        assert prior.rate_per_year(QUIET_LAT, QUIET_LNG) is None
        assert prior.probability_in_window(QUIET_LAT, QUIET_LNG) is None
        assert prior.assess(QUIET_LAT, QUIET_LNG) is None

    def test_a_truncated_artifact_declines(self, tmp_path):
        # `occurrence_model` treats a hand-edited artifact as untrusted, and so
        # does this: a prior missing its year span would divide by zero.
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"model_version": "x", "cells": {}}), encoding="utf-8")
        prior = sp.SeismicPrior(path)
        assert prior.available is False
        assert "missing" in (prior.load_error or "")

    def test_a_non_positive_year_span_is_rejected(self, tmp_path):
        path = _write(tmp_path, _artifact({}, years=0.0))
        assert sp.SeismicPrior(path).available is False

    def test_info_reports_the_live_fallback_when_absent(self, tmp_path):
        info = sp.SeismicPrior(tmp_path / "absent.json").info()
        assert info["available"] is False
        assert "attenuation" in info["fallback"]


class TestRate:
    def test_events_in_range_are_summed(self, tmp_path):
        # Two cells either side of the query point, one well outside it.
        near = int(QUIET_LAT // 0.5)
        near_lng = int(QUIET_LNG // 0.5)
        artifact = _artifact(
            {
                _key(near, near_lng): _record(3, 6.2),
                _key(near, near_lng + 1): _record(4, 7.1),
                # ~2000 km away, must not be counted.
                _key(near + 40, near_lng): _record(99, 8.0),
            }
        )
        prior = sp.SeismicPrior(_write(tmp_path, artifact))
        events, cells, peak = prior.events_within(QUIET_LAT, QUIET_LNG, 100.0)
        assert events == 7
        assert cells == 2
        assert peak == 7.1

    def test_rate_divides_by_the_catalogue_span(self, tmp_path):
        artifact = _artifact({_cell_key(QUIET_LAT, QUIET_LNG): _record(5)}, years=25.0)
        prior = sp.SeismicPrior(_write(tmp_path, artifact))
        assert prior.rate_per_year(QUIET_LAT, QUIET_LNG, 100.0) == pytest.approx(0.2)

    def test_an_empty_region_reads_zero_not_missing(self, tmp_path):
        """No stored cells nearby is a real answer: the region is quiet.

        Returning None here would be indistinguishable from a broken artifact,
        and the caller would have to guess which it was looking at.
        """
        prior = sp.SeismicPrior(_write(tmp_path, _artifact({})))
        assert prior.rate_per_year(QUIET_LAT, QUIET_LNG, 100.0) == 0.0
        assert prior.probability_in_window(QUIET_LAT, QUIET_LNG) == 0.0

    def test_a_wider_radius_never_reports_fewer_events(self, tmp_path):
        base = int(QUIET_LNG // 0.5)
        cells = {_key(int(QUIET_LAT // 0.5), base + i): _record(2) for i in range(6)}
        prior = sp.SeismicPrior(_write(tmp_path, _artifact(cells)))
        counts = [
            prior.events_within(QUIET_LAT, QUIET_LNG, r)[0]
            for r in (10.0, 50.0, 100.0, 400.0, 2000.0)
        ]
        assert counts == sorted(counts)


class TestWindowProbability:
    def test_it_is_a_poisson_at_least_one_figure(self, tmp_path):
        import math

        artifact = _artifact({_cell_key(QUIET_LAT, QUIET_LNG): _record(25)}, years=25.0)
        prior = sp.SeismicPrior(_write(tmp_path, artifact))
        # 25 events in 25 years == 1/yr, so 12h is exp(-12/8760).
        expected = 1.0 - math.exp(-12.0 / 8760.0)
        assert prior.probability_in_window(QUIET_LAT, QUIET_LNG, 12.0) == pytest.approx(
            expected, rel=1e-6
        )

    def test_a_longer_window_is_never_less_likely(self, tmp_path):
        artifact = _artifact({_cell_key(QUIET_LAT, QUIET_LNG): _record(25)})
        prior = sp.SeismicPrior(_write(tmp_path, artifact))
        values = [
            prior.probability_in_window(QUIET_LAT, QUIET_LNG, h)
            for h in (1.0, 6.0, 12.0, 24.0, 72.0)
        ]
        assert values == sorted(values)
        assert all(0.0 <= v <= 1.0 for v in values)

    def test_a_very_active_region_stays_well_below_one(self, tmp_path):
        """Even a busy zone's 12-hour figure is small, which is the point.

        A number approaching 1.0 here would mean the rate is being presented as
        a forecast, and the whole module is built on not doing that.
        """
        base = int(ACTIVE_LNG // 0.5)
        cells = {
            _key(int(ACTIVE_LAT // 0.5), base + i): _record(500) for i in range(-2, 3)
        }
        prior = sp.SeismicPrior(_write(tmp_path, _artifact(cells, years=25.0)))
        probability = prior.probability_in_window(ACTIVE_LAT, ACTIVE_LNG, 12.0)
        assert 0.0 < probability < 0.2


class TestHonesty:
    """The caveats travel with the number, at every level it is exposed."""

    def test_assess_labels_the_figure_a_climatology_not_a_forecast(self, tmp_path):
        artifact = _artifact({_cell_key(QUIET_LAT, QUIET_LNG): _record(4)})
        result = sp.SeismicPrior(_write(tmp_path, artifact)).assess(QUIET_LAT, QUIET_LNG)
        assert result is not None
        assert result["is_prediction"] is False
        assert "not a forecast" in result["interpretation"]
        assert "Long-run rate" in result["interpretation"]

    def test_assess_carries_the_artifact_limitations(self, tmp_path):
        prior = sp.SeismicPrior(_write(tmp_path, _artifact({})))
        result = prior.assess(QUIET_LAT, QUIET_LNG)
        assert result["limitations"] == ["a limitation worth carrying"]

    def test_info_also_says_it_is_not_a_prediction(self, tmp_path):
        info = sp.SeismicPrior(_write(tmp_path, _artifact({}))).info()
        assert info["is_prediction"] is False
        assert info["limitations"]

    def test_assess_reports_the_magnitude_floor_it_counted_above(self, tmp_path):
        artifact = _artifact({}, min_magnitude=4.5)
        result = sp.SeismicPrior(_write(tmp_path, artifact)).assess(QUIET_LAT, QUIET_LNG)
        assert result["min_magnitude"] == 4.5
        assert "M4.5+" in result["interpretation"]


class TestBuilder:
    def test_a_quake_is_binned_into_its_half_degree_cell(self):
        assert build.cell_key(22.31, 73.19) == build.cell_key(22.34, 73.24)
        assert build.cell_key(22.31, 73.19) != build.cell_key(22.81, 73.19)

    def test_omitting_sparse_cells_is_recorded_as_a_limitation(self):
        # A cell with one event is not a rate. Dropping it silently would make
        # the artifact look complete when it is not.
        quakes = [
            build.Quake(10.0, 10.0, 5.5, date(2020, 1, 1)),
            build.Quake(10.0, 10.0, 5.6, date(2021, 1, 1)),
            build.Quake(-30.0, -70.0, 5.1, date(2022, 1, 1)),  # lonely cell
        ]
        prior = build.build_prior(quakes, years=25.0, min_magnitude=5.0)
        assert prior["events_in_catalogue"] == 3
        assert prior["events_in_stored_cells"] == 2
        assert any("omitted" in note for note in prior["limitations"])

    def test_peak_magnitude_is_tracked_per_cell(self):
        quakes = [
            build.Quake(10.0, 10.0, 5.5, date(2020, 1, 1)),
            build.Quake(10.0, 10.0, 7.8, date(2021, 1, 1)),
            build.Quake(10.0, 10.0, 6.1, date(2021, 6, 1)),
        ]
        prior = build.build_prior(quakes, years=25.0, min_magnitude=5.0)
        (record,) = prior["cells"].values()
        assert record["max_magnitude"] == 7.8
        assert record["events"] == 3
        assert record["m6_plus_events"] == 2

    def test_the_built_limitations_name_the_three_real_caveats(self):
        prior = build.build_prior([], years=25.0, min_magnitude=5.0)
        notes = " ".join(prior["limitations"]).lower()
        assert "long-run rate" in notes
        assert "decluster" in notes
        assert "m5.0+" in notes


class TestShippedArtifact:
    """Checks against the artifact that actually ships."""

    def _prior(self) -> sp.SeismicPrior:
        assert sp.ARTIFACT_PATH.exists(), "run `python -m ml.seismic_prior`"
        return sp.get_seismic_prior()

    def test_the_shipped_artifact_loads(self):
        prior = self._prior()
        assert prior.available, prior.load_error

    def test_it_came_from_a_real_catalogue(self):
        info = self._prior().info()
        assert info["events_in_catalogue"] > 10_000
        assert info["cells_stored"] > 1_000
        assert info["years"] > 20.0
        assert "USGS" in info["source"]

    def test_the_magnitude_floor_is_at_least_five(self):
        # Below M5 the catalogue is dominated by local network detections, so
        # the "rate" would largely measure instrumentation.
        assert self._prior().info()["min_magnitude"] >= 5.0

    def test_it_discriminates_between_quiet_and_active_regions(self):
        prior = self._prior()
        quiet = prior.rate_per_year(QUIET_LAT, QUIET_LNG, 100.0)
        active = prior.rate_per_year(ACTIVE_LAT, ACTIVE_LNG, 100.0)
        assert active > 5.0
        assert quiet is not None
        assert active > quiet * 10

    def test_the_deployed_zones_are_recorded_as_quiet(self):
        """The honest headline: Gujarat has no M5+ history in this window.

        Pinned so that if the catalogue or the floor ever changes, the claim that
        these zones read zero has to be re-examined rather than quietly drifting.
        """
        prior = self._prior()
        for lat, lng in ((22.30, 73.19), (22.31, 73.19), (20.10, 75.10)):
            assert prior.events_within(lat, lng, 100.0)[0] == 0
            assert prior.rate_per_year(lat, lng, 100.0) == 0.0
            assert prior.probability_in_window(lat, lng, 12.0) == 0.0
