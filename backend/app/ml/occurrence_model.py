"""Runtime loader for the trained hazard-occurrence models.

Each artifact is a JSON document produced by `ml/train.py` holding standardised
coefficients plus the provenance and limitations of the fit. This module only
evaluates them, and does so with the standard library alone.

Three properties matter more than speed here.

First, the models must never be load-bearing. If an artifact is missing,
truncated, hand-edited into an invalid state, or built from a different feature
set than this module expects, `probability()` returns None and the caller falls
back to the arithmetic rule. A corrupt artifact degrades the forecast; it does
not break it.

Second, every number an artifact claims must stay attached to it. The
limitations are as much a part of a model as its coefficients -- the fitted
prior reflects a sampling frame rather than field incidence, and one of these
models is measurably weaker than a single weather reading -- so they are
surfaced through the API rather than left in a file nobody reads.

Third, the model is only offered a feature the runtime can actually observe.
A feature the poller does not store would be reported as missing, and
`assess()` would return None on every call: a model that can never fire.
"""
from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"

# Guard rails for a hand-edited or truncated artifact.
MAX_INTERCEPT = 50.0
MAX_COEFFICIENT = 50.0

#: Hazard key -> artifact filename.
ARTIFACTS: dict[str, str] = {
    "flood": "flood_lr_v1.json",
    "fire": "fire_lr_v1.json",
    "storm": "storm_lr_v1.json",
}

#: Human-readable driver names, used for the XAI share. Anything not listed
#: simply does not contribute to that particular share.
DRIVER_NAMES: dict[str, tuple[str, ...]] = {
    "flood": ("peak_precip_3d_mm", "precip_10d_mm"),
    "fire": ("dry_spell_days", "precip_30d_mm", "temp_max_mean_7d_c"),
    "storm": ("wind_max_3d_kmh", "pressure_min_3d_hpa", "precip_3d_mm"),
}

DRIVER_LABELS: dict[str, str] = {
    "flood": "rainfall",
    "fire": "fuel dryness and heat",
    "storm": "pressure, wind and rain",
}


@dataclass(frozen=True)
class OccurrenceAssessment:
    """One scored hazard-occurrence estimate, with its reasoning attached."""

    hazard: str
    probability: float
    model_id: str
    model_version: str
    features: dict[str, float]
    contributions: dict[str, float]
    #: Share of the decision attributable to the hazard's own driver, i.e. the
    #: sum of those contributions over the total movement in logit.
    driver_share: float
    #: False when a single obvious measurement scores better than this model.
    beats_single_feature: bool

    def explain(self) -> str:
        ordered = sorted(
            self.contributions.items(), key=lambda item: abs(item[1]), reverse=True
        )
        parts = [
            f"{name.replace('_', ' ')} {value:+.2f}" for name, value in ordered[:3]
        ]
        return (
            f"{self.model_version}: {self.probability * 100:.0f}% {self.hazard} "
            f"occurrence (driven by {', '.join(parts)})"
        )


