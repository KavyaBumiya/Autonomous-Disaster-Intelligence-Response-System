# Flood model: data, training, and what the number means

Flood is the first of three fitted occurrence models. This document records where
its training data came from, how to rebuild it, and — most importantly — what the
resulting probability is and is not allowed to be used for. Fire and storm share
the same pipeline and the same caveats; see `ml/hazards.py` for their specs and
`app/ml/artifacts/*.json` for their measured metrics.

Separately, seismic has a **background-rate prior** rather than an occurrence
model, built from the USGS ComCat catalogue by `ml/seismic_prior.py` and served by
`app/ml/seismic_prior.py`. It is a long-run regional rate, explicitly not a
forecast; `ml/hazards.py:DECLINED_HAZARDS["seismic"]` explains why no fitted
occurrence model is attempted.

## What is fitted

`app/ml/flood_model.py` scores the question **"did a flood occur at all in this
zone, given the recent rainfall?"**

It does *not* replace the propagation arithmetic in
`prediction_engine._flood_propagation_probability`, which answers a different
question: "how bad does this specific cell get once it is raining". The two are
composed — the trained probability sets the zone level, and the existing 10 km
distance falloff spreads it across cells, because the fitted model has no
opinion about intra-zone geometry.

| | |
| --- | --- |
| Model | L2-regularised logistic regression, fitted with IRLS |
| Runtime deps | Python standard library only (no numpy, sklearn, or scipy) |
| Artifact | `app/ml/artifacts/flood_lr_v1.json` |
| Training code | `ml/train_flood_model.py` |
| Dataset code | `ml/flood_dataset.py` |
| Dataset | `ml/data/flood_dataset.csv` (389 rows: 144 flood / 245 non-flood) |

## Training data

All of it is public, and none of it came from this repository's own test data.

