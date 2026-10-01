"""Build the seismic background-rate prior from the USGS ComCat catalogue.

Why this exists
---------------
`DECLINED_HAZARDS["seismic"]` records that earthquake *occurrence* is not
weather-driven, so no weather feature set can predict it, and that the
defensible source for a prior would be "a completeness-magnitude declustered
seismic catalogue -- an earthquake catalogue, not a weather one." This module is
that catalogue. USGS ComCat is public, needs no API key, and is near-complete
globally above about M4.5, which is the completeness assumption this rests on.

What it is not
--------------
This is **not** a forecast of an earthquake, and it is deliberately not a
logistic model. A per-region long-run rate cannot rank one 12-hour window above
another, so `train.py`'s publication gate would (correctly) refuse it: an
occurrence model fed only "this region has had earthquakes" produces an
out-of-fold AUC near 0.5. What the rate is good for is context and calibration
-- how seismically active a place is, in units an operator can check, sitting
next to the live magnitude-and-depth attenuation physics that *is* the operative
mechanism when the poller sees a real event.

Declustering
-------------
Aftershocks are not omitted, and this is a stated limitation rather than an
oversight. Removing them properly means a declustering algorithm (Gardner-Knopoff
or a windowed sweep) over the full catalogue, which is a research step with its
own choices, and a rate computed over 25 years is barely moved by the clusters
that dominate any single recent year. The magnitude floor does most of the work:
below the completeness magnitude the catalogue is dominated by regional network
detections, so counting them would inflate quiet regions and understate the
relative activity of already-active ones.
"""
from __future__ import annotations

import argparse
import calendar
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

USGS_EVENT_QUERY = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USER_AGENT = "aegis-seismic-prior/1.0"

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = BACKEND_ROOT / "app" / "ml" / "artifacts" / "seismic_prior_v1.json"

#: Below this the catalogue is not globally complete, so counting these events
#: would mostly measure how well a local network is instrumented.
DEFAULT_MIN_MAGNITUDE = 5.0

#: ComCat rejects a single query above 20 000 events, so the export runs one
#: calendar year at a time. At M5+ the busiest year globally is ~2 200, which
#: leaves a wide margin and needs no pagination.
MAX_EVENTS_PER_QUERY = 20_000

#: Rate binning resolution, matching the training folds' 0.5 degree cells so a
#: prior and a model are never quoted for different places.
CELL_DEGREES = 0.5

#: Only cells that saw at least this many events are stored. A cell with one
#: event in 25 years is not evidence of a rate, and storing ~40 000 one-event
#: cells would make the artifact large enough to be hard to review.
MIN_EVENTS_PER_CELL = 2


@dataclass(frozen=True)
class Quake:
    """One catalogue event, reduced to what the rate actually needs."""

    lat: float
    lng: float
    magnitude: float
    day: date


def _get_json(url: str, *, retries: int = 3, timeout: float = 90.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"USGS query failed after {retries} attempts: {last}")


def _quakes_for_window(
    start: date, end: date, min_magnitude: float, *, verbose: bool
) -> list[Quake]:
    url = (
        f"{USGS_EVENT_QUERY}?format=geojson&starttime={start.isoformat()}"
        f"&endtime={end.isoformat()}&minmagnitude={min_magnitude}"
        f"&limit={MAX_EVENTS_PER_QUERY}"
    )
    payload = _get_json(url)
    features = payload.get("features") or []
    if len(features) >= MAX_EVENTS_PER_QUERY:
        # Silently truncating would bias the rate towards whichever years the
        # busiest events fell in, so this is a hard stop rather than a warning.
        raise RuntimeError(
            f"{start}..{end} returned {len(features)} events at the query "
            f"limit ({MAX_EVENTS_PER_QUERY}); split the window further before "
            "treating this as a complete count"
        )

    out: list[Quake] = []
    for feature in features:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        magnitude = props.get("mag")
        if len(coords) < 2 or magnitude is None:
            continue
        lng, lat = float(coords[0]), float(coords[1])
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            continue
        stamp = props.get("time")
        if stamp is None:
            continue
        out.append(
            Quake(
                lat=lat,
                lng=lng,
                magnitude=float(magnitude),
                day=date.fromtimestamp(float(stamp) / 1000.0),
            )
        )
    return out


def fetch_catalogue(
    start_year: int = 2000,
    end_year: int = 2026,
    min_magnitude: float = DEFAULT_MIN_MAGNITUDE,
    *,
    verbose: bool = True,
) -> list[Quake]:
    """Every M>=`min_magnitude` event in the years requested, year by year."""
    quakes: list[Quake] = []
    for year in range(start_year, end_year + 1):
        start = date(year, 1, 1)
        end = date(year, 12, calendar.monthrange(year, 12)[1])
        end = min(end, date.today())
        if start > end:
            continue
        batch = _quakes_for_window(start, end, min_magnitude, verbose=verbose)
        quakes.extend(batch)
        if verbose:
            print(f"  {year}: {len(batch):6} events  cumulative {len(quakes)}")
        time.sleep(0.2)
    return quakes


