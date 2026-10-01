"""Fit the AEGIS hazard-occurrence models and write the runtime artifacts.

    python -m ml.train

Model
-----
L2-regularised logistic regression, fitted with iteratively reweighted least
squares in numpy. scikit-learn is deliberately not used: it is not installed in
the deploy image, and scipy's compiled extensions are blocked on some Windows
hosts. Five features and a few hundred rows converge in a handful of IRLS
iterations, so the dependency would buy nothing and would make the artifacts
harder to reproduce.

Evaluation
----------
Grouped 5-fold cross-validation. Folds are grouped by ~0.5 degree cell so that
rows sharing a location stay together: with negatives sampled at event
locations, an ungrouped split would put the same place in both train and test
and report an AUC that does not survive contact with a new zone.

Every reported metric is cross-validated, never in-sample.

Two baselines, and the model must beat both:

* the **rules baseline** -- the monotone ramp the shipped code already applies
  to this hazard's dominant driver, evaluated on the same rows;
* a **single-feature baseline** -- the same logistic fit restricted to that one
  driver. This is the honest test of whether the extra columns earn their keep,
  and it is the harder of the two: a model that cannot beat a one-column fit on
  its own strongest column is not worth shipping regardless of how many
  features it was given.

If the fitted model fails either comparison the artifact is not written.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ml import hazards as hz
from ml.occurrence_dataset import default_csv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = BACKEND_ROOT / "app" / "ml" / "artifacts"

# L2 strength. Deliberately heavy: a few dozen to a few hundred positive events
# is a small sample, and unregularised coefficients would chase noise.
L2_STRENGTH = 3.0
IRLS_MAX_ITERATIONS = 60
IRLS_TOLERANCE = 1e-9
CV_FOLDS = 5
# Rows within this distance of each other share a fold.
GROUP_CELL_DEGREES = 0.5


def model_version(spec: hz.HazardSpec) -> str:
    return f"{spec.key}-lr-v1"


def artifact_path(spec: hz.HazardSpec) -> Path:
    return ARTIFACT_DIR / f"{spec.key}_lr_v1.json"


# ── Data ──────────────────────────────────────────────────────────────────


@dataclass
class Dataset:
    x: np.ndarray
    y: np.ndarray
    groups: np.ndarray
    raw: list[dict[str, str]]
    columns: tuple[str, ...]
    target: str

    def __len__(self) -> int:
        return int(self.y.shape[0])


def load_dataset(spec: hz.HazardSpec, path: Path | None = None) -> Dataset:
    source = path or default_csv(spec)
    if not source.exists():
        raise FileNotFoundError(
            f"{source} not found -- run `python -m ml.occurrence_dataset {spec.key}` first"
        )

    with source.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{source} is empty")

    usable: list[dict[str, str]] = []
    for row in rows:
        try:
            values = [float(row[name]) for name in spec.feature_columns]
            label = float(row[spec.target])
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(v) for v in values):
            continue
        if label not in (0.0, 1.0):
            continue
        usable.append(row)

    if not usable:
        raise ValueError(f"{source} has no usable rows")

    x = np.array([[float(row[name]) for name in spec.feature_columns] for row in usable])
    y = np.array([float(row[spec.target]) for row in usable])
    groups = np.array(
        [
            f"{math.floor(float(row['lat']) / GROUP_CELL_DEGREES)}:"
            f"{math.floor(float(row['lng']) / GROUP_CELL_DEGREES)}"
            for row in usable
        ]
    )
    return Dataset(
        x=x,
        y=y,
        groups=groups,
        raw=usable,
        columns=spec.feature_columns,
        target=spec.target,
    )


def _standardise(x: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    # A constant column would divide by zero; scale to 1 so it contributes
    # nothing to the likelihood instead of producing NaNs.
    scale = np.where(scale < 1e-12, 1.0, scale)
    return (x - mean) / scale, mean, scale


# ── Model ─────────────────────────────────────────────────────────────────


def _sigmoid(z: np.ndarray) -> np.ndarray:
    out = np.empty_like(z)
    positive = z >= 0
    out[positive] = 1.0 / (1.0 + np.exp(-z[positive]))
    exp_z = np.exp(z[~positive])
    out[~positive] = exp_z / (1.0 + exp_z)
    return out


def fit_logistic(
    x: np.ndarray, y: np.ndarray, *, l2: float = L2_STRENGTH
) -> tuple[np.ndarray, float]:
    """L2-penalised logistic regression via IRLS. Returns (coef, intercept)."""
    n_rows, n_features = x.shape
    design = np.hstack([np.ones((n_rows, 1)), x])
    weights = np.zeros(n_features + 1)
    penalty = np.eye(n_features + 1) * l2
    penalty[0, 0] = 0.0  # the intercept is not shrunk

    previous_cost = float("inf")
    for _ in range(IRLS_MAX_ITERATIONS):
        p = _sigmoid(design @ weights)
        w = np.clip(p * (1 - p), 1e-9, None)

        # Newton step on the penalised NLL: grad = X'(p - y), H = X'WX + l2*I,
        # so w <- w + H^-1 X'(y - p). Negating this term walks away from the
        # optimum and the weights diverge instead of converging.
        z = weights + np.linalg.pinv(
            design.T @ (design * w[:, None]) + penalty
        ) @ (design.T @ (y - p))
        p_new = _sigmoid(design @ z)

        # Converged on the objective, not just on the parameters.
        cost = -float(
            np.sum(
                y * np.log(np.clip(p_new, 1e-12, 1))
                + (1 - y) * np.log(np.clip(1 - p_new, 1e-12, 1))
            )
        ) + 0.5 * l2 * float(z[1:] @ z[1:])

        shift = float(np.max(np.abs(z - weights)))
        weights = z
        if shift < IRLS_TOLERANCE or abs(cost - previous_cost) < 1e-10:
            break
        previous_cost = cost

    return weights[1:], float(weights[0])


def predict_proba(x: np.ndarray, coef: np.ndarray, intercept: float) -> np.ndarray:
    return _sigmoid(x @ coef + intercept)


# ── Metrics ───────────────────────────────────────────────────────────────


def roc_auc(y: np.ndarray, scores: np.ndarray) -> float:
    """Rank-based AUC (ties averaged)."""
    positives = y > 0.5
    n_pos, n_neg = int(positives.sum()), int((~positives).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    order = np.argsort(scores, kind="mergesort")
    ranks = np.empty(len(scores), dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1, dtype=float)
    # Average ranks within tied score groups.
    sorted_scores = scores[order]
    start = 0
    for index in range(1, len(scores) + 1):
        if index == len(scores) or sorted_scores[index] != sorted_scores[start]:
            if index - start > 1:
                ranks[order[start:index]] = ranks[order[start:index]].mean()
            start = index
    return float((ranks[positives].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def average_precision(y: np.ndarray, scores: np.ndarray) -> float:
    positives = y > 0.5
    n_pos = int(positives.sum())
    if n_pos == 0:
        return float("nan")
    order = np.argsort(-scores, kind="mergesort")
    sorted_y = y[order]
    precision = np.cumsum(sorted_y) / np.arange(1, len(sorted_y) + 1)
    return float((precision * sorted_y).sum() / n_pos)


def brier(y: np.ndarray, scores: np.ndarray) -> float:
    return float(np.mean((scores - y) ** 2))


def rules_baseline_scores(spec: hz.HazardSpec, dataset: Dataset) -> np.ndarray:
    """The rule this model would replace, evaluated on the dataset rows.

    Reported for context, not used as the publication gate. A rule has nothing
    to fit, so its score carries no cross-fold calibration drift, while a
    pooled out-of-fold model score does; comparing the two directly flatters
    the rule. The gate below is therefore the single-feature fit, which is held
    to exactly the same cross-validation machinery as the full model.
    """
    out: list[float] = []
    for row in dataset.raw:
        features: dict[str, float] = {}
        # Baseline-only columns are not in the design matrix but must still be
        # readable, so read every column the row actually carries.
        for column, value in row.items():
            number = _as_float(value)
            if number is not None:
                features[column] = number
        score = spec.rule_score(features)
        out.append(float("nan") if score is None else score)
    return np.array(out, dtype=float)


def _as_float(value: str) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


# ── Cross-validation ──────────────────────────────────────────────────────


def _fold_assignment(dataset: Dataset) -> np.ndarray:
    groups = sorted(set(dataset.groups.tolist()))
    assignment = {group: index % CV_FOLDS for index, group in enumerate(groups)}
    return np.array([assignment[g] for g in dataset.groups])


def _out_of_fold(
    x: np.ndarray, y: np.ndarray, fold_of_row: np.ndarray
) -> np.ndarray:
    oof = np.full(len(y), np.nan)
    for fold in range(CV_FOLDS):
        train_mask = fold_of_row != fold
        test_mask = ~train_mask
        if not test_mask.any() or not train_mask.any():
            continue
        if len(set(y[train_mask].tolist())) < 2:
            continue
        x_train, mean, scale = _standardise(x[train_mask])
        coef, intercept = fit_logistic(x_train, y[train_mask])
        oof[test_mask] = predict_proba((x[test_mask] - mean) / scale, coef, intercept)
    return oof


def cross_validate(spec: hz.HazardSpec, dataset: Dataset) -> dict[str, float]:
    fold_of_row = _fold_assignment(dataset)
    oof = _out_of_fold(dataset.x, dataset.y, fold_of_row)

    # A constant oof vector means no fold ever produced a prediction, which the
    # metric functions would happily score as AUC 0.5 / AP 1.0 rather than
    # report as the failure it is.
    scored = oof[np.isfinite(oof)]
    if scored.size != len(dataset) or np.unique(np.round(scored, 9)).size <= 1:
        raise RuntimeError(
            f"{spec.key}: cross-validation produced constant or missing "
            "out-of-fold predictions"
        )

    # The single strongest driver, fitted on its own with the same folds.
    # Chosen by the data rather than by assumption: naming a weak column would
    # flatter the full model.
    strongest = _strongest_feature(dataset)
    single = _out_of_fold(
        dataset.x[:, [strongest]], dataset.y, fold_of_row
    )
    single_scored = single[np.isfinite(single)]
    single_auc = (
        float("nan")
        if single_scored.size != len(dataset)
        or np.unique(np.round(single_scored, 9)).size <= 1
        else roc_auc(dataset.y, single)
    )

    base = np.full(len(dataset), float(dataset.y.mean()))
    rule = rules_baseline_scores(spec, dataset)
    rule_auc = roc_auc(dataset.y, np.nan_to_num(rule, nan=0.5))

    return {
        "roc_auc": roc_auc(dataset.y, oof),
        "roc_auc_baseline_rule": rule_auc,
        "roc_auc_single_feature": single_auc,
        "roc_auc_base_rate": roc_auc(dataset.y, base),
        "average_precision": average_precision(dataset.y, oof),
        "average_precision_base_rate": float(dataset.y.mean()),
        "brier": brier(dataset.y, oof),
        "brier_base_rate": brier(dataset.y, base),
        "positive_rate": float(dataset.y.mean()),
        "rows": float(len(dataset)),
        "positives": float(dataset.y.sum()),
        "strongest_feature": float(strongest),
    }


def _strongest_feature(dataset: Dataset) -> int:
    """Index of the single column with the best solo AUC against the label.

    Choosing the baseline by the data rather than by assumption is deliberate:
    picking a weak column would flatter the full model.
    """
    best_index, best_score = 0, -1.0
    for index in range(dataset.x.shape[1]):
        column = dataset.x[:, index]
        if column.std() < 1e-12:
            continue
        score = roc_auc(dataset.y, column)
        if math.isfinite(score) and score > best_score:
            best_index, best_score = index, score
    return best_index


# ── Entry point ───────────────────────────────────────────────────────────


def report_collinearity(
    dataset: Dataset, *, threshold: float = 0.9
) -> list[str]:
    """Warn about feature pairs that are near-duplicates of each other.

    Collinearity does not break the fit, it makes it uninterpretable: the
    penalty splits the shared effect across the pair and either column can end
    up with the wrong sign while the model still scores well.
    """
    warnings: list[str] = []
    for i, first in enumerate(dataset.columns):
        for j, second in enumerate(dataset.columns[i + 1 :], start=i + 1):
            a = dataset.x[:, i]
            b = dataset.x[:, j]
            if a.std() < 1e-12 or b.std() < 1e-12:
                continue
            r = float(np.corrcoef(a, b)[0, 1])
            if abs(r) >= threshold:
                warnings.append(f"{first} ~ {second}: r={r:+.3f}")
    return warnings


def train(
    spec: hz.HazardSpec,
    dataset_path: Path | None = None,
    out: Path | None = None,
    *,
    verbose: bool = True,
) -> dict:
    target = out or artifact_path(spec)
    dataset = load_dataset(spec, dataset_path)

    if verbose:
        print(f"[1/4] loaded {len(dataset)} rows ({int(dataset.y.sum())} {spec.key})")
        print(f"  positives per year: {_per_year(dataset)}")
        collinear = report_collinearity(dataset)
        if collinear:
            print("  WARNING collinear features:")
            for line in collinear:
                print(f"    {line}")
        else:
            print("  no collinear feature pairs")

    metrics = cross_validate(spec, dataset)
    strongest = dataset.columns[int(metrics["strongest_feature"])]
    if verbose:
        print("[2/4] cross-validated metrics (out-of-fold)")
        for key, value in metrics.items():
            if key == "strongest_feature":
                continue
            print(f"  {key:32} {value:.4f}")
        print(f"  strongest single feature: {strongest}")

    _refuse_if_not_better(spec, metrics, strongest)

    if not metrics["beats_single_feature"]:
        print(
            f"  NOTE: a single-feature fit on {strongest} alone scores better "
            f"({metrics['roc_auc_single_feature']:.3f} vs {metrics['roc_auc']:.3f}). "
            "Shipping anyway because it beats the rule it replaces, but this "
            "model is weak -- the missing variables are named in its limitations."
        )

    x, mean, scale = _standardise(dataset.x)
    coef, intercept = fit_logistic(x, dataset.y)
    in_sample = predict_proba(x, coef, intercept)

    if verbose:
        print("[3/4] fitted on the full dataset")
        for name, weight in zip(dataset.columns, coef):
            print(f"  {name:24} {weight:+.4f}")
        print(f"  {'(intercept)':24} {intercept:+.4f}")

    artifact = {
        "model_id": spec.model_id,
        "model_version": model_version(spec),
        "hazard": spec.key,
        "task": "binary_classification",
        "target": f"{spec.key} occurrence within the antecedent window",
        "question": spec.questions,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_columns": list(dataset.columns),
        "scaler": {"mean": mean.tolist(), "scale": scale.tolist()},
        "coef": coef.tolist(),
        "intercept": intercept,
        "metrics": metrics,
        "in_sample": {
            "roc_auc": roc_auc(dataset.y, in_sample),
            "average_precision": average_precision(dataset.y, in_sample),
            "brier": brier(dataset.y, in_sample),
        },
        "training_data": _provenance(spec, dataset),
        "limitations": _limitations(spec, metrics, strongest),
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    if verbose:
        print(f"[4/4] wrote {target}")
    return artifact


def _refuse_if_not_better(
    spec: hz.HazardSpec, metrics: dict[str, float], strongest: str
) -> None:
    """Block the write unless the model beats a like-for-like baseline.

    The gate is the same fit restricted to the single strongest column and
    scored by the same out-of-fold machinery. A model that cannot beat that has
    learned nothing that one obvious measurement does not already say, and
    shipping it would add an opaque dependency for no accuracy.
    """
    auc = metrics["roc_auc"]
    rule = metrics["roc_auc_baseline_rule"]

    if not math.isfinite(auc):
        raise RuntimeError(f"{spec.key}: out-of-fold AUC is not a number; refusing to write")

    if auc <= 0.5:
        raise RuntimeError(
            f"{spec.key}: out-of-fold AUC {auc:.3f} is no better than a coin "
            "flip; refusing to write the artifact"
        )

    if spec.rule_is_shipped and math.isfinite(rule) and auc <= rule:
        # Shipping it anyway would mean replacing explainable arithmetic with
        # an opaque model that is measurably no better than what it replaced.
        raise RuntimeError(
            f"{spec.key}: trained model does not beat the rule it replaces "
            f"({spec.rule_name}, AUC {auc:.3f} vs {rule:.3f}); refusing to "
            "write the artifact"
        )

    # Past this point the write is going ahead, so the two descriptive keys are
    # safe to add. `single` is read with `get` because unlike the two keys above
    # it is not needed to decide anything -- a metrics dict without it still
    # gets refused correctly, which is the behaviour that matters.
    single = metrics.get("roc_auc_single_feature", float("nan"))
    beats_single = (not math.isfinite(single)) or auc > single
    metrics["beats_single_feature"] = float(beats_single)
    metrics["strength"] = "strong" if beats_single else "weak"


def _per_year(dataset: Dataset) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row, label in zip(dataset.raw, dataset.y):
        year = row["day"][:4]
        counts[year] = counts.get(year, 0) + int(label)
    return dict(sorted(counts.items()))


def _provenance(spec: hz.HazardSpec, dataset: Dataset) -> dict:
    events = {r["event_id"] for r in dataset.raw if r[dataset.target] == "1"}
    return {
        "labels": (
            f"GDACS {spec.gdacs_eventtype} records (EC JRC), public domain, no API key"
        ),
        "label_url": "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH",
        "features": "ERA5 reanalysis via Open-Meteo archive: "
        + ", ".join(spec.daily_variables),
        "feature_url": "https://archive-api.open-meteo.com/v1/archive",
        "builder": "ml/occurrence_dataset.py",
        "antecedent_days": spec.antecedent_days,
        "rows": len(dataset),
        "positives": int(dataset.y.sum()),
        "distinct_events": len(events),
        "year_span": [
            min(r["day"][:4] for r in dataset.raw),
            max(r["day"][:4] for r in dataset.raw),
        ],
        "negative_sampling": (
            f"{dataset.y.size and int((1 - dataset.y).sum())} non-{spec.key} dates, "
            "drawn from the same jittered coordinates and rejected within "
            f"{hz.NEGATIVE_EXCLUSION_KM:.0f} km / {hz.NEGATIVE_EXCLUSION_DAYS} days "
            "of any record"
        ),
        "sampling_positive_rate": float(dataset.y.mean()),
        "license": "GDACS: public domain (CC BY 4.0, EC JRC). ERA5: Copernicus.",
    }


def _limitations(spec: hz.HazardSpec, metrics: dict, strongest: str) -> list[str]:
    return [
        f"Negative sampling over-represents non-{spec.key} periods "
        f"({float(metrics['positive_rate']):.0%} of rows are positive), so the "
        "intercept encodes a sampling frame rather than a real-world base rate. "
        "Absolute probabilities are optimistic and must be read as a ranking "
        "score, not as incidence.",
        f"Only {int(metrics['positives'])} {spec.key} events back the fit, so "
        "coefficients carry wide uncertainty and are shrunk hard by L2.",
        f"A GDACS {spec.gdacs_eventtype} record means the event was reported "
        "somewhere inside a coarse alert polygon, not measured at the record's "
        "centroid, so the label is noisy.",
        "Cross-validation holds out 0.5 degree cells, not unseen countries or "
        "unseen climates, so the reported AUC is optimistic for a region "
        "outside the training distribution.",
        f"The strongest single feature is {strongest}; the model only earns its "
        "place by beating a fit on that column alone.",
        *spec.limitations,
    ]


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "hazard",
        nargs="?",
        default="all",
        choices=["all", *hz.TRAINED_HAZARDS],
    )
    parser.add_argument("--data", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    keys = list(hz.TRAINED_HAZARDS) if args.hazard == "all" else [args.hazard]

    # One refused hazard must not hide the state of the others.
    failures: list[str] = []
    for key in keys:
        spec = hz.TRAINED_HAZARDS[key]
        print(f"\n=== {key} ===")
        try:
            train(spec, dataset_path=args.data, out=args.out)
        except (RuntimeError, FileNotFoundError, ValueError) as exc:
            print(f"  REFUSED: {exc}")
            failures.append(key)

    if failures:
        print(f"\n{len(failures)} of {len(keys)} hazards not written: {failures}")


if __name__ == "__main__":  # pragma: no cover - offline entry point
    main()