- **Positives** — [GDACS](https://www.gdacs.org/) flood event records
  (`gdacsapi/api/events/geteventlist/SEARCH`). Fetched quarter by quarter,
  because the API silently ignores the `eventtype` filter and caps each response
  near 100 records. Events are deduplicated by GDACS event id, so a single
  multi-week event contributes **one** row.
- **Negatives** — deliberately *not* "random places with no flood". Each
  negative is sampled near a real flood, at least 50 km away and at least 20
  days from it, so that "no flood" is a statement about weather rather than
  about geography.
- **Rainfall features** — ERA5 reanalysis via the
  [Open-Meteo archive API](https://archive-api.open-meteo.com/v1/archive).
- **Window** — the ten completed days *before* onset. Rain falling on or after
  the onset day is excluded, so an event can never appear to have caused itself.

Each flood is one independent observation, so all cross-validation is **grouped
by GDACS event id**. Without grouping, a single event appearing in both train
and validation folds would inflate the score.

## Features

| Feature | Meaning |
| --- | --- |
| `peak_precip_3d_mm` | Wettest single day in the three days before onset |
| `precip_10d_mm` | Total rainfall over the ten-day window |
| `dry_spell_days` | Consecutive dry days counting back from the most recent |
| `elevation_m` | Terrain elevation at the event location |

`precip_72h_mm` is still present in the CSV for inspection but is **excluded
from the fit**: it is a deterministic subset of `peak_precip_3d_mm` and pulling
it in splits one signal across two weights. The trainer reports pairwise
collinearity and refuses to publish if a pair exceeds the threshold.

### One coefficient has the wrong sign

The fitted `precip_10d_mm` weight is **negative** (−0.12), which reads as "more
rain over ten days makes flooding less likely". That is not what the data says.
The column's own relationship to the label is positive (positives average
67 mm, negatives 44 mm).

It happens because `peak_precip_3d_mm` and `precip_10d_mm` correlate at
**r ≈ 0.74** — a wet three-day peak usually sits inside a wet ten-day total.
With two columns carrying one signal, L2 is free to split the effect any way
that minimises the penalised loss, and it chose to put a slightly larger weight
on the peak and a slightly negative one on the total. The combined rainfall
term stays positive, which is why the out-of-fold AUC still beats both
baselines.

**This is why the model ships anyway.** It is not a bug to fix by flipping the
sign — the sign is an artefact of which of two correlated columns absorbed the
shared effect, and forcing it positive would be fitting the answer rather than
the data. What it does mean:

- **Do not** read any single coefficient as a causal statement about rain.
- **Do** read the rainfall pair as one term that rises with rain.
- The honest alternative, if the sign ever became a problem, is dropping one of
  the two columns — not sign-editing the artifact.

The caveat is recorded in the artifact's own `limitations` so it surfaces
through `/api/phase2/model-registry` rather than only in this file.

## Measured performance

Grouped 5-fold cross-validated, out-of-fold, on 389 rows:

| Metric | Trained model | Rules baseline | Base rate |
| --- | --- | --- | --- |
| ROC-AUC | **0.6406** | 0.5825 | 0.5000 |
| Average precision | 0.4455 | — | 0.3702 |
| Brier | 0.2169 | — | 0.2353 |

The trained model beats the hand-tuned rules it sits beside. That margin is
real but modest, and the rules baseline itself only clears a coin flip by a
little — which is the honest summary of how much any of this knows.

`ml/train_flood_model.py` **refuses to write the artifact** unless the fitted
model beats the rules baseline out-of-fold. A regression cannot be published by
accident.

## The probability is a ranking score, not a forecast

The dataset samples roughly 2 non-flood observations per flood, so the
model's intercept encodes a **~37% positive rate** that is an artefact of how
the training set was built, not of how often floods happen. A real deployment
sees far fewer.

Therefore:

- **Use** the score to **rank** zones by relative flood likelihood and to
  prioritise attention.
- **Do not** read `0.72` as "72% chance this cell floods", and do not display it
  as a calibrated probability. It is not calibrated.
- To turn it into a probability, the base rate must be re-estimated against
  your own incident history first. `backend/app/ai/storage/prediction_store.py`
  is the intended home for that loop — see *Known gaps* below.

## Degradation is always safe

`FloodModel` treats the artifact as untrusted input and refuses to load it if
the feature count disagrees, if any coefficient is non-finite, if a coefficient
exceeds `MAX_COEFFICIENT`, or if a scaler entry is non-positive. If it is
missing or malformed, `available` is `False` and `prediction_engine` silently
falls back to the rules baseline. **A corrupt model degrades the forecast; it
never breaks it, and it never fails a request.**

Scoring returns `None` — not a guess — when a feature is missing, non-finite,
or outside the sample range it was fitted on. Missing data is reported as
missing rather than imputed as zero, because zeroing an unobserved day
manufactures a drought and drags the dry-spell feature the wrong way.

## Rebuilding

```bash
cd backend

# Refetch ground truth + rainfall features, then fit and write the artifact.
python -m ml.occurrence_dataset flood
python -m ml.train flood
```

`ml.flood_dataset` makes a few hundred HTTP requests to GDACS and Open-Meteo and
caches responses, so expect it to take several minutes. The trainer is offline
and finishes in about a second.

After any change, the artifact's in-sample metrics should stay *above* the
out-of-fold metrics in the table above. If in-sample converges on out-of-fold,
the fit has started memorising.

## Known gaps

- **The `predictions` table does not exist.** `app/ai/storage/prediction_store.py`
  was written for a prediction/outcome log, but no Alembic migration ever
  created the table, which is why nothing calls it. Until a migration lands
  there is no feedback loop, so the model cannot be recalibrated against
  observed outcomes or retrains on local ground truth. This is the single
  highest-value piece of remaining work.
- **Elevation is substituted, not observed.** `zones` has no elevation column,
  so scoring feeds the training-set mean (`584.3`). The fitted elevation
  coefficient is small (+0.06 standardised), so this is close to omitting the
  feature — but it is a real gap, not a neutral one.
- **Antecedent rainfall depends on the poller.** The feature window is
  reconstructed from `weather_readings`. Fewer than 6 distinct days in the
  window and the trained model declines to score, deferring to the rules.
- **Onset is the GDACS record date**, which is when GDACS published the event,
  not the moment water rose. That noise is in the labels and cannot be removed.
- **The dataset skews recent** (2019–2026) and covers the events GDACS happens
  to publish, which is not a uniform sample of global flooding.

## Tests

```bash
cd backend
pytest tests/test_flood_model.py tests/test_flood_dataset.py
```

These cover artifact validation, saturation, monotonicity in rainfall, missing
and non-finite features, the dry-spell gap semantics, the shipped artifact
beating the rules baseline, and the honesty of the `phase2` model registry.