class OccurrenceModel:
    """Evaluates one fitted logistic model."""

    def __init__(self, hazard: str, path: Path | None = None) -> None:
        if hazard not in ARTIFACTS:
            raise KeyError(f"no artifact registered for hazard {hazard!r}")
        self.hazard = hazard
        self._path = path or (ARTIFACT_DIR / ARTIFACTS[hazard])
        self._lock = threading.Lock()
        self._artifact: dict[str, Any] | None = None
        self._load_error: str | None = None
        self._load_failed = False

    # ── Loading ──────────────────────────────────────────────────────────

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, Any] | None:
        if self._artifact is not None:
            return self._artifact
        with self._lock:
            if self._artifact is not None or self._load_failed:
                return self._artifact

            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._validate(raw)
            except FileNotFoundError:
                self._load_error = f"artifact not found at {self._path}"
                self._load_failed = True
                logger.warning("occurrence_model_missing", hazard=self.hazard, path=str(self._path))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._load_error = f"artifact unusable: {exc}"
                self._load_failed = True
                logger.warning(
                    "occurrence_model_unusable", hazard=self.hazard, error=str(exc)
                )
            else:
                self._artifact = raw
                logger.info(
                    "occurrence_model_loaded",
                    hazard=self.hazard,
                    version=raw.get("model_version"),
                    trained_at=raw.get("trained_at"),
                )
            return self._artifact

    @staticmethod
    def _validate(raw: dict[str, Any]) -> None:
        """Reject an artifact that cannot be trusted to score with."""
        for key in ("feature_columns", "scaler", "coef", "intercept", "model_version"):
            if key not in raw:
                raise ValueError(f"missing '{key}'")
        if len(raw["coef"]) != len(raw["feature_columns"]):
            raise ValueError("coef length does not match feature_columns")
        for key in ("mean", "scale"):
            if len(raw["scaler"][key]) != len(raw["feature_columns"]):
                raise ValueError(f"scaler.{key} length does not match feature_columns")
        values = [*raw["coef"], raw["intercept"]]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            raise ValueError("non-finite coefficients")
        if any(abs(v) > MAX_COEFFICIENT for v in values):
            raise ValueError(
                f"coefficient magnitude exceeds {MAX_COEFFICIENT}; refusing to score"
            )
        scales = raw["scaler"]["scale"]
        if any(not isinstance(s, (int, float)) or s <= 0 for s in scales):
            raise ValueError("non-positive scaler value")

    # ── Introspection ────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._load() is not None

    @property
    def load_error(self) -> str | None:
        self._load()
        return self._load_error

    def info(self) -> dict[str, Any]:
        artifact = self._load()
        if artifact is None:
            return {
                "available": False,
                "hazard": self.hazard,
                "reason": self._load_error or "not loaded",
                "fallback": "rules-baseline",
            }
        metrics = artifact.get("metrics", {})
        return {
            "available": True,
            "hazard": artifact.get("hazard", self.hazard),
            "model_id": artifact.get("model_id"),
            "model_version": artifact.get("model_version"),
            "trained_at": artifact.get("trained_at"),
            "target": artifact.get("target"),
            "question": artifact.get("question"),
            "feature_columns": artifact.get("feature_columns"),
            "metrics": metrics,
            "strength": metrics.get("strength", "unknown"),
            "beats_single_feature": bool(metrics.get("beats_single_feature", True)),
            "training_data": artifact.get("training_data", {}),
            "limitations": artifact.get("limitations", []),
            "runtime": "pure-python logistic evaluation (no ML runtime dependency)",
        }

    # ── Scoring ──────────────────────────────────────────────────────────

    def training_mean(self, feature: str) -> float | None:
        """Training-set mean of one feature.

        For inputs the database does not hold (elevation), substituting the
        training mean makes the feature contribute nothing to the logit, which
        is the neutral choice: an invented value would not.
        """
        artifact = self._load()
        if artifact is None:
            return None
        names: list[str] = artifact["feature_columns"]
        means = artifact["scaler"]["mean"]
        if feature not in names:
            return None
        index = names.index(feature)
        return float(means[index]) if index < len(means) else None

    def probability(self, features: dict[str, float]) -> float | None:
        """Occurrence probability for a feature dict, or None when unusable."""
        result = self.assess(features)
        return None if result is None else result.probability

    def assess(self, features: dict[str, float]) -> OccurrenceAssessment | None:
        artifact = self._load()
        if artifact is None:
            return None

        names: list[str] = artifact["feature_columns"]
        mean = artifact["scaler"]["mean"]
        scale = artifact["scaler"]["scale"]
        coef = artifact["coef"]

        contributions: dict[str, float] = {}
        z = float(artifact["intercept"])
        for index, name in enumerate(names):
            raw_value = features.get(name)
            if raw_value is None or not math.isfinite(float(raw_value)):
                # A missing feature is not a zero feature; scoring it as zero
                # would state a confident answer built on absent data.
                logger.warning(
                    "occurrence_model_feature_missing", hazard=self.hazard, feature=name
                )
                return None
            standardised = (float(raw_value) - float(mean[index])) / float(scale[index])
            contribution = float(coef[index]) * standardised
            contributions[name] = round(contribution, 4)
            z += contribution

        probability = 1.0 / (1.0 + math.exp(-z)) if z >= -700 else 0.0

        drivers = DRIVER_NAMES.get(self.hazard, ())
        driver_total = sum(
            abs(value) for name, value in contributions.items() if name in drivers
        )
        # Denominator is the total absolute contribution, not the net movement
        # away from the intercept. Net movement is smaller than the driver's own
        # contribution whenever the other columns pull the other way, which made
        # this "share" exceed 1.0 -- 1.19 in the first live response this ran in.
        # A share is bounded by construction when both sides count magnitude.
        total = sum(abs(value) for value in contributions.values())
        driver_share = driver_total / total if total > 1e-9 else 0.0

        metrics = artifact.get("metrics", {})
        return OccurrenceAssessment(
            hazard=self.hazard,
            probability=round(min(1.0, max(0.0, probability)), 4),
            model_id=str(artifact.get("model_id", "aegis-occurrence-logistic")),
            model_version=str(artifact.get("model_version", "unknown")),
            features={name: float(features[name]) for name in names},
            contributions=contributions,
            driver_share=round(driver_share, 3),
            beats_single_feature=bool(metrics.get("beats_single_feature", True)),
        )


# ── Singletons ────────────────────────────────────────────────────────────


@lru_cache(maxsize=None)
def get_occurrence_model(hazard: str) -> OccurrenceModel:
    return OccurrenceModel(hazard)


def get_flood_model() -> OccurrenceModel:
    return get_occurrence_model("flood")


def get_fire_model() -> OccurrenceModel:
    return get_occurrence_model("fire")


def get_storm_model() -> OccurrenceModel:
    return get_occurrence_model("storm")


def available_models() -> dict[str, bool]:
    """Which registered hazards have a usable artifact right now."""
    return {key: get_occurrence_model(key).available for key in ARTIFACTS}


def reset_occurrence_model_cache() -> None:
    """Drop the cached singletons so a new artifact path is picked up."""
    get_occurrence_model.cache_clear()
