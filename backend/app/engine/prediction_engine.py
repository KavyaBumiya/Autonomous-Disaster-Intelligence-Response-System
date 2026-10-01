"""
Prediction Engine v1 — Flood & Fire Spread Simulation.
Phase 3 deliverable. Cellular automata-based flood simulation and wind-directed
fire spread using shapely geometry for geospatial propagation.

Flood model:
- Grid-based cellular automata over zone geometry
- Propagation probability depends on: rainfall intensity, terrain slope,
  drainage proximity (distance to zone centroid treated as "water body")
- Spread direction: primarily downslope / towards zone centroid

Fire model:
- Wind-directed 2-step propagation using shapely buffer/offset
- Each step: new cells downwind based on wind_speed_kmh
- Probability decreases with distance from ignition point

Exports:
- predict_spread(zone_id, disaster_type, hours_ahead, db) → dict
- calculate_flood_spread(zone, rainfall_mm_hr, hours) → List[dict]
- calculate_fire_spread(zone, wind_speed_kmh, hours) → List[dict]
"""
from datetime import date, datetime, timedelta, timezone
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml.occurrence_model import get_flood_model, get_occurrence_model
from app.ml.seismic_prior import get_seismic_prior

# The feature definitions and the list of trainable hazards are shared with the
# offline pipeline, so the online and offline definitions are the same code.
from ml.hazards import TRAINED_HAZARDS
from app.models.zone import Zone
from app.models.incident import Incident

logger = structlog.get_logger()


# ── Helpers ───────────────────────────────────────────────────────────────

def _deg_to_rad(deg: float) -> float:
    return deg * 3.14159265358979 / 180.0


