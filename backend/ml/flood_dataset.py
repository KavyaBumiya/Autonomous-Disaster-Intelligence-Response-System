"""Flood dataset entry point. The implementation is now hazard-generic.

Kept as a module because `ml/train_flood_model.py`, the tests and the rebuild
instructions all import from here. Every name below is a thin alias onto
`ml.hazards` / `ml.occurrence_dataset`; there is no flood-specific logic left in
this file, which is the point -- flood is now just the first hazard spec.

    python -m ml.flood_dataset
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from ml import hazards as _hz
from ml import occurrence_dataset as _od
from ml.hazards import (
    ARCHIVE_LAG_DAYS,
    DRY_DAY_MM,
    NEGATIVE_EXCLUSION_DAYS,
    PEAK_WINDOW_DAYS,
    FLOOD as _FLOOD_SPEC,
)

SPEC = _FLOOD_SPEC

FEATURE_COLUMNS = SPEC.feature_columns
LABEL_COLUMN = SPEC.target
DEFAULT_CSV = _od.default_csv(SPEC)

FloodRecord = _od.EventRecord
Sample = _od.Sample

GDACS_API = _od.GDACS_API
OPEN_METEO_ARCHIVE = _od.OPEN_METEO_ARCHIVE
USER_AGENT = _od.USER_AGENT
BACKEND_ROOT = _od.BACKEND_ROOT

FLOOD_EVENTTYPE = SPEC.gdacs_eventtype
# The flood window is ten days; kept as a name because the runtime mirrors it.
ANTECEDENT_DAYS = SPEC.antecedent_days
LOCATIONS_PER_REQUEST = _hz.LOCATIONS_PER_REQUEST

fetch_events = _od.fetch_events
fetch_flood_events = _od.fetch_events
sample_negatives = _od.sample_negatives
fetch_features = _od.fetch_features
fetch_rainfall_features = _od.fetch_features
build_dataset = _od.build_dataset

_safe_float = _hz._safe_float


def _extract_features(entry: dict[str, Any], day: date) -> dict[str, float] | None:
    """Flood antecedent-rainfall features for one Open-Meteo daily block."""
    return SPEC.extract(entry, day, SPEC.antecedent_days)


def main(argv: list[str] | None = None) -> None:
    _od.main(["flood", *(argv or [])])


if __name__ == "__main__":  # pragma: no cover - offline entry point
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--negative-ratio", type=int, default=2)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    build_dataset(
        SPEC,
        start_year=args.start_year,
        end_year=args.end_year,
        negative_ratio=args.negative_ratio,
        out_path=args.out,
    )
