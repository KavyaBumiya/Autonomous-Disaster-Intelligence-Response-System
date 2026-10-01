"""Runtime lookup for the USGS seismic background-rate prior.

Pure stdlib, like the rest of `app/ml`. Reads the artifact built by
`python -m ml.seismic_prior`; it never makes a network call, because a forecast
endpoint that blocks on USGS is worse than one that answers from a snapshot.

What this is for
----------------
`ml.hazards.DECLINED_HAZARDS["seismic"]` explains that whether a rupture occurs
is a function of tectonics and fault state rather than weather, so no fitted
occurrence model is honest here. This supplies the *context* that note asked
for: how seismically active a place is, in events per year, from a
completeness-filtered USGS catalogue.

It is not a forecast. `probability_in_window` returns a Poisson
at-least-one-event figure derived from a 25-year mean rate, which is a statement
about climatology, not about the next twelve hours. The module docstring on
`ml/seismic_prior.py` and the artifact's own `limitations` both say so, and
`info()` carries them to callers so they cannot be quoted without them.

The live mechanism for a real event is unchanged and remains the operative one:
the USGS poller plus the magnitude-and-depth attenuation physics in
`prediction_engine.calculate_seismic_shaking`.
"""
from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

ARTIFACT_PATH = Path(__file__).resolve().parent / "artifacts" / "seismic_prior_v1.json"

#: Default search radius. Deliberately tighter than the 300 km the live
#: catalogue uses for attenuation: a 300 km radius around Gujarat reaches into
#: the Himalayan front, whose rate would swamp the local one and make every
#: zone look equally active. 100 km is about the scale at which "is this region
#: seismically quiet" is a meaningful question.
DEFAULT_RADIUS_KM = 100.0

EARTH_RADIUS_KM = 6371.0088


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


class SeismicPrior:
    """Background earthquake rate for a location, read from a static snapshot.

    Degrades to "no opinion" rather than raising: a missing or malformed
    artifact must not take the earthquake endpoint down, because the endpoint
    still has the live attenuation path to fall back on.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or ARTIFACT_PATH
        self._lock = threading.Lock()
        self._artifact: dict[str, Any] | None = None
        self._load_error: str | None = None
        self._load_failed = False

    # ── loading ───────────────────────────────────────────────────────────

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
                logger.warning("seismic_prior_missing", path=str(self._path))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self._load_error = f"artifact unusable: {exc}"
                self._load_failed = True
                logger.warning("seismic_prior_unusable", error=str(exc))
            else:
                self._artifact = raw
                logger.info(
                    "seismic_prior_loaded",
                    version=raw.get("model_version"),
                    cells=raw.get("cells_stored"),
                )
            return self._artifact

    @staticmethod
    def _validate(raw: dict[str, Any]) -> None:
        for key in ("model_version", "min_magnitude", "years", "cell_degrees", "cells"):
            if key not in raw:
                raise KeyError(f"artifact is missing {key!r}")
        if not isinstance(raw["cells"], dict):
            raise TypeError("cells is not an object")
        years = float(raw["years"])
        if not math.isfinite(years) or years <= 0.0:
            raise ValueError(f"years must be positive and finite, got {years!r}")
        if float(raw["cell_degrees"]) <= 0.0:
            raise ValueError("cell_degrees must be positive")

    @property
    def available(self) -> bool:
        return self._load() is not None

    @property
    def load_error(self) -> str | None:
        self._load()
        return self._load_error

    # ── queries ────────────────────────────────────────────────────────────

    def events_within(
        self, lat: float, lng: float, radius_km: float = DEFAULT_RADIUS_KM
    ) -> tuple[int, int, float]:
        """(events, cells, peak magnitude) in stored cells overlapping the radius.

        Cell overlap is a bounding-box test on cell corners, not a point count,
        so a cell is counted when any part of it falls inside the radius. That
        deliberately over-counts at the edge: the alternative silently drops a
        cell whose centre is just outside while the zone inside it is not.
        """
        artifact = self._load()
        if artifact is None:
            return 0, 0, 0.0
        cell_degrees = float(artifact["cell_degrees"])
        total = 0
        used = 0
        peak = 0.0
        for key, record in artifact["cells"].items():
            lat_index, lng_index = (int(part) for part in key.split(":"))
            centre_lat = (lat_index + 0.5) * cell_degrees
            centre_lng = (lng_index + 0.5) * cell_degrees
            # Nearest point of the cell to the query, so the test is "does this
            # cell reach into the radius" rather than "is its centre inside".
            near_lat = min(max(lat, lat_index * cell_degrees), (lat_index + 1) * cell_degrees)
            near_lng = min(max(lng, lng_index * cell_degrees), (lng_index + 1) * cell_degrees)
            if _haversine_km(lat, lng, near_lat, near_lng) > radius_km:
                continue
            total += int(record["events"])
            peak = max(peak, float(record["max_magnitude"]))
            used += 1
        return total, used, peak

    def rate_per_year(
        self, lat: float, lng: float, radius_km: float = DEFAULT_RADIUS_KM
    ) -> float | None:
        artifact = self._load()
        if artifact is None:
            return None
        events, _, _ = self.events_within(lat, lng, radius_km)
        return events / float(artifact["years"])

    def probability_in_window(
        self,
        lat: float,
        lng: float,
        hours: float = 12.0,
        radius_km: float = DEFAULT_RADIUS_KM,
    ) -> float | None:
        """P(at least one M+ event within `radius_km`) in `hours`, from a Poisson rate.

        This is a climatological at-least-one figure, not a forecast of the next
        window. It is small by construction, and callers must not present it as
        a prediction -- see `assess()` for the wording that is safe to show.
        """
        rate = self.rate_per_year(lat, lng, radius_km)
        if rate is None:
            return None
        if rate <= 0.0:
            return 0.0
        return 1.0 - math.exp(-rate * (hours / 8760.0))

    def assess(
        self, lat: float, lng: float, hours: float = 12.0, radius_km: float = DEFAULT_RADIUS_KM
    ) -> dict[str, Any] | None:
        """The prior plus the caveats, or None when the artifact is unusable."""
        artifact = self._load()
        if artifact is None:
            return None
        events, cells, peak = self.events_within(lat, lng, radius_km)
        rate = events / float(artifact["years"])
        probability = self.probability_in_window(lat, lng, hours, radius_km) or 0.0
        floor = float(artifact["min_magnitude"])
        return {
            "source": "usgs-comcat-background-rate",
            "model_id": artifact.get("model_id"),
            "model_version": artifact.get("model_version"),
            "available": True,
            "radius_km": radius_km,
            "window_hours": hours,
            "min_magnitude": floor,
            "events_within_radius": events,
            "cells_within_radius": cells,
            "peak_magnitude_in_history": round(peak, 1),
            "rate_per_year": round(rate, 4),
            "window_probability": round(probability, 6),
            "catalogue_years": artifact.get("years"),
            # Named as a climatology, not a prediction, at every level it is
            # exposed: a caller that copies only the number still carries the
            # qualifier with it.
            "interpretation": (
                f"Long-run rate of M{floor}+ events within {radius_km:.0f} km, "
                f"from the USGS catalogue. This is regional seismicity, not a "
                f"forecast: the {hours:.0f}-hour figure is what a constant-rate "
                f"process implies, not a prediction that one will occur."
            ),
            "is_prediction": False,
            "limitations": list(artifact.get("limitations") or ()),
        }

    def info(self) -> dict[str, Any]:
        artifact = self._load()
        if artifact is None:
            return {
                "available": False,
                "model_id": "aegis-seismic-prior",
                "reason": self._load_error or "artifact not built",
                "fallback": "live-catalogue attenuation (unchanged)",
            }
        return {
            "available": True,
            "model_id": artifact.get("model_id"),
            "model_version": artifact.get("model_version"),
            "source": artifact.get("source"),
            "min_magnitude": artifact.get("min_magnitude"),
            "years": artifact.get("years"),
            "cells_stored": artifact.get("cells_stored"),
            "events_in_catalogue": artifact.get("events_in_catalogue"),
            "is_prediction": False,
            "limitations": list(artifact.get("limitations") or ()),
        }


_PRIOR: SeismicPrior | None = None
_PRIOR_LOCK = threading.Lock()


def get_seismic_prior() -> SeismicPrior:
    global _PRIOR
    if _PRIOR is None:
        with _PRIOR_LOCK:
            if _PRIOR is None:
                _PRIOR = SeismicPrior()
    return _PRIOR
