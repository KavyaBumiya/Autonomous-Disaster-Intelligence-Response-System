"""Build occurrence datasets for any trainable hazard from public records.

Ground truth
------------
GDACS (Global Disaster Alert and Coordination System, EC JRC) publishes point
records with an onset date for floods, wildfires, tropical cyclones, droughts,
earthquakes and eruptions. `geteventlist/SEARCH` needs no API key but caps a
response at a couple of hundred events and silently ignores an `eventtype`
filter, so the export runs one calendar quarter at a time and filters
client-side. Records are de-duplicated by event id *and* episode id: GDACS
carries one row per episode, and several episodes can describe the same storm
or fire, so collapsing them stops a single long event from becoming a dozen
"independent" training rows.

Every label here is authored by the European Commission's Joint Research
Centre, not by this repository. That independence is the point: it is what
makes the labels usable for fitting instead of circular.

Features
--------
Antecedent conditions at the event location from ERA5 reanalysis, via the
Open-Meteo archive. The variables requested are declared per hazard in
`ml/hazards.py`, and are restricted to those the runtime poller also stores.

Negatives
---------
Drawn from the *same locations* as the positives, jittered, and far enough away
in time from every record that "no hazard" is a statement about weather rather
than about geography. A negative from a random global coordinate would be
trivially separable -- India floods, the Sahara does not -- and the fitted
model would be worthless in production.
"""
from __future__ import annotations

import calendar
import csv
import json
import math
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from ml import hazards as hz

GDACS_API = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
USER_AGENT = "aegis-occurrence-dataset/1.0"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_ROOT / "ml" / "data"


def default_csv(spec: hz.HazardSpec) -> Path:
    return DATA_DIR / f"{spec.key}_dataset.csv"


# ── Records ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EventRecord:
    """One GDACS observation."""

    event_id: str
    lat: float
    lng: float
    onset: date
    end: date | None
    alert_score: float | None
    country: str
    iso3: str


@dataclass
class Sample:
    """One labelled training row."""

    lat: float
    lng: float
    day: date
    label: int
    origin: str  # "gdacs_event" | "negative_sample"
    event_id: str = ""
    features: dict[str, float] = field(default_factory=dict)


# ── HTTP ───────────────────────────────────────────────────────────────────


def _get_json(url: str, *, retries: int = 3, timeout: float = 60.0) -> Any:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8", "replace"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            last = exc
            # GDACS returns 400 on some quarter boundaries and the occasional
            # empty body; a short backoff recovers most of them.
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last


# ── GDACS ──────────────────────────────────────────────────────────────────


def _parse_date(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)).date()
    except ValueError:
        return None


def fetch_events(
    spec: hz.HazardSpec, start_year: int, end_year: int, *, verbose: bool = True
) -> list[EventRecord]:
    """Every GDACS record of this hazard type between two years, de-duplicated."""
    seen: dict[str, EventRecord] = {}

    for year in range(start_year, end_year + 1):
        for quarter in range(4):
            first_month = quarter * 3 + 1
            last_month = first_month + 2
            last_day = calendar.monthrange(year, last_month)[1]
            start = date(year, first_month, 1)
            end = date(year, last_month, last_day)

            url = (
                f"{GDACS_API}?fromDate={start.isoformat()}"
                f"&toDate={end.isoformat()}&limit=200"
            )
            try:
                payload = _get_json(url)
            except RuntimeError as exc:
                # A single unreachable quarter must not abort a multi-year
                # rebuild; the gap is reported rather than hidden.
                if verbose:
                    print(f"  ! {start}..{end} unavailable: {exc}")
                continue

            for feature in payload.get("features", []) or []:
                props = feature.get("properties") or {}
                if props.get("eventtype") != spec.gdacs_eventtype:
                    continue
                geometry = feature.get("geometry") or {}
                coords = geometry.get("coordinates") or []
                if len(coords) < 2:
                    continue
                lng, lat = float(coords[0]), float(coords[1])
                onset = _parse_date(props.get("fromdate"))
                if onset is None or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
                    continue

                key = f"{props.get('eventid')}:{props.get('episodeid')}"
                record = EventRecord(
                    event_id=key,
                    lat=lat,
                    lng=lng,
                    onset=onset,
                    end=_parse_date(props.get("todate")),
                    alert_score=hz._safe_float(props.get("alertscore")),
                    country=str(props.get("country") or "")[:64],
                    iso3=str(props.get("iso3") or "")[:8],
                )
                previous = seen.get(key)
                if previous is None or onset < previous.onset:
                    seen[key] = record

            if verbose:
                found = sum(1 for r in seen.values() if start <= r.onset <= end)
                print(
                    f"  {start}..{end}  cumulative {spec.key} records:"
                    f" {len(seen)} (this quarter +{found})"
                )
            time.sleep(0.2)

    return sorted(seen.values(), key=lambda r: r.onset)