def _rad_to_deg(rad: float) -> float:
    return rad * 180.0 / 3.14159265358979


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km. Used by the seismic and rainfall-hazard
    models to measure how far an event or storm cell sits from the zone."""
    r_km = 6371.0
    d_lat = _deg_to_rad(lat2 - lat1)
    d_lng = _deg_to_rad(lng2 - lng1)
    a = (
        __import__("math").sin(d_lat / 2) ** 2
        + __import__("math").cos(_deg_to_rad(lat1))
        * __import__("math").cos(_deg_to_rad(lat2))
        * __import__("math").sin(d_lng / 2) ** 2
    )
    return 2 * r_km * __import__("math").asin(min(1.0, __import__("math").sqrt(a)))


# ── Flood Spread ──────────────────────────────────────────────────────────

async def _get_zone_geometry(zone_id: str, db: AsyncSession) -> dict:
    """Load zone with centroid and basic info."""
    result = await db.execute(select(Zone).where(Zone.id == zone_id))
    zone = result.scalar_one_or_none()
    if not zone:
        raise ValueError(f"Zone {zone_id} not found")
    return {
        "centroid_lat": zone.centroid_lat,
        "centroid_lng": zone.centroid_lng,
        "radius_meters": zone.radius_meters,
    }


async def _generate_flood_grid(zone_centroid_lat: float, zone_centroid_lng: float,
                               radius_meters: float, grid_cells: int = 10) -> list:
    """
    Generate a simple square grid of cells over the zone area.
    grid_cells x grid_cells cells covering the zone radius.
    Returns list of {(lat, lng)} cell centers.
    """
    # Approx: 1 degree lat ≈ 111km, 1 degree lng ≈ 111km * cos(lat)
    lat_deg = radius_meters / 111_000
    lng_deg = lat_deg / __import__("math").cos(_deg_to_rad(zone_centroid_lat))

    cells = []
    for i in range(grid_cells):
        for j in range(grid_cells):
            cell_lat = zone_centroid_lat - lat_deg/2 + (i * lat_deg / (grid_cells - 1))
            cell_lng = zone_centroid_lng - lng_deg/2 + (j * lng_deg / (grid_cells - 1))
            cells.append({"lat": cell_lat, "lng": cell_lng})
    return cells


def _flood_propagation_probability(rainfall_mm_hr: float, cell_elevation_relative: float,
                                   distance_to_centroid_km: float) -> float:
    """
    Rules-baseline flood probability.

    Retained as the fallback path and as the reference the trained model is
    measured against (`ml/train_flood_model.py::baseline_rule_scores`). Its
    coefficients were chosen by hand and never fitted to anything; the trained
    model in `app.ml.flood_model` is preferred whenever its antecedent-rainfall
    features can actually be built.

    - Higher rainfall → higher probability
    - Lower elevation (relative) → higher flood risk
    - Greater distance from centroid → lower probability (approximation)
    """
    # Rainfall factor: normalize at 50mm/hr as threshold
    rain_factor = min(1.0, rainfall_mm_hr / 50.0)

    # No rain, no flood. The elevation and distance terms below are unconditional,
    # so without this gate they contributed 0.35 on their own and a corroborating
    # report's evidence_boost (max 0.10) pushed the total to 0.41 -- over the 0.4
    # "flooded" threshold. The model therefore reported ~13% flood intensity for a
    # zone whose rain gauge read zero. Those terms describe how bad a flood gets
    # once it is raining; they cannot create one.
    if rainfall_mm_hr <= 0:
        return 0.0

    # Elevation factor: lower = riskier (we simulate relative elevation 0-1)
    elev_risk = 1.0 - min(1.0, abs(cell_elevation_relative))

    # Distance factor: shorter distance → higher risk
    dist_factor = max(0.0, 1.0 - distance_to_centroid_km / 10.0)  # 10km falloff

    # Combined probability [0, 1]
    prob = round(rain_factor * 0.5 + elev_risk * 0.3 + dist_factor * 0.2, 3)
    return prob


# ── Trained flood model (app.ml.flood_model) ───────────────────────────────
# The rules above ask "how bad does a cell get once it is raining". The trained
# model asks the prior question -- "did a flood occur at all in this cell given
# the recent rain" -- and answers it from 144 GDACS flood records instead of
# from hand-picked constants. The two are composed rather than swapped: the
# trained probability sets the zone-level level, and the same 10 km distance
# falloff spreads it across cells, because the fitted model has no opinion
# about intra-zone geometry.

FLOOD_MODEL_HISTORY_DAYS = 10
# The poller samples every ~5 minutes, so a healthy day contributes ~288 rows.
# Requiring a solid share of the window stops a three-hour-old database from
# being scored as if it held a decade of antecedent rainfall.
FLOOD_MODEL_MIN_DAYS = 6
FLOOD_DRY_DAY_MM = 1.0

# Hazards with a fitted occurrence model. The artifact, the feature list and the
# feature definitions all live in `ml/hazards.py`; this module only supplies the
# observations. Seismic and landslide are absent on purpose -- see
# `ml.hazards.DECLINED_HAZARDS` for why neither can honestly be fitted.
OCCURRENCE_HAZARDS: tuple[str, ...] = tuple(TRAINED_HAZARDS)


def _flood_spatial_decay(distance_to_centroid_km: float) -> float:
    """Spread a zone-level probability over the grid.

    1.0 at the centroid, easing to 0.5 at the 10 km falloff used by the rules
    baseline. Multiplying (rather than adding, as the rule does) keeps the
    centroid cell equal to the trained zone probability.
    """
    return 0.5 + 0.5 * max(0.0, 1.0 - distance_to_centroid_km / 10.0)


async def _daily_history(
    zone_id: str, db: AsyncSession, days: int
) -> dict[date, dict[str, float]]:
    """Collapse the poller's samples into one record per calendar day.

    A day the poller never sampled is simply absent from the mapping. It is not
    filled with zeros anywhere downstream: an unobserved day is not evidence of
    no rain, and reading it that way would manufacture both a drought and a
    calm -- precisely the conditions these models exist to detect.
    """
    from sqlalchemy import and_

    from app.models.weather import WeatherReading

    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                WeatherReading.polled_at,
                WeatherReading.rainfall_mm_hr,
                WeatherReading.temperature_c,
                WeatherReading.wind_speed_kmh,
                WeatherReading.humidity_pct,
                WeatherReading.pressure_hpa,
            )
            .where(
                and_(
                    WeatherReading.zone_id == zone_id,
                    WeatherReading.polled_at >= since,
                )
            )
            .order_by(WeatherReading.polled_at)
            .limit(20000)
        )
    ).all()

    by_day: dict[date, dict[str, float]] = {}
    for polled_at, rain, temperature, wind, humidity, pressure in rows:
        if polled_at is None:
            continue
        if polled_at.tzinfo is None:
            polled_at = polled_at.replace(tzinfo=timezone.utc)
        day = polled_at.date()
        record = by_day.setdefault(day, {"samples": 0, "rain_total": 0.0})
        record["samples"] = record.get("samples", 0) + 1
        if rain is not None:
            # Samples are rainfall *rates* in mm/hr, so a day's total is the
            # mean rate over 24 hours, not a sum of five-minute readings.
            record["rain_total"] = record.get("rain_total", 0.0) + float(rain)
        if temperature is not None:
            record["temp_max"] = max(record.get("temp_max", float("-inf")), float(temperature))
        if wind is not None:
            record["wind_max"] = max(record.get("wind_max", float("-inf")), float(wind))
        # Pressure and humidity are averaged over the day's samples, matching the
        # ERA5 daily means the offline extractor is fitted on. Each is tracked
        # with its own present-value count: a day whose humidity is entirely NULL
        # stays absent for humidity rather than averaging to zero, which would
        # read as bone-dry air.
        for name, value in (("humidity", humidity), ("pressure", pressure)):
            if value is None:
                continue
            record[f"{name}_sum"] = record.get(f"{name}_sum", 0.0) + float(value)
            record[f"{name}_n"] = record.get(f"{name}_n", 0) + 1

    for record in by_day.values():
        samples = record.get("samples", 0)
        record["precipitation_sum"] = (
            round(record.get("rain_total", 0.0) / samples * 24.0, 3) if samples else None
        )
        record["pressure_msl_mean"] = _daily_mean(record, "pressure")
        record["relative_humidity_2m_mean"] = _daily_mean(record, "humidity")
        for key in (
            "samples", "rain_total",
            "pressure_sum", "pressure_n", "humidity_sum", "humidity_n",
        ):
            record.pop(key, None)
    return by_day


def _daily_mean(record: dict[str, float], prefix: str) -> float | None:
    """Mean of one aggregated variable for a day, or None if never observed."""
    count = record.get(f"{prefix}_n", 0)
    if not count:
        return None
    return round(record.get(f"{prefix}_sum", 0.0) / count, 3)


def _history_as_archive_entry(
    history: dict[date, dict[str, float]], days: int, elevation: float
) -> dict:
    """Render the daily history in the shape the offline extractor expects.

    The feature definitions in `ml/hazards.py` are the single source of truth for
    every hazard, and they are written against an Open-Meteo daily block because
    that is what the training data looked like. Rather than restate the window
    arithmetic here -- where it would silently drift away from the training code
    the first time a window changed -- the observations are rendered into the
    same shape and handed to the same functions.
    """
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = yesterday - timedelta(days=days - 1)
    times: list[str] = []
    series: dict[str, list[float | None]] = {
        "precipitation_sum": [],
        "temperature_2m_max": [],
        "wind_speed_10m_max": [],
        "pressure_msl_mean": [],
        "relative_humidity_2m_mean": [],
    }
    for offset in range(days):
        day = start + timedelta(days=offset)
        record = history.get(day) or {}
        times.append(day.isoformat())
        for name, source in (
            ("precipitation_sum", "precipitation_sum"),
            ("temperature_2m_max", "temp_max"),
            ("wind_speed_10m_max", "wind_max"),
            ("pressure_msl_mean", "pressure_msl_mean"),
            ("relative_humidity_2m_mean", "relative_humidity_2m_mean"),
        ):
            series[name].append(record.get(source))
    return {
        "elevation": elevation,
        "daily": {"time": times, **series},
    }


async def _occurrence_features(
    hazard: str, zone_id: str, db: AsyncSession
) -> dict[str, float] | None:
    """Build one hazard's model features from the poller history.

    Returns None whenever the model should not be trusted to answer: no usable
    artifact, too little history, or a feature the poller cannot supply. The
    caller treats None as "use the rules", which is always safe.
    """
    spec = TRAINED_HAZARDS[hazard]
    model = get_occurrence_model(hazard)
    if not model.available:
        return None

    history = await _daily_history(zone_id, db, spec.antecedent_days)
    if len(history) < min(FLOOD_MODEL_MIN_DAYS, spec.antecedent_days):
        return None

    # `zones` has no elevation column, so the model is fed the training-set
    # mean. That makes the standardised elevation exactly zero, i.e. no
    # contribution at all -- the neutral choice, where an invented terrain
    # number would not be.
    elevation = model.training_mean("elevation_m")
    if elevation is None:
        return None

    entry = _history_as_archive_entry(history, spec.antecedent_days, elevation)
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    features = spec.extract(entry, yesterday + timedelta(days=1), spec.antecedent_days)
    if features is None:
        return None
    return {name: features[name] for name in spec.feature_columns}


async def _antecedent_rain_features(zone_id: str, db: AsyncSession) -> dict | None:
    """Flood antecedent-rainfall features. Kept as the flood-specific name.

    The arithmetic lives in `ml.hazards.extract_flood`, shared with the offline
    dataset builder, so the online and offline definitions cannot drift apart.
    """
    return await _occurrence_features("flood", zone_id, db)


async def calculate_flood_spread(zone_id: str, rainfall_mm_hr: float,
                                 hours: int = 12, db: AsyncSession = None,
                                 evidence_boost: float = 0.0) -> dict:
    """
    Calculate flood spread simulation for a zone over given hours.

    evidence_boost (Phase 10): small bounded delta [0, EVIDENCE_BOOST_MAX]
    added to cell propagation probability from corroborating reports.

    Returns dict with:
    - affected_cells: List[{"lat": float, "lng": float, "intensity": float, "time_step": int}]
    - max_intensity: float (0-100)
    - flooded_percentage: float (0-100)
    - expires_at: datetime
    """
    # Load zone data if db session not provided
    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await calculate_flood_spread(zone_id, rainfall_mm_hr, hours, _db,
                                                evidence_boost=evidence_boost)

    zone = await _get_zone_geometry(zone_id, db)
    cells = await _generate_flood_grid(zone["centroid_lat"], zone["centroid_lng"],
                                       zone["radius_meters"], grid_cells=12)

    # Trained model supplies the zone-level probability; the rules baseline
    # remains the fallback whenever the antecedent rainfall history needed to
    # build the features is not there yet.
    trained = await _trained_flood_assessment(zone_id, db)

    results = []
    current_expire = datetime.now(timezone.utc)

    for step in range(1, hours + 1):
        for cell in cells:
            # Simple distance from centroid
            import math
            lat_diff = cell["lat"] - zone["centroid_lat"]
            lng_diff = cell["lng"] - zone["centroid_lng"]
            dist_km = math.sqrt(lat_diff ** 2 + lng_diff ** 2) * 111.0

            if trained is not None:
                # No rain in the antecedent window means no flood, whatever the
                # instantaneous gauge says. The fitted model was never shown a
                # dry baseline, so this gate stays explicit.
                prob = (
                    round(trained.probability * _flood_spatial_decay(dist_km), 3)
                    if rainfall_mm_hr > 0
                    else 0.0
                )
            else:
                prob = _flood_propagation_probability(
                    rainfall_mm_hr, cell.get("elevation_rel", 0.5), dist_km
                )
            if evidence_boost:
                prob = min(1.0, round(prob + evidence_boost, 3))

            # Propagate: if prob > threshold, cell becomes flooded at this time step
            if prob > 0.4:  # threshold for "flooded"
                intensity = round(min(100, prob * 20 + step * 5), 1)
                results.append({
                    "lat": cell["lat"],
                    "lng": cell["lng"],
                    "intensity": intensity,
                    "time_step": step,
                })

    if not results:
        # Still return structure even if no cells flood
        results = [{"lat": zone["centroid_lat"], "lng": zone["centroid_lng"],
                    "intensity": 0, "time_step": 0}]

    # Deduplicate by rounding coords
    seen = set()
    unique = []
    for r in results:
        key = (round(r["lat"], 4), round(r["lng"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    # Compute summary
    max_intensity = max(r["intensity"] for r in unique) if unique else 0
    flooded_pct = round(len([r for r in unique if r["intensity"] > 0]) / max(len(unique), 1) * 100, 1)

    result = {
        "affected_cells": unique,
        "max_intensity": max_intensity,
        "flooded_percentage": flooded_pct,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=hours),
    }
    result["model"] = (
        {
            "source": "trained",
            "model_id": trained.model_id,
            "model_version": trained.model_version,
            "probability": trained.probability,
            "features": trained.features,
            "contributions": trained.contributions,
            "driver_share": trained.driver_share,
            "explanation": trained.explain(),
        }
        if trained is not None
        else {
            "source": "rules-baseline",
            "model_id": "aegis-flood-rules",
            "model_version": "v1",
            "reason": get_flood_model().load_error
            or "antecedent rainfall history too short to build model features",
            "coefficients_are": "hand-chosen, never fitted to observations",
        }
    )
    return result


async def _trained_flood_assessment(zone_id: str, db: AsyncSession):
    """Score the zone with the trained model, or None to signal the fallback."""
    features = await _antecedent_rain_features(zone_id, db)
    if features is None:
        return None
    return get_flood_model().assess(features)


# ── Fire Spread ───────────────────────────────────────────────────────────

def _fire_wind_direction(wind_speed_kmh: float) -> float:
    """
    Convert wind speed to a direction factor for fire spread.
    Returns a unit vector angle in radians, based on typical disaster data.
    Higher wind → faster, further spread.
    """
    # For MVP: wind speed modulates spread probability & distance
    # Direction is simulated as a constant direction; speed affects extent
    return wind_speed_kmh / 10.0  # scale factor


async def calculate_fire_spread(zone_id: str, wind_speed_kmh: float,
                                hours: int = 12, db: AsyncSession = None) -> dict:
    """
    Calculate fire spread simulation for a zone over given hours.

    Uses shapely buffer/offset downwind direction.
    Returns dict with:
    - burned_area: List[{"lat": float, "lng": float, "intensity": float, "time_step": int}]
    - max_intensity: float (0-100)
    - spread_direction_degrees: float
    - expires_at: datetime
    """
    import math
    from shapely.geometry import Point

    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await calculate_fire_spread(zone_id, wind_speed_kmh, hours, _db)

    zone = await _get_zone_geometry(zone_id, db)

    # Wind direction factor (simplified: we use wind_speed as magnitude factor)
    wind_factor = _fire_wind_direction(wind_speed_kmh)

    # Create ignition point at zone centroid
    ignition = Point(zone["centroid_lng"], zone["centroid_lat"])

    # Build spread using sequential buffers based on wind speed and time
    burned_cells = []
    results = []

    for step in range(1, hours + 1):
        # Distance increases with wind speed and step count
        step_distance = wind_speed_kmh * step * 0.5  # 0.5km per (km/h * step) approx

        # Offset point downwind (we use a simplified angle; in production would use real wind dir)
        # For MVP: radial spread modulated by wind factor
        angle = wind_factor * step * 0.1  # gradual directional bias
        offset_lng = math.sin(angle) * step_distance / 111.0
        offset_lat = math.cos(angle) * step_distance / 111.0

        spread_point = Point(zone["centroid_lng"] + offset_lng,
                             zone["centroid_lat"] + offset_lat)

        # Create a small buffer cell around the spread point
        cell_buffer = spread_point.buffer(0.02)  # ~2km radius in lat/lng terms

        # Sample a few points within the buffer to represent the "cell"
        for p in [spread_point, Point(spread_point.x + 0.01, spread_point.y),
                  Point(spread_point.x, spread_point.y + 0.01)]:
            intensity = round(min(100, wind_speed_kmh * 2 + step * 3), 1)
            burned_cells.append({
                "lat": p.y,
                "lng": p.x,
                "intensity": intensity,
                "time_step": step,
            })

        results.extend(burned_cells)

    # Deduplicate
    seen = set()
    unique = []
    for cell in results:
        key = (round(cell["lat"], 4), round(cell["lng"], 4))
        if key not in seen:
            seen.add(key)
            unique.append(cell)

    max_intensity = max((c["intensity"] for c in unique), default=0)

    return {
        "burned_area": unique,
        "max_intensity": max_intensity,
        "spread_direction_degrees": round(wind_factor * 45, 1) if wind_factor else 0.0,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=hours),
    }


# ── Real inputs (Phase 10) ─────────────────────────────────────────────────
# Defaults preserve the pre-Phase-10 behaviour when no data exists
# (hard-coded 50 mm/hr / 20 km/h — now explicitly labelled as assumptions).
DEFAULT_RAINFALL_MM_HR = 50.0
DEFAULT_WIND_SPEED_KMH = 20.0
DEFAULT_LABEL = "no weather data — default assumption (pre-Phase-10 value)"
EVIDENCE_BOOST_MAX = 0.10       # max probability delta from corroborating reports


async def _latest_weather(zone_id: str, db: AsyncSession):
    """Most recent weather reading for the zone (any age — labelled by caller)."""
    from app.models.weather import WeatherReading

    result = await db.execute(
        select(WeatherReading)
        .where(WeatherReading.zone_id == zone_id)
        .order_by(WeatherReading.polled_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _reading_age_minutes(polled_at: datetime | None) -> float | None:
    """Age of a reading in minutes, or None when it carries no timestamp."""
    if polled_at is None:
        return None
    if polled_at.tzinfo is None:
        # The column is timestamptz but SQLite fixtures can hand back naive
        # datetimes; assume UTC rather than reading them as local wall clock.
        polled_at = polled_at.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - polled_at).total_seconds() / 60.0)


def _stale_reason(polled_at: datetime | None) -> str | None:
    """Reason string when a reading is too old to present as current, else None."""
    age = _reading_age_minutes(polled_at)
    if age is None:
        return "weather reading has no timestamp"
    if age > WEATHER_MAX_AGE_MINUTES:
        return (
            f"weather reading is stale ({int(age)} min old, limit "
            f"{int(WEATHER_MAX_AGE_MINUTES)} min) — the weather poller is "
            f"not keeping up, so no current observation is available"
        )
    return None


async def _active_incident(zone_id: str, db: AsyncSession):
    from sqlalchemy import and_

    result = await db.execute(
        select(Incident).where(
            and_(Incident.zone_id == zone_id, Incident.active == True)
        ).limit(1)
    )
    return result.scalar_one_or_none()


async def _flood_evidence(zone_id: str, db: AsyncSession) -> dict:
    """Flood evidence from reports/incident (deterministic, DB only)."""
    from sqlalchemy import and_, func as sa_func

    from app.models.report import Report

    incident = await _active_incident(zone_id, db)
    corroborating = (
        await db.execute(
            select(sa_func.count(Report.id)).where(
                and_(Report.zone_id == zone_id, Report.suppressed == False)  # noqa: E712
            )
        )
    ).scalar() or 0
    return {
        "corroborating_reports": int(corroborating),
        "active_incident": incident is not None,
        "incident_severity": float(getattr(incident, "severity_score", 0.0) or 0.0)
        if incident
        else 0.0,
        "incident_disaster_type": getattr(incident, "disaster_type", None)
        if incident
        else None,
    }


async def _gis_context(zone_id: str, db: AsyncSession) -> dict:
    """Cached GIS features around the zone (bbox counts — no network)."""
    from sqlalchemy import and_, func as sa_func

    from app.models.infrastructure import Infrastructure
    from app.services.gis_service import bbox_for_radius

    from app.models.zone import Zone

    zone = (await db.execute(select(Zone).where(Zone.id == zone_id))).scalar_one_or_none()
    if not zone:
        return {"available": False, "reason": "zone not found"}
    south, west, north, east = bbox_for_radius(
        zone.centroid_lat, zone.centroid_lng,
        max(1000.0, float(zone.radius_meters or 500) * 4),
    )
    rows = (
        await db.execute(
            select(Infrastructure.category, sa_func.count(Infrastructure.id))
            .where(
                and_(
                    Infrastructure.lat.between(south, north),
                    Infrastructure.lng.between(west, east),
                )
            )
            .group_by(Infrastructure.category)
        )
    ).all()
    counts = {str(cat): int(n) for cat, n in rows}
    if not counts:
        return {
            "available": False,
            "reason": "no cached GIS features near zone (refresh zone infrastructure)",
            "counts": {},
        }
    critical = sum(counts.get(c, 0) for c in ("hospital", "clinic", "shelter"))
    return {
        "available": True,
        "counts": counts,
        "feature_count": sum(counts.values()),
        "critical_features": critical,
    }


async def _nearest_seismic(zone: dict, db: AsyncSession, hours: int = 72,
                           max_km: float = 300.0) -> dict | None:
    """Strongest recent seismic event within `max_km` of the zone centroid.

    Backed by `seismic_events` (USGS poller, 2-minute cadence). Returns the
    single most dangerous qualifying event, or None when the catalogue holds
    nothing recent nearby -- which is a real answer, not missing data.
    """
    from datetime import timedelta

    from app.models.seismic import SeismicEvent

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        await db.execute(
            select(SeismicEvent)
            .where(SeismicEvent.event_time >= since)
            .order_by(SeismicEvent.event_time.desc())
            .limit(200)
        )
    ).scalars().all()

    best = None
    for event in rows:
        distance = _haversine_km(
            zone["centroid_lat"], zone["centroid_lng"], event.lat, event.lng
        )
        if distance > max_km:
            continue
        # Rank by magnitude first, then proximity.
        if best is None or (event.magnitude, -distance) > (best["magnitude"], -best["distance_km"]):
            best = {
                "magnitude": float(event.magnitude),
                "depth_km": float(event.depth_km) if event.depth_km is not None else 10.0,
                "distance_km": round(distance, 1),
                "place": event.place_description or "",
                "event_time": event.event_time,
                "usgs_id": event.usgs_id,
            }
    return best


async def _rainfall_window(zone_id: str, db: AsyncSession, hours: int = 24) -> dict:
    """Observed rainfall over the trailing `hours`.

    Poll samples are point readings, not an accumulation series, so the driver
    is the observed PEAK rate rather than a sum -- summing 5-minute samples
    would invent an accumulation figure the data does not support.
    """
    from datetime import timedelta

    from sqlalchemy import and_

    from app.models.weather import WeatherReading

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = (
        await db.execute(
            select(WeatherReading.rainfall_mm_hr, WeatherReading.polled_at)
            .where(
                and_(
                    WeatherReading.zone_id == zone_id,
                    WeatherReading.polled_at >= since,
                )
            )
            .order_by(WeatherReading.polled_at.desc())
            .limit(200)
        )
    ).all()

    if not rows:
        return {"available": False, "reason": "no rainfall reading in window", "peak_mm_hr": 0.0,
                "mean_mm_hr": 0.0, "samples": 0, "window_hours": hours}

    newest_polled_at = rows[0][1]
    stale = _stale_reason(newest_polled_at)
    if stale is not None:
        # The window filter only bounds age by `hours`; a poller that stopped
        # hours ago still leaves rows inside a 24 h window. Report the gap
        # instead of summarising a stretch of history as if it were current.
        return {"available": False, "reason": stale, "peak_mm_hr": 0.0,
                "mean_mm_hr": 0.0, "samples": 0, "window_hours": hours,
                "newest_reading_age_min": round(_reading_age_minutes(newest_polled_at) or 0.0, 1)}

    values = [float(v) for v, _ in rows if v is not None]
    if not values:
        return {"available": False, "reason": "no rainfall reading in window", "peak_mm_hr": 0.0,
                "mean_mm_hr": 0.0, "samples": 0, "window_hours": hours}
    return {
        "available": True,
        "peak_mm_hr": round(max(values), 2),
        "mean_mm_hr": round(sum(values) / len(values), 2),
        "samples": len(values),
        "window_hours": hours,
        "newest_reading_age_min": round(_reading_age_minutes(newest_polled_at) or 0.0, 1),
    }


# ── Extended hazard projections (Phase 18) ─────────────────────────────────
# Flood and fire SPREAD across space, so they resolve a grid of cells.
# Earthquake, landslide and wind storm act over an area far larger than a zone
# footprint, so within a ~500 m zone they are effectively uniform. Modelling
# them as a spatial spread would fabricate detail the source data cannot
# support. They therefore return a zone-uniform intensity, tag the result with
# spatial_resolution="zone_uniform", and carry an explicit limitations list.
# The console renders these as intensity metrics rather than hazard maps.

# A weather poll older than this is reported as unavailable rather than used.
# The poller can be rate-limited (open-meteo returns HTTP 429 on the free tier),
# which leaves a row in weather_readings that is perfectly well-formed and days
# old. Reading it as current weather would present stale numbers as an
# observation, so age is treated as missing data.
WEATHER_MAX_AGE_MINUTES = 90.0        # ~18x the 5-minute poll cadence

SEISMIC_MAGNITUDE_FLOOR = 3.0        # below this, shaking is not perceptible
SEISMIC_MAGNITUDE_CEIL = 7.0         # at/above this, local exposure is total
SEISMIC_DEPTH_REFERENCE_KM = 60.0
SEISMIC_DISTANCE_REFERENCE_KM = 300.0
LANDSLIDE_SATURATION_MM_HR = 75.0    # rainfall rate that saturates slopes
STORM_IMPACT_FLOOR_KMH = 40.0        # below this, structural impact is negligible
STORM_IMPACT_CEIL_KMH = 120.0        # hurricane force


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _zone_grid(zone: dict, grid_cells: int = 3) -> list:
    """Sync 3x3 grid of cell centres over the zone footprint."""
    import math

    lat_deg = zone["radius_meters"] / 111_000
    lng_deg = lat_deg / math.cos(_deg_to_rad(zone["centroid_lat"]))
    return [
        {
            "lat": zone["centroid_lat"] - lat_deg / 2 + (i * lat_deg / (grid_cells - 1)),
            "lng": zone["centroid_lng"] - lng_deg / 2 + (j * lng_deg / (grid_cells - 1)),
        }
        for i in range(grid_cells)
        for j in range(grid_cells)
    ]


def _seismic_shaking_probability(magnitude: float, depth_km: float,
                                 distance_km: float) -> float:
    """Shaking exposure at the zone for a given event. Mirrors the weighted
    factor structure of the flood model so the two read consistently.

    Below the perceptibility floor the result is exactly zero: the depth and
    distance terms are non-zero even for a trivial event, so without this gate
    a M2 tremor kilometres away would register as real exposure.
    """
    if magnitude <= SEISMIC_MAGNITUDE_FLOOR:
        return 0.0
    mag_factor = _clamp01(
        (magnitude - SEISMIC_MAGNITUDE_FLOOR)
        / (SEISMIC_MAGNITUDE_CEIL - SEISMIC_MAGNITUDE_FLOOR)
    )
    depth_factor = _clamp01(1.0 - depth_km / SEISMIC_DEPTH_REFERENCE_KM)
    dist_factor = _clamp01(1.0 - distance_km / SEISMIC_DISTANCE_REFERENCE_KM)
    return round(mag_factor * 0.5 + depth_factor * 0.2 + dist_factor * 0.3, 3)


def _landslide_susceptibility(peak_rain_mm_hr: float) -> float:
    """Slope-failure susceptibility from observed rainfall rate.

    Only the rainfall leg of a real landslide model (antecedent moisture,
    slope angle, lithology) is available here; the rest is reported as a
    limitation rather than guessed."""
    return round(_clamp01(peak_rain_mm_hr / LANDSLIDE_SATURATION_MM_HR), 3)


def _storm_impact_probability(wind_speed_kmh: float) -> float:
    """Structural impact probability from sustained wind (gale -> hurricane)."""
    span = STORM_IMPACT_CEIL_KMH - STORM_IMPACT_FLOOR_KMH
    return round(_clamp01((wind_speed_kmh - STORM_IMPACT_FLOOR_KMH) / span), 3)


def _zone_uniform_projection(zone: dict, probability: float, hours: int,
                             coverage_threshold: float = 0.05) -> dict:
    """Shared shape for hazards that do not resolve spatially within a zone."""
    probability = _clamp01(probability)
    if probability > coverage_threshold:
        intensity = round(probability * 100.0, 1)
        cells = [
            {"lat": c["lat"], "lng": c["lng"], "intensity": intensity, "time_step": 0}
            for c in _zone_grid(zone)
        ]
        coverage = 100.0
    else:
        cells = [{
            "lat": zone["centroid_lat"],
            "lng": zone["centroid_lng"],
            "intensity": 0,
            "time_step": 0,
        }]
        coverage = 0.0

    return {
        "affected_cells": cells,
        "max_intensity": round(probability * 100.0, 1),
        "coverage_percentage": coverage,
        "spatial_resolution": "zone_uniform",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=hours),
    }


async def calculate_seismic_shaking(zone_id: str, hours: int = 12,
                                    db: AsyncSession = None) -> dict:
    """Seismic shaking exposure for a zone, from the USGS event catalogue.

    `available` is False when the catalogue holds no qualifying recent event
    nearby. That is a genuine all-clear, and is reported as such rather than
    being filled with a default magnitude.
    """
    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await calculate_seismic_shaking(zone_id, hours, _db)

    zone = await _get_zone_geometry(zone_id, db)
    event = await _nearest_seismic(zone, db, hours=72, max_km=SEISMIC_DISTANCE_REFERENCE_KM)

    # The background rate is reported alongside the live result, in both
    # branches, because it answers a different question: not "is the ground
    # shaking now" but "how seismically active is this place". It is explicitly
    # not a forecast, and `assess()` carries that qualifier with the number.
    prior = get_seismic_prior().assess(
        zone.get("centroid_lat", 0.0), zone.get("centroid_lng", 0.0), hours=float(hours)
    )

    if event is None:
        result = _zone_uniform_projection(zone, 0.0, hours, coverage_threshold=0.0)
        result.update({
            "available": False,
            "reason": "no seismic event within 300 km in the last 72 h",
            "event": None,
            "background_rate": prior,
        })
        return result

    probability = _seismic_shaking_probability(
        event["magnitude"], event["depth_km"], event["distance_km"]
    )
    result = _zone_uniform_projection(zone, probability, hours)
    result.update({
        "available": True,
        "reason": None,
        "event": {
            "magnitude": event["magnitude"],
            "depth_km": event["depth_km"],
            "distance_km": event["distance_km"],
            "place": event["place"],
            "event_time": event["event_time"].isoformat() if event["event_time"] else None,
            "usgs_id": event["usgs_id"],
        },
        "shaking_probability": probability,
        "background_rate": prior,
    })
    return result


async def calculate_landslide_risk(zone_id: str, hours: int = 12,
                                  db: AsyncSession = None) -> dict:
    """Rainfall-driven landslide susceptibility for a zone."""
    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await calculate_landslide_risk(zone_id, hours, _db)

    zone = await _get_zone_geometry(zone_id, db)
    window = await _rainfall_window(zone_id, db, hours=24)

    if not window["available"]:
        result = _zone_uniform_projection(zone, 0.0, hours, coverage_threshold=0.0)
        result.update({
            "available": False,
            "reason": window["reason"],
            "rainfall_window": window,
        })
        return result

    probability = _landslide_susceptibility(window["peak_mm_hr"])
    result = _zone_uniform_projection(zone, probability, hours)
    result.update({
        "available": True,
        "reason": None,
        "rainfall_window": window,
        "susceptibility": probability,
    })
    return result


async def calculate_storm_impact(zone_id: str, wind_speed_kmh: float | None = None,
                                 hours: int = 12, db: AsyncSession = None) -> dict:
    """Wind-driven structural impact for a zone."""
    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await calculate_storm_impact(zone_id, wind_speed_kmh, hours, _db)

    zone = await _get_zone_geometry(zone_id, db)
    if wind_speed_kmh is not None:
        wind, wind_source = float(wind_speed_kmh), "request_parameter"
        stale_reason = None
    else:
        weather = await _latest_weather(zone_id, db)
        stale_reason = _stale_reason(weather.polled_at) if weather is not None else None
        if stale_reason is not None:
            # Do not fall back to the default here: a default wind figure would
            # present as a current observation when the real problem is that no
            # current observation exists.
            result = _zone_uniform_projection(zone, 0.0, hours, coverage_threshold=0.0)
            result.update({
                "available": False,
                "reason": stale_reason,
                "wind_speed_kmh": None,
                "wind_source": "unavailable",
                "impact_probability": None,
            })
            return result
        if weather is not None:
            wind = float(weather.wind_speed_kmh or 0.0)
            wind_source = (
                f"weather_reading:open-meteo @ {weather.polled_at.isoformat()}"
                if weather.polled_at
                else "weather_reading:open-meteo"
            )
        else:
            wind, wind_source = DEFAULT_WIND_SPEED_KMH, DEFAULT_LABEL

    probability = _storm_impact_probability(wind)
    result = _zone_uniform_projection(zone, probability, hours)
    result.update({
        "available": True,
        "reason": None,
        "wind_speed_kmh": wind,
        "wind_source": wind_source,
        "impact_probability": probability,
    })
    return result


# ── Hazard catalogue ───────────────────────────────────────────────────────

HAZARD_CATALOGUE: dict[str, dict] = {
    "flood": {
        "display_name": "Flash flood propagation",
        "modelled": "spatially",
        "driver": "rainfall_mm_hr",
    },
    "fire": {
        "display_name": "Wildfire spread",
        "modelled": "spatially",
        "driver": "wind_speed_kmh",
    },
    "earthquake": {
        "display_name": "Seismic shaking exposure",
        "modelled": "zone_uniform",
        "driver": "magnitude",
    },
    "landslide": {
        "display_name": "Landslide susceptibility",
        "modelled": "zone_uniform",
        "driver": "rainfall_mm_hr",
    },
    "storm": {
        "display_name": "Wind storm impact",
        "modelled": "zone_uniform",
        "driver": "wind_speed_kmh",
    },
}

HAZARD_LIMITATIONS: dict[str, list[str]] = {
    "flood": [
        "Zone-level probability is fitted (see app/ml/artifacts); the spread "
        "across cells is a 10 km distance falloff, not a hydraulic simulation.",
        "Cell elevation is assumed uniform; no terrain DEM is available.",
        "Distance-to-centroid is used as a drainage proxy, not a real channel.",
        "Fitted coefficients come from 144 GDACS flood records, whose alert "
        "polygons are coarse. The reported probability is a ranking score under "
        "a 1:2 sampling frame, not calibrated field incidence.",
    ],
    "fire": [
        "Spread direction is a speed-derived bias, not an observed wind vector.",
        "No fuel or vegetation model is applied.",
    ],
    "earthquake": [
        "Only the strongest qualifying event is projected; aftershock sequences "
        "are not modelled.",
        "Zone-uniform: shaking varies negligibly across a few hundred metres, "
        "so no spatial map is produced.",
        "The background rate reported alongside is a long-run USGS catalogue "
        "rate, not a forecast. It says how active the region has been, and the "
        "window probability derived from it is a climatological at-least-one "
        "figure, not a prediction that an earthquake will occur. Aftershocks "
        "are not declustered, so a cell's rate is a floor on its activity.",
    ],
    "landslide": [
        "Rainfall is the only driver available. Slope angle, lithology and "
        "antecedent moisture are absent, so this under-reports real risk.",
        "Zone-uniform for the same reason as earthquake.",
    ],
    "storm": [
        "Wind speed only for the rules baseline. No gust factor, direction or "
        "duration distribution.",
        "No asset vulnerability model; impact is not weighted by what is built.",
        "A fitted storm-occurrence model ships in app/ml/artifacts but is not "
        "yet consulted on this path: the projection below is the wind ramp, not "
        "the trained score.",
    ],
}


# ── Main API ──────────────────────────────────────────────────────────────

async def predict_spread(zone_id: str, disaster_type: str, hours_ahead: int = 12,
                         db: AsyncSession = None,
                         rainfall_mm_hr: float | None = None,
                         wind_speed_kmh: float | None = None) -> dict:
    """
    Main entry point for prediction engine.

    Phase 10: real inputs from `weather_readings` when callers do not pass
    explicit parameters (was: hard-coded 50 mm/hr / 20 km/h). Explicit
    request parameters still win; absence of data falls back to the legacy
    defaults, labelled as assumptions — never fabricated as observations.
    Flood projections additionally accept corroborating-report evidence
    (small bounded probability boost) and GIS exposure context.

    Args:
        zone_id: Zone identifier
        disaster_type: one of HAZARD_CATALOGUE ("flood", "fire", "earthquake",
            "landslide", "storm")
        hours_ahead: Number of hours to simulate (default 12)
        db: AsyncSession (lazy-creates if None)
        rainfall_mm_hr: explicit override (POST /predictions/flood, what-if)
        wind_speed_kmh: explicit override (POST /predictions/fire, what-if)

    Returns dict with simulation results + additive metadata:
        projection_label: "MODEL PROJECTION" (PRD §18)
        inputs: resolved driver values + their provenance
        generated_at: ISO timestamp
    """
    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await predict_spread(
                zone_id, disaster_type, hours_ahead, _db,
                rainfall_mm_hr=rainfall_mm_hr, wind_speed_kmh=wind_speed_kmh,
            )

    weather = await _latest_weather(zone_id, db)
    evidence = await _flood_evidence(zone_id, db)
    gis_ctx = await _gis_context(zone_id, db)

    if disaster_type.lower() == "flood":
        if rainfall_mm_hr is not None:
            rain, rain_source = float(rainfall_mm_hr), "request_parameter"
        elif weather is not None:
            rain = float(weather.rainfall_mm_hr or 0.0)
            rain_source = (
                f"weather_reading:open-meteo @ {weather.polled_at.isoformat()}"
                if weather.polled_at
                else "weather_reading:open-meteo"
            )
        else:
            rain, rain_source = DEFAULT_RAINFALL_MM_HR, DEFAULT_LABEL

        # Bounded evidence boost: proven active event + corroboration nudges
        # cell propagation probability (never dominates rainfall).
        evidence_boost = 0.0
        flood_evidence = evidence["incident_disaster_type"] in (None, "flood")
        if evidence["active_incident"] and evidence["corroborating_reports"] > 0 and flood_evidence:
            evidence_boost = round(
                EVIDENCE_BOOST_MAX
                * min(1.0, evidence["corroborating_reports"] / 10.0),
                3,
            )

        result = await calculate_flood_spread(
            zone_id, rainfall_mm_hr=rain, hours=hours_ahead, db=db,
            evidence_boost=evidence_boost,
        )
        inputs = {
            "rainfall_mm_hr": rain,
            "rainfall_source": rain_source,
            "evidence": evidence,
            "evidence_boost": evidence_boost,
            "gis_context": gis_ctx,
            "model": result.get("model"),
        }
    elif disaster_type.lower() == "fire":
        if wind_speed_kmh is not None:
            wind, wind_source = float(wind_speed_kmh), "request_parameter"
        elif weather is not None:
            wind = float(weather.wind_speed_kmh or 0.0)
            wind_source = (
                f"weather_reading:open-meteo @ {weather.polled_at.isoformat()}"
                if weather.polled_at
                else "weather_reading:open-meteo"
            )
        else:
            wind, wind_source = DEFAULT_WIND_SPEED_KMH, DEFAULT_LABEL

        result = await calculate_fire_spread(
            zone_id, wind_speed_kmh=wind, hours=hours_ahead, db=db
        )
        inputs = {
            "wind_speed_kmh": wind,
            "wind_source": wind_source,
            "evidence": evidence,
            "gis_context": gis_ctx,
        }
    elif disaster_type.lower() == "earthquake":
        result = await calculate_seismic_shaking(zone_id, hours=hours_ahead, db=db)
        inputs = {
            "source": "seismic_events:usgs",
            "catalogue_window_hours": 72,
            "catalogue_radius_km": SEISMIC_DISTANCE_REFERENCE_KM,
            "event": result.get("event"),
            "available": result.get("available"),
            "reason": result.get("reason"),
            "background_rate": result.get("background_rate"),
            "gis_context": gis_ctx,
        }
    elif disaster_type.lower() == "landslide":
        result = await calculate_landslide_risk(zone_id, hours=hours_ahead, db=db)
        inputs = {
            "rainfall_window": result.get("rainfall_window"),
            "available": result.get("available"),
            "reason": result.get("reason"),
            "gis_context": gis_ctx,
        }
    elif disaster_type.lower() == "storm":
        result = await calculate_storm_impact(
            zone_id, wind_speed_kmh=wind_speed_kmh, hours=hours_ahead, db=db
        )
        inputs = {
            "wind_speed_kmh": result.get("wind_speed_kmh"),
            "wind_source": result.get("wind_source"),
            "gis_context": gis_ctx,
        }
    else:
        raise ValueError(
            f"Unknown disaster type: {disaster_type}. "
            f"Expected one of: {', '.join(sorted(HAZARD_CATALOGUE))}."
        )

    kind = disaster_type.lower()
    result["projection_label"] = "MODEL PROJECTION"
    result["disaster_type"] = kind
    result["display_name"] = HAZARD_CATALOGUE[kind]["display_name"]
    result["modelled"] = HAZARD_CATALOGUE[kind]["modelled"]
    result["limitations"] = HAZARD_LIMITATIONS[kind]
    result.setdefault("available", True)
    result.setdefault("reason", None)
    result["inputs"] = inputs
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result


async def predict_all_hazards(zone_id: str, hours_ahead: int = 12,
                              db: AsyncSession = None) -> dict:
    """Every modelled hazard for a zone in one uniform envelope.

    Returns a list rather than a fixed-key object so the console can render new
    hazards without a frontend change. Each entry keeps its own `available`
    flag: a hazard with no qualifying observation is reported as unavailable
    with a reason, never as a zero-valued model run.
    """
    from app.models.zone import Zone

    if db is None:
        from app.core.database import AsyncSessionLocal as _AsyncSessionLocal
        async with _AsyncSessionLocal() as _db:
            return await predict_all_hazards(zone_id, hours_ahead, _db)

    zone_row = (await db.execute(select(Zone).where(Zone.id == zone_id))).scalar_one_or_none()
    if zone_row is None:
        raise ValueError(f"Zone {zone_id} not found")

    hazards: list[dict] = []
    for kind in HAZARD_CATALOGUE:
        try:
            run_result = await predict_spread(
                zone_id=zone_id, disaster_type=kind, hours_ahead=hours_ahead, db=db
            )
            error = None
        except ValueError as exc:
            logger.warning("hazard_run_failed", zone_id=zone_id, hazard=kind, error=str(exc))
            run_result, error = None, str(exc)

        if run_result is None:
            hazards.append({
                "disaster_type": kind,
                "display_name": HAZARD_CATALOGUE[kind]["display_name"],
                "modelled": HAZARD_CATALOGUE[kind]["modelled"],
                "available": False,
                "reason": error,
                "cells": [],
                "max_intensity": 0.0,
                "coverage_percentage": None,
                "metrics": {},
                "inputs": {},
                "limitations": HAZARD_LIMITATIONS[kind],
                "expires_at": None,
            })
            continue

        # Flood reports its cells as `affected_cells`, fire as `burned_area`.
        # Reading the wrong key silently produced an empty fire map.
        cells = run_result.get("affected_cells")
        if cells is None:
            cells = run_result.get("burned_area") or []

        # Coverage is only defined where the hazard actually models area. Fire
        # has no coverage metric, and reporting 0.0 next to a high intensity
        # would read as "0% of the zone affected" when nothing was measured.
        coverage = run_result.get("coverage_percentage")
        if coverage is None:
            coverage = run_result.get("flooded_percentage")
        coverage = None if coverage is None else float(coverage)

        available = bool(run_result.get("available", True))
        if not available:
            # No projection was actually produced, so the placeholder cell the
            # uniform helper emits must not be presented as one.
            cells = []
            coverage = None

        hazard_row = {
            "disaster_type": kind,
            "display_name": run_result.get("display_name", kind),
            "modelled": run_result.get("modelled", HAZARD_CATALOGUE[kind]["modelled"]),
            "available": available,
            "reason": run_result.get("reason"),
            "cells": cells,
            "max_intensity": float(run_result.get("max_intensity") or 0.0),
            "coverage_percentage": coverage,
            "metrics": _hazard_metrics(kind, run_result),
            "inputs": run_result.get("inputs", {}),
            "limitations": run_result.get("limitations", []),
            "expires_at": (
                run_result["expires_at"].isoformat()
                if hasattr(run_result.get("expires_at"), "isoformat")
                else run_result.get("expires_at")
            ),
        }
        # Earthquake only: the long-run USGS rate, hoisted out of `inputs` so the
        # console has a stable top-level contract for it. It is deliberately a
        # sibling of the projection, not part of it -- the matrix builder
        # projects an explicit field set, so anything left only in `inputs` is
        # invisible to a client reading the documented shape.
        if kind == "earthquake":
            prior = run_result.get("background_rate") or (
                run_result.get("inputs") or {}
            ).get("background_rate")
            if prior is not None:
                hazard_row["background_rate"] = prior
        hazards.append(hazard_row)

    return {
        "zone_id": zone_id,
        "zone_name": zone_row.name,
        "hours_ahead": hours_ahead,
        "projection_label": "MODEL PROJECTION",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hazard_count": len(hazards),
        "hazards": hazards,
    }


def _hazard_metrics(kind: str, result: dict) -> dict:
    """Hazard-specific headline numbers, flattened for display."""
    if kind == "flood":
        return {"flooded_percentage": result.get("flooded_percentage", 0.0)}
    if kind == "fire":
        return {"spread_direction_degrees": result.get("spread_direction_degrees", 0.0)}
    if kind == "earthquake":
        event = result.get("event") or {}
        return {
            "magnitude": event.get("magnitude"),
            "depth_km": event.get("depth_km"),
            "distance_km": event.get("distance_km"),
            "shaking_probability": result.get("shaking_probability"),
        }
    if kind == "landslide":
        window = result.get("rainfall_window") or {}
        return {
            "susceptibility": result.get("susceptibility"),
            "peak_rain_mm_hr": window.get("peak_mm_hr"),
            "mean_rain_mm_hr": window.get("mean_mm_hr"),
        }
    if kind == "storm":
        return {
            "wind_speed_kmh": result.get("wind_speed_kmh"),
            "impact_probability": result.get("impact_probability"),
        }
    return {}