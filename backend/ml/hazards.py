"""What each hazard is, and whether it can honestly be trained.

The prediction engine forecasts five hazards. GDACS publishes point records for
three of them, and the other two are refused here on purpose rather than
fitted on borrowed labels.

Every trained feature in this file is deliberately restricted to quantities the
weather poller already persists -- `rainfall_mm_hr`, `wind_speed_kmh`,
`temperature_c`, `humidity_pct` and `pressure_hpa` in `weather_readings`, plus
terrain elevation from the training set. A model built on a variable the runtime
cannot read would look trained in the registry and then silently never score
anything, which is worse than having no model at all.

Pressure and humidity were the last two variables on that list to reach storage.
Storm now uses both -- mean sea-level pressure is the classic cyclone signal and
was its largest known gap. Fire still does not use humidity, which remains the
single strongest known wildfire predictor and therefore the largest known gap in
the fire model; that is a retrain, not a wiring change. Both columns were
nullable on introduction, so history older than migration 0011 reads as missing
and a model declines to score rather than substituting a plausible default.

Excluded from every feature set, deliberately:

* alert score, alert level, severity, casualties -- these describe the
  *outcome*, so a model handed them learns to read the answer off the label.
* calendar date. Seasonal climatology would lift the score without improving a
  12-hour forecast, and would hide a model that has learned nothing. Negatives
  are drawn from the same locations, so season cannot leak in anyway.
* event id, country, and the raw coordinates, for the same reason.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

# A day below this counts as dry for antecedent-wetness purposes.
DRY_DAY_MM = 1.0
# ERA5 reanalysis lags real time, so the most recent days are simply absent
# from the archive. Without this the newest events would be featureless.
ARCHIVE_LAG_DAYS = 10
# A negative is only "no hazard" if it is far enough from every real record.
NEGATIVE_EXCLUSION_DAYS = 20
# Open-Meteo tolerates many coordinates per request; batching keeps a rebuild
# to a handful of calls instead of one per row.
LOCATIONS_PER_REQUEST = 40
# Negatives are co-located with a real event (jittered) and drawn from up to
# ten years either side of it.
NEGATIVE_OFFSET_DAYS = 3650
NEGATIVE_JITTER_DEGREES = 0.15
# A negative must not sit within this distance of another event.
NEGATIVE_EXCLUSION_KM = 50.0

# The shipped wind ramp, from `_storm_impact_probability`. Reused as the rules
# baseline for both wind-driven hazards so the comparison is against a rule that
# actually exists in this codebase rather than one invented here.
RULES_WIND_FLOOR_KMH = 40.0
RULES_WIND_CEIL_KMH = 120.0


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result


def _series(entry: dict[str, Any], variables: tuple[str, ...]) -> dict[date, dict[str, float]]:
    """Turn an Open-Meteo daily block into {date: {variable: value}}.

    A day absent from a variable's series stays absent for that variable rather
    than defaulting to zero. Treating an unobserved day as no rain would
    manufacture a drought, and treating an unobserved day as no wind would
    manufacture a calm -- both of which are exactly the conditions the model is
    supposed to detect.
    """
    daily = entry.get("daily") or {}
    times: list[str] = daily.get("time") or []
    if not times:
        return {}

    out: dict[date, dict[str, float]] = {}
    for index, stamp in enumerate(times):
        try:
            day = datetime.fromisoformat(stamp).date()
        except (ValueError, TypeError):
            continue
        values: dict[str, float] = {}
        for name in variables:
            column = daily.get(name)
            if not column or index >= len(column):
                continue
            number = _safe_float(column[index])
            if number is not None:
                values[name] = number
        out[day] = values
    return out


def _window(series: dict[date, dict[str, float]], day: date, length: int) -> list[dict[str, float]]:
    """The `length` completed days before `day`, oldest first."""
    end = day - timedelta(days=1)
    start = end - timedelta(days=length - 1)
    return [series.get(start + timedelta(days=offset), {}) for offset in range(length)]


def _mean(values: list[float | None], minimum: int) -> float | None:
    """Mean of the present values, or None if too few were observed.

    A mean silently computed from a third of its intended days is not a mean of
    anything meaningful, so short coverage returns nothing at all.
    """
    present = [v for v in values if v is not None]
    if len(present) < minimum:
        return None
    return sum(present) / len(present)


def _max(values: list[float | None], minimum: int) -> float | None:
    present = [v for v in values if v is not None]
    if len(present) < minimum:
        return None
    return max(present)


def _min(values: list[float | None], minimum: int) -> float | None:
    present = [v for v in values if v is not None]
    if len(present) < minimum:
        return None
    return min(present)


def _sum(values: list[float | None], minimum: int) -> float | None:
    present = [v for v in values if v is not None]
    if len(present) < minimum:
        return None
    return sum(present)


def _dry_spell(window: list[dict[str, float]], limit: int | None = None) -> float:
    """Consecutive days under DRY_DAY_MM, counting back from the most recent.

    Stops at the first wet day and also at the first day the poller missed: no
    evidence of rain in a day is not evidence that it did not rain. This matches
    the runtime extractor in `prediction_engine` exactly -- a feature that
    means one thing offline and another online is worse than no feature.
    """
    cap = limit if limit is not None else len(window)
    spell = 0
    for values in reversed(window):
        if spell >= cap:
            break
        amount = values.get("precipitation_sum")
        if amount is None or amount >= DRY_DAY_MM:
            break
        spell += 1
    return float(spell)


def _coverage(window: list[dict[str, float]], variable: str) -> int:
    return sum(1 for values in window if variable in values)


# ── Per-hazard feature extraction ──────────────────────────────────────────


def extract_flood(entry: dict[str, Any], day: date, window_days: int) -> dict[str, float] | None:
    """Antecedent rainfall. See `ml/hazards.py` module docstring."""
    variables = ("precipitation_sum",)
    series = _series(entry, variables)
    window = _window(series, day, window_days)
    if _coverage(window, "precipitation_sum") < 2:
        return None

    recent = window[-3:]
    return {
        "peak_precip_3d_mm": _max([d.get("precipitation_sum") for d in recent], 2),
        "precip_72h_mm": _sum([d.get("precipitation_sum") for d in recent], 2),
        "precip_10d_mm": _sum([d.get("precipitation_sum") for d in window], 2),
        "dry_spell_days": _dry_spell(window),
        "elevation_m": _safe_float(entry.get("elevation")) or 0.0,
    }


def extract_fire(entry: dict[str, Any], day: date, window_days: int) -> dict[str, float] | None:
    """Fuel dryness and heat load over the month before ignition.

    Fire behaviour is governed by how long the fuel has been dry, not by
    whether it rained this afternoon, so `window_days` is 30 where flood's is
    10. Humidity would be the strongest single predictor and is deliberately
    absent: the poller does not store it.
    """
    variables = ("precipitation_sum", "temperature_2m_max", "wind_speed_10m_max")
    series = _series(entry, variables)
    window = _window(series, day, window_days)
    if _coverage(window, "precipitation_sum") < 10:
        return None

    week = window[-7:]
    return {
        "dry_spell_days": _dry_spell(window, limit=window_days),
        "precip_30d_mm": _sum([d.get("precipitation_sum") for d in window], 10),
        "temp_max_mean_7d_c": _mean([d.get("temperature_2m_max") for d in week], 5),
        "wind_max_mean_7d_kmh": _mean([d.get("wind_speed_10m_max") for d in week], 5),
        "elevation_m": _safe_float(entry.get("elevation")) or 0.0,
    }


def extract_storm(entry: dict[str, Any], day: date, window_days: int) -> dict[str, float] | None:
    """Pressure, wind, rain and warmth in the days before the record.

    Mean sea-level pressure is the classic cyclone signal, and it used to be
    absent by design because the poller did not store it. The poller does now
    (`weather_readings.pressure_hpa`), so it is fitted like any other column.
    Pressure is summarised as the *minimum* daily mean over the recent window
    rather than the mean: a cyclone announces itself as a fall, and averaging
    that fall away would discard the part of the signal that matters.
    """
    variables = (
        "precipitation_sum",
        "wind_speed_10m_max",
        "temperature_2m_max",
        "pressure_msl_mean",
        "relative_humidity_2m_mean",
    )
    series = _series(entry, variables)
    window = _window(series, day, window_days)
    if _coverage(window, "wind_speed_10m_max") < 4:
        return None

    recent = window[-3:]
    return {
        "wind_max_3d_kmh": _max([d.get("wind_speed_10m_max") for d in recent], 2),
        # Baseline-only column, kept in the CSV for the same reason flood keeps
        # `precip_72h_mm`: the rules comparison needs a number the fitted model
        # is not allowed to see. `_storm_impact_probability` reads the most
        # recent wind, not the 3-day peak.
        "wind_max_1d_kmh": _max([d.get("wind_speed_10m_max") for d in window[-1:]], 1),
        "pressure_min_3d_hpa": _min(
            [d.get("pressure_msl_mean") for d in recent], 2
        ),
        "humidity_mean_3d_pct": _mean(
            [d.get("relative_humidity_2m_mean") for d in recent], 2
        ),
        "precip_3d_mm": _sum([d.get("precipitation_sum") for d in recent], 2),
        "temp_max_mean_3d_c": _mean([d.get("temperature_2m_max") for d in recent], 2),
        "elevation_m": _safe_float(entry.get("elevation")) or 0.0,
    }


# ── Specs ──────────────────────────────────────────────────────────────────


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def flood_rule(features: dict[str, float]) -> float | None:
    """The flood rule currently deployed, as a score.

    Mirrors `prediction_engine._flood_propagation_probability`: rainfall
    normalised at 50 mm/hr and weighted 0.5, elevation weighted 0.3, and the
    distance term pinned at its dataset-neutral maximum because a CSV row has
    no centroid to measure from. Pinning distance upward makes this a slight
    over-estimate of the live rule, which is the fair direction for a
    replacement to be judged in.
    """
    peak = _safe_float(features.get("peak_precip_3d_mm"))
    elevation = _safe_float(features.get("elevation_m"))
    if peak is None or elevation is None:
        return None
    rain_factor = min(1.0, peak / 50.0)
    elevation_risk = 1.0 - min(1.0, elevation / 1000.0)
    return _clamp01(rain_factor * 0.5 + elevation_risk * 0.3 + 0.2)


def wind_ramp(features: dict[str, float], column: str, floor: float, ceil: float) -> float | None:
    """The storm rule's linear wind ramp, applied to any wind column.

    This is literally `_storm_impact_probability`. The fire code ships no
    probability of its own -- only a wind-magnitude spread factor -- so the same
    ramp is used for fire as the closest honest analogue, and the comparison is
    labelled as an analogue rather than presented as the shipped rule.
    """
    value = _safe_float(features.get(column))
    if value is None:
        return None
    return _clamp01((value - floor) / (ceil - floor))


def fire_rule(features: dict[str, float]) -> float | None:
    return wind_ramp(features, "wind_max_mean_7d_kmh", RULES_WIND_FLOOR_KMH, RULES_WIND_CEIL_KMH)


def storm_rule(features: dict[str, float]) -> float | None:
    return wind_ramp(features, "wind_max_1d_kmh", RULES_WIND_FLOOR_KMH, RULES_WIND_CEIL_KMH)


@dataclass(frozen=True)
class HazardSpec:
    """One trainable hazard: its labels, its features, and its baseline."""

    key: str
    target: str
    gdacs_eventtype: str
    model_id: str
    feature_columns: tuple[str, ...]
    daily_variables: tuple[str, ...]
    antecedent_days: int
    extract: Callable[[dict[str, Any], date, int], dict[str, float] | None]
    rule: Callable[[dict[str, float]], float | None]
    rule_name: str
    rule_is_shipped: bool
    strongest_column: str
    min_records: int
    questions: str
    limitations: tuple[str, ...] = field(default_factory=tuple)

    def rule_score(self, features: dict[str, float]) -> float | None:
        return self.rule(features)


FLOOD = HazardSpec(
    key="flood",
    target="flood_occurred",
    gdacs_eventtype="FL",
    model_id="aegis-flood-logistic",
    feature_columns=(
        "peak_precip_3d_mm",
        "precip_10d_mm",
        "dry_spell_days",
        "elevation_m",
    ),
    daily_variables=("precipitation_sum",),
    antecedent_days=10,
    extract=extract_flood,
    rule=flood_rule,
    rule_name="prediction_engine._flood_propagation_probability",
    rule_is_shipped=True,
    strongest_column="precip_10d_mm",
    min_records=30,
    questions="did a flood occur here, given the rain that had already fallen",
    limitations=(
        "Negative sampling over-represents non-flood periods, so the intercept "
        "encodes a sampling frame rather than a real-world base rate; treat the "
        "score as a ranking, never as a calibrated probability.",
        "Onset is the GDACS publication date, not the moment water rose.",
        "Elevation is imputed from the training mean because zones carry no "
        "elevation column.",
        "The two rainfall columns are correlated (r ~ 0.74), so the L2 penalty "
        "splits one rainfall signal across both weights and `precip_10d_mm` "
        "carries a small *negative* coefficient -- more antecedent rain "
        "nominally lowering the score. The combined rainfall term is positive "
        "and the out-of-fold AUC beats both baselines, but no single "
        "coefficient here should be read as a causal claim about rain.",
    ),
)

FIRE = HazardSpec(
    key="fire",
    target="fire_occurred",
    gdacs_eventtype="WF",
    model_id="aegis-fire-logistic",
    feature_columns=(
        "dry_spell_days",
        "precip_30d_mm",
        "temp_max_mean_7d_c",
        "wind_max_mean_7d_kmh",
        "elevation_m",
    ),
    daily_variables=(
        "precipitation_sum",
        "temperature_2m_max",
        "wind_speed_10m_max",
    ),
    antecedent_days=30,
    extract=extract_fire,
    rule=fire_rule,
    rule_name="analogue of _fire_wind_direction (no probability ships today)",
    rule_is_shipped=False,
    strongest_column="temp_max_mean_7d_c",
    min_records=25,
    questions="did a wildfire start here, given how dry and hot the fuel was",
    limitations=(
        "Wildfire records are fire *events* at whatever resolution GDACS chose; "
        "many are detected once already sizeable, so the model is predicting "
        "detection as much as ignition.",
        "No fuel type, land cover, or humidity: relative humidity is the single "
        "strongest known predictor and the poller does not store it.",
        "Negative sampling over-represents non-fire periods, so the score is a "
        "ranking, not a calibrated probability.",
    ),
)

STORM = HazardSpec(
    key="storm",
    target="storm_occurred",
    gdacs_eventtype="TC",
    model_id="aegis-storm-logistic",
    feature_columns=(
        "wind_max_3d_kmh",
        "pressure_min_3d_hpa",
        "humidity_mean_3d_pct",
        "precip_3d_mm",
        "temp_max_mean_3d_c",
        "elevation_m",
    ),
    daily_variables=(
        "precipitation_sum",
        "wind_speed_10m_max",
        "temperature_2m_max",
        "pressure_msl_mean",
        "relative_humidity_2m_mean",
    ),
    antecedent_days=10,
    extract=extract_storm,
    rule=storm_rule,
    rule_name="prediction_engine._storm_impact_probability",
    rule_is_shipped=True,
    strongest_column="wind_max_1d_kmh",
    min_records=25,
    questions="did a tropical cyclone affect here, given the preceding pressure and wind",
    limitations=(
        "A cyclone record is a moving track summarised at a centroid. The "
        "centroid at onset is where the storm was, not where it made landfall, "
        "so the label and the location can disagree.",
        "Tropical cyclones are rare and clustered in basins and seasons, so a "
        "fitted coefficient is not expected to transfer between basins.",
        "Mean sea-level pressure comes from reanalysis; it reflects the synoptic "
        "field and does not include sub-grid pressure perturbations.",
        "Pressure is fitted but earns almost nothing: its weight is near zero "
        "and *positive*, so more pressure nominally raises the score. A 50 hPa "
        "swing -- the difference between a tropical depression and a category-1 "
        "cyclone -- moves the logit by about 0.1, against roughly 0.8 for a "
        "20-point humidity swing. The gain from adding pressure and humidity "
        "came from humidity; do not read pressure as a working cyclone signal "
        "here, and do not sign-edit the artifact to make it look like one.",
    ),
)

TRAINED_HAZARDS: dict[str, HazardSpec] = {
    spec.key: spec for spec in (FLOOD, FIRE, STORM)
}


@dataclass(frozen=True)
class DeclinedHazard:
    """A hazard deliberately left to the rules, with the reason recorded."""

    key: str
    gdacs_eventtype: str | None
    reason: str
    what_would_change_it: str


DECLINED_HAZARDS: dict[str, DeclinedHazard] = {
    "seismic": DeclinedHazard(
        key="seismic",
        gdacs_eventtype="EQ",
        reason=(
            "Earthquake records exist in abundance, but whether a rupture occurs "
            "is a function of plate tectonics and fault state, not of weather. "
            "The only weather variables the runtime can supply -- rainfall, "
            "wind, temperature -- carry no information about it, so a fitted "
            "model would be measuring noise and presenting it as a forecast. "
            "The existing magnitude-and-depth shaking physics is left in place, "
            "which is honest about being a physical attenuation estimate rather "
            "than a learned prior."
        ),
        what_would_change_it=(
            "Partly resolved, and the remainder is still not available. The "
            "catalogue this note asked for now exists: `ml/seismic_prior.py` "
            "builds a completeness-filtered background rate from USGS ComCat, "
            "and `app/ml/seismic_prior.py` serves it alongside the attenuation "
            "physics as context. It is a rate, not a forecast, and it is not a "
            "substitute for an occurrence model -- a per-region long-run rate "
            "cannot rank one window above another, so it would be refused by "
            "the same gate that refuses this hazard. What would still be needed "
            "for an actual forecast is something the weather feed cannot "
            "provide at all: precursors, fault state, or a time-dependent "
            "hazard model. Nothing in the weather data can supply those."
        ),
    ),
    "landslide": DeclinedHazard(
        key="landslide",
        gdacs_eventtype=None,
        reason=(
            "Landslides are rainfall-driven and the rainfall physics already "
            "exists here, but GDACS publishes no landslide event type, so there "
            "is no ground truth to fit against. Training on flood records and "
            "labelling them landslides would be straightforwardly wrong: floods "
            "and landslides share a trigger and almost nothing else, and the "
            "model would inherit every flood-specific regularity. The rules "
            "keep the honest rainfall leg and report the missing terrain terms "
            "as a limitation."
        ),
        what_would_change_it=(
            "A citable landslide event feed with onset dates and point "
            "locations -- e.g. a national or NASA landslide catalogue exposed "
            "as an API or a stable CSV. With that, the flood antecedent-rainfall "
            "features transfer directly and only slope and lithology would need "
            "adding."
        ),
    ),
    "lightning": DeclinedHazard(
        key="lightning",
        gdacs_eventtype=None,
        reason=(
            "Lightning is genuinely weather-driven, so unlike seismic this is "
            "not a refusal on physical grounds -- the features would be "
            "legitimate. It is deferred purely for want of ground truth: GDACS "
            "publishes no lightning event type. Its published types were "
            "checked directly against the live feed and are FL, TC, EQ and WF, "
            "so there is nothing to label with. Substituting a thunderstorm "
            "report for a flash would not be a close substitute: a reported "
            "thunderstorm is a damage or wind event, which is a different "
            "quantity from a strike, and a model fitted to one would misreport "
            "the other."
        ),
        what_would_change_it=(
            "A citable flash-to-ground strike catalogue with onset timestamps "
            "and point locations. Blitzortung publishes one but offers no "
            "public API, and WWLLN is licensed. The shape needed is the same "
            "as the seismic catalogue: point events with times, declusterable, "
            "and it must cover India rather than North America -- every zone "
            "currently configured is in Gujarat, and a US-only feed would be "
            "fitting a prior for a region nothing is deployed in."
        ),
    ),
    "severe_weather": DeclinedHazard(
        key="severe_weather",
        gdacs_eventtype=None,
        reason=(
            "Convective storms are the most predictable of the weather hazards "
            "here, so this is not a refusal on physical grounds -- the features "
            "would be legitimate. It is deferred for two reasons, one external "
            "and one measured. First, there is no label source: GDACS "
            "publishes no convective or thunderstorm event type (its published "
            "types were checked against the live feed and are FL, TC, EQ, WF), "
            "and the obvious substitute, NOAA Storm Events, is US-only. Since "
            "every configured zone is in Gujarat, a US feed would fit a prior "
            "for a region nothing is deployed in. Second, and independently: "
            "CAPE, the standard convective-instability feature, is not "
            "available from the archive this project trains on. Open-Meteo's "
            "ERA5 archive accepts `cape_max` and `cape_mean` and returns HTTP "
            "200 with null for every day of every year tested, rather than "
            "erroring, so a pipeline built on it would silently produce no "
            "rows. That was verified across 2020, 2024 and 2026 on both the "
            "daily and hourly archive endpoints."
        ),
        what_would_change_it=(
            "A citable Indian convective or thunderstorm feed with onset "
            "timestamps and point locations -- IMD/MOSDAC, or a licensed "
            "provider. CAPE is not a blocker once that exists: "
            "`precipitation_hours`, `dew_point_2m_mean`, "
            "`apparent_temperature_max`, `wind_gusts_10m_max` and "
            "`cloud_cover_mean` were all confirmed to carry real values from "
            "the same archive and are usable substitutes for instability, "
            "though none of them is a direct measurement of it."
        ),
    ),
}

ENGINE_HAZARDS: tuple[str, ...] = (
    "flood",
    "fire",
    "seismic",
    "landslide",
    "storm",
)

PEAK_WINDOW_DAYS = 3


def hazard_inventory() -> dict[str, Any]:
    """Serialise the whole train/decline ledger for the operator console.

    `model_status()` answers "is this model healthy right now". This answers the
    question an operator actually asks first: "which hazards are covered, and
    for the ones that are not, why not?" That answer currently lives only in
    this module, so a client could see five hazard tiles and no way to learn that
    three of them are rule-based or that two are deliberately unmodelled.

    Declined entries are reported as first-class rows rather than omissions. A
    hazard missing from a list is indistinguishable from one nobody considered,
    and the difference matters to somebody deciding whether to trust a gap.
    """
    trained = {
        key: {
            "key": key,
            "status": "trained",
            "gdacs_eventtype": spec.gdacs_eventtype,
            "antecedent_days": spec.antecedent_days,
            "feature_columns": list(spec.feature_columns),
            "rule_is_shipped": spec.rule_is_shipped,
        }
        for key, spec in TRAINED_HAZARDS.items()
    }
    declined = {
        key: {
            "key": key,
            "status": "declined",
            "gdacs_eventtype": entry.gdacs_eventtype,
            "reason": entry.reason,
            "what_would_change_it": entry.what_would_change_it,
        }
        for key, entry in DECLINED_HAZARDS.items()
    }
    return {
        "engine_hazards": list(ENGINE_HAZARDS),
        "trained": trained,
        "declined": declined,
        "trained_count": len(trained),
        "declined_count": len(declined),
    }