# ── Negative sampling ──────────────────────────────────────────────────────


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lng / 2) ** 2
    )
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def sample_negatives(
    records: list[EventRecord],
    *,
    ratio: float,
    seed: int,
    verbose: bool = True,
) -> list[Sample]:
    """Draw non-event dates from the same places the events happened.

    A candidate is rejected when it falls inside the exclusion window around
    any record, which keeps unrecorded-but-actually-occurring dates out of the
    negative class where possible.
    """
    rng = random.Random(seed)
    cutoff = date.today() - timedelta(days=hz.ARCHIVE_LAG_DAYS)
    exclusion = timedelta(days=hz.NEGATIVE_EXCLUSION_DAYS)
    negatives: list[Sample] = []
    rejected = 0

    for record in records:
        made = 0
        for _ in range(int(ratio) * 6 + 12):
            if made >= ratio:
                break
            offset = rng.randint(0, hz.NEGATIVE_OFFSET_DAYS)
            candidate = record.onset + timedelta(days=offset)
            if candidate > cutoff:
                continue
            # Jitter slightly so negatives are not exactly co-located with the
            # event; a model should not key on the raw coordinate pair.
            lat = round(record.lat + rng.uniform(-hz.NEGATIVE_JITTER_DEGREES, hz.NEGATIVE_JITTER_DEGREES), 4)
            lng = round(record.lng + rng.uniform(-hz.NEGATIVE_JITTER_DEGREES, hz.NEGATIVE_JITTER_DEGREES), 4)

            conflict = any(
                other.event_id != record.event_id
                and _haversine_km(lat, lng, other.lat, other.lng)
                <= hz.NEGATIVE_EXCLUSION_KM
                and abs((candidate - other.onset).days) <= hz.NEGATIVE_EXCLUSION_DAYS
                for other in records
            )
            if conflict:
                rejected += 1
                continue

            negatives.append(
                Sample(
                    lat=lat,
                    lng=lng,
                    day=candidate,
                    label=0,
                    origin="negative_sample",
                )
            )
            made += 1

    if verbose:
        print(
            f"  negatives kept: {len(negatives)}"
            f" (rejected {rejected} as too close to a record)"
        )
    return negatives


# ── Antecedent features ────────────────────────────────────────────────────