def cell_key(lat: float, lng: float) -> str:
    return f"{math.floor(lat / CELL_DEGREES)}:{math.floor(lng / CELL_DEGREES)}"


def _cell_centre(key: str) -> tuple[float, float]:
    lat_index, lng_index = (int(part) for part in key.split(":"))
    return (lat_index + 0.5) * CELL_DEGREES, (lng_index + 0.5) * CELL_DEGREES


def build_prior(quakes: list[Quake], years: float, min_magnitude: float) -> dict[str, Any]:
    """Bin the catalogue into per-cell rates."""
    cells: dict[str, dict[str, float]] = {}
    for quake in quakes:
        key = cell_key(quake.lat, quake.lng)
        record = cells.setdefault(key, {"events": 0, "max_magnitude": 0.0, "m6_plus": 0.0})
        record["events"] += 1
        record["max_magnitude"] = max(record["max_magnitude"], quake.magnitude)
        if quake.magnitude >= 6.0:
            record["m6_plus"] += 1

    stored = {
        key: {
            "events": int(record["events"]),
            "max_magnitude": round(float(record["max_magnitude"]), 1),
            "events_per_year": round(record["events"] / years, 4) if years > 0 else 0.0,
            "m6_plus_events": int(record["m6_plus"]),
        }
        for key, record in sorted(cells.items())
        if record["events"] >= MIN_EVENTS_PER_CELL
    }
    counted = sum(int(r["events"]) for r in stored.values())
    return {
        "model_id": "aegis-seismic-prior",
        "model_version": "usgs-comcat-rate-v1",
        "hazard": "seismic",
        "kind": "background_rate",
        "question": (
            "how seismically active is this location, as a long-run rate of "
            "M+ events per year"
        ),
        "source": "USGS ComCat (earthquake.usgs.gov), public domain, no API key",
        "source_url": USGS_EVENT_QUERY,
        "min_magnitude": min_magnitude,
        "start_year": min(q.day.year for q in quakes) if quakes else None,
        "end": max(q.day.isoformat() for q in quakes) if quakes else None,
        "years": round(years, 3),
        "cell_degrees": CELL_DEGREES,
        "events_in_catalogue": len(quakes),
        "cells_stored": len(stored),
        "events_in_stored_cells": counted,
        "min_events_per_cell": MIN_EVENTS_PER_CELL,
        "cells": stored,
        "limitations": _limitations(min_magnitude, years, counted, len(quakes)),
    }


def _limitations(
    min_magnitude: float, years: float, counted: int, total: int
) -> tuple[str, ...]:
    return (
        "This is a long-run rate, not a forecast. It does not predict that an "
        "earthquake will happen, when, or how large; it says how active the "
        "region has been. A short window probability derived from it is "
        "correspondingly small, and should not be read as a prediction.",
        f"Only M{min_magnitude}+ is counted, on the grounds that the catalogue "
        "is near-complete globally at that level. A lower floor would mostly "
        "measure local network instrumentation, and would make quiet regions "
        "look active purely because they are well monitored.",
        "Aftershocks are not declustered. A single mainshock sequence can "
        "dominate a cell's count, so a cell's rate is a floor on its activity "
        "rather than a clean independent-event rate.",
        f"Cells holding fewer than {MIN_EVENTS_PER_CELL} events are omitted, so "
        f"{total - counted} of {total} catalogue events are not represented. A "
        "location in an omitted cell reads as zero rate, which means 'not "
        "enough events to say', not 'no earthquakes'.",
        "The rate is spatially binned, not area-weighted, so a cell's count is "
        "attributed to its centre. Locations near a cell edge inherit the "
        "cell's rate regardless of which side of the edge they fall on.",
        "The magnitude floor is applied to the catalogue, not to the peak "
        "magnitude, so this says nothing about the severity of any event that "
        "does occur -- that is the attenuation model's job, not this prior's.",
        f"The window spans about {years:.0f} years. Seismicity is not "
        "stationary over that span: the rate for any given decade may differ "
        "from the mean, and cluster bursts make short recent windows "
        "unrepresentative either way.",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2000)
    parser.add_argument("--end-year", type=int, default=date.today().year)
    parser.add_argument("--min-magnitude", type=float, default=DEFAULT_MIN_MAGNITUDE)
    parser.add_argument("--out", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args(argv)

    print(f"[1/2] fetching USGS ComCat M{args.min_magnitude}+ "
          f"{args.start_year}..{args.end_year}")
    quakes = fetch_catalogue(
        args.start_year, args.end_year, args.min_magnitude, verbose=True
    )
    if not quakes:
        raise SystemExit("catalogue came back empty; refusing to write a zero prior")

    end = max(q.day for q in quakes)
    years = (end - date(args.start_year, 1, 1)).days / 365.25
    print(f"[2/2] binning {len(quakes)} events over {years:.2f} years")
    prior = build_prior(quakes, years, args.min_magnitude)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(prior, indent=2) + "\n", encoding="utf-8")
    print(
        f"  wrote {args.out} -- {prior['cells_stored']} cells, "
        f"{prior['events_in_stored_cells']} events represented"
    )


if __name__ == "__main__":  # pragma: no cover - offline entry point
    main()
