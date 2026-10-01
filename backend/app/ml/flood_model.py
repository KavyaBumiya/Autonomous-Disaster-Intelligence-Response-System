"""Flood model entry point. The implementation is now hazard-generic.

Kept as a module because `prediction_engine`, the tests and the rebuild
instructions import from here. The types below are aliases onto
`app.ml.occurrence_model`; `FloodModel` is retained as a name because a flood
model is still a flood model, it just is not the only one any more.

    python -m ml.train_flood_model
"""
from __future__ import annotations

from pathlib import Path

from app.ml.occurrence_model import ARTIFACT_DIR as _ARTIFACT_DIR
from app.ml.occurrence_model import (
    DRIVER_LABELS,
    OccurrenceAssessment as FloodAssessment,
    OccurrenceModel as _OccurrenceModel,
    get_occurrence_model,
)
from app.ml.occurrence_model import (
    get_flood_model,
    reset_occurrence_model_cache as _reset,
)

FLOOD_ARTIFACT = _ARTIFACT_DIR / "flood_lr_v1.json"
ARTIFACT_DIR = _ARTIFACT_DIR

#: The flood model's own driver columns, kept for the XAI share.
RAINFALL_FEATURES = ("peak_precip_3d_mm", "precip_10d_mm")


def FloodModel(path: Path | None = None) -> _OccurrenceModel:  # noqa: N802
    """The flood occurrence model. Prefer `get_flood_model()` for the cached one."""
    return _OccurrenceModel("flood", path)


def reset_flood_model_cache() -> None:
    """Drop the cached singletons so a new artifact path is picked up."""
    _reset()


__all__ = [
    "FLOOD_ARTIFACT",
    "FloodAssessment",
    "FloodModel",
    "RAINFALL_FEATURES",
    "get_flood_model",
    "reset_flood_model_cache",
]