def _batched(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _date_buckets(samples: list[Sample]) -> list[list[Sample]]:
    """Group samples by half-year so each request covers a short date range.

    The archive API tolerates many coordinates, but the cell count it will serve
    is bounded by locations x days, so the work is split by period instead.
    """
    buckets: dict[tuple[int, int], list[Sample]] = {}
    for sample in samples:
        half = 0 if sample.day.month <= 6 else 1
        buckets.setdefault((sample.day.year, half), []).append(sample)
    return [buckets[key] for key in sorted(buckets)]


def fetch_features(
    spec: hz.HazardSpec, samples: list[Sample], *, verbose: bool = True
) -> int:
    """Attach antecedent features to every sample. Returns the failure count."""
    if not samples:
        return 0

    failures = 0
    for bucket in _date_buckets(samples):
        first_day = min(s.day for s in bucket) - timedelta(
            days=spec.antecedent_days + 2
        )
        last_day = max(s.day for s in bucket)
        variables = ",".join(spec.daily_variables)

        for group in _batched(bucket, hz.LOCATIONS_PER_REQUEST):
            lats = ",".join(f"{s.lat:.4f}" for s in group)
            lngs = ",".join(f"{s.lng:.4f}" for s in group)
            url = (
                f"{OPEN_METEO_ARCHIVE}?latitude={lats}&longitude={lngs}"
                f"&start_date={first_day.isoformat()}&end_date={last_day.isoformat()}"
                f"&daily={variables}&timezone=UTC"
            )
            try:
                payload = _get_json(url, retries=4, timeout=90.0)
            except RuntimeError:
                failures += len(group)
                if verbose:
                    print(f"  ! {len(group)} samples dropped ({first_day}..{last_day})")
                continue

            entries = payload if isinstance(payload, list) else [payload]
            if len(entries) != len(group):
                # A partial batch is unusable: silently misaligning weather
                # with labels would be worse than dropping the batch.
                failures += len(group)
                if verbose:
                    print(f"  ! partial batch ({len(entries)}/{len(group)}), dropped")
                continue

            for sample, entry in zip(group, entries):
                features = spec.extract(entry, sample.day, spec.antecedent_days)
                if features is None:
                    failures += 1
                    continue
                sample.features = features

            if verbose:
                print(f"  {first_day}..{last_day} -> {len(group)} samples")
            time.sleep(0.3)

    return failures


# ── Assembly ───────────────────────────────────────────────────────────────


def build_dataset(
    spec: hz.HazardSpec,
    *,
    start_year: int = 2019,
    end_year: int | None = None,
    negative_ratio: int = 2,
    seed: int = 20260930,
    out_path: Path | None = None,
) -> Path:
    """Rebuild one hazard's dataset CSV end to end."""
    end_year = end_year or date.today().year
    target = out_path or default_csv(spec)

    print(f"[1/4] GDACS {spec.key} records ({spec.gdacs_eventtype}) {start_year}-{end_year}")
    records = fetch_events(spec, start_year, end_year)
    cutoff = date.today() - timedelta(days=hz.ARCHIVE_LAG_DAYS)
    records = [r for r in records if r.onset <= cutoff]
    print(f"  usable {spec.key} records: {len(records)}")
    if len(records) < spec.min_records:
        raise RuntimeError(
            f"only {len(records)} {spec.key} records collected;"
            f" too few to fit a model (need {spec.min_records})"
        )

    print(f"[2/4] sampling negatives (ratio {negative_ratio})")
    samples = [
        Sample(
            lat=r.lat,
            lng=r.lng,
            day=r.onset,
            label=1,
            origin="gdacs_event",
            event_id=r.event_id,
        )
        for r in records
    ]
    samples.extend(sample_negatives(records, ratio=negative_ratio, seed=seed))

    print(f"[3/4] fetching ERA5 antecedent conditions for {len(samples)} samples")
    failures = fetch_features(spec, samples)

    # Every row must carry the same feature columns or the design matrix would
    # be ragged. A row that is missing one is dropped, not zero-filled.
    complete = [s for s in samples if s.features]
    if complete:
        expected = set(complete[0].features)
        complete = [s for s in complete if set(s.features) == expected]
    if not complete:
        raise RuntimeError(f"no {spec.key} rows survived feature extraction")

    columns = sorted(complete[0].features)
    missing = [c for c in spec.feature_columns if c not in columns]
    if missing:
        raise RuntimeError(
            f"{spec.key} extractor did not emit required features: {missing}"
        )

    print(f"[4/4] writing {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fields = ["lat", "lng", "day", spec.target, "origin", "event_id", *columns]
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in complete:
            row = {
                "lat": sample.lat,
                "lng": sample.lng,
                "day": sample.day.isoformat(),
                spec.target: sample.label,
                "origin": sample.origin,
                "event_id": sample.event_id,
            }
            row.update(sample.features)
            writer.writerow(row)

    positives = sum(1 for s in complete if s.label == 1)
    print(
        f"  wrote {len(complete)} rows "
        f"({positives} {spec.key} / {len(complete) - positives} non-{spec.key}), "
        f"{failures} dropped for missing data"
    )
    return target


def main(argv: list[str] | None = None) -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "hazard",
        nargs="?",
        default="all",
        choices=["all", *hz.TRAINED_HAZARDS],
    )
    parser.add_argument("--start-year", type=int, default=2019)
    parser.add_argument("--end-year", type=int, default=None)
    parser.add_argument("--negative-ratio", type=int, default=2)
    args = parser.parse_args(argv)

    keys = list(hz.TRAINED_HAZARDS) if args.hazard == "all" else [args.hazard]
    for key in keys:
        print(f"\n=== {key} ===")
        build_dataset(
            hz.TRAINED_HAZARDS[key],
            start_year=args.start_year,
            end_year=args.end_year,
            negative_ratio=args.negative_ratio,
        )


if __name__ == "__main__":  # pragma: no cover - offline entry point
    main()
