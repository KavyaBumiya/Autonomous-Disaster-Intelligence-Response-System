"""Flood model training entry point. The implementation is now hazard-generic.

Kept as a module because the tests and the rebuild instructions import from
here. Every name below is an alias onto `ml.train`; there is no flood-specific
fitting code left in this file.

    python -m ml.train_flood_model
"""
from __future__ import annotations

from pathlib import Path

from ml import hazards as _hz
from ml import train as _train
from ml.flood_dataset import FEATURE_COLUMNS, LABEL_COLUMN, DEFAULT_CSV, SPEC
from ml.train import (
    CV_FOLDS,
    GROUP_CELL_DEGREES,
    IRLS_MAX_ITERATIONS,
    IRLS_TOLERANCE,
    L2_STRENGTH,
    Dataset,
    _standardise,
    average_precision,
    brier,
    fit_logistic,
    predict_proba,
    report_collinearity,
    roc_auc,
)

ARTIFACT_PATH = _train.artifact_path(SPEC)
MODEL_VERSION = _train.model_version(SPEC)


def load_dataset(path: Path | None = None) -> Dataset:
    return _train.load_dataset(SPEC, path)


def cross_validate(dataset: Dataset) -> dict[str, float]:
    return _train.cross_validate(SPEC, dataset)


def train(
    dataset_path: Path | None = None,
    artifact_path: Path | None = None,
    *,
    verbose: bool = True,
) -> dict:
    return _train.train(
        SPEC, dataset_path=dataset_path, out=artifact_path, verbose=verbose
    )


if __name__ == "__main__":  # pragma: no cover - offline entry point
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    train(dataset_path=args.data, artifact_path=args.out)
