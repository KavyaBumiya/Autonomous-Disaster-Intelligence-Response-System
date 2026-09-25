"""
Common normalized observation models (PRD §5).

Every external provider maps into these structures so downstream code
(fusion, trust, prediction, XAI) never touches raw provider payloads.

Each model carries §5 provenance:
    source        provider name (e.g. "open-meteo", "usgs", "osm/overpass")
    observation_type
    location / timestamp
    confidence
"""
from datetime import datetime

from pydantic import BaseModel, Field


class WeatherObservation(BaseModel):
    """Normalized weather observation (Open-Meteo → §5 shape)."""

    source: str = "open-meteo"
    observation_type: str = "weather"
    latitude: float
    longitude: float
    timestamp: datetime

    rainfall_mm_hr: float = 0.0
    temperature_c: float | None = None
    wind_speed_kmh: float | None = None
    humidity_pct: float | None = None
    precipitation_probability_pct: float | None = None
    weather_code: int | None = None
    weather_main: str = ""
    weather_description: str = ""

    unit: str = "mm/hr"
    confidence: float = 1.0
    # True when served from cache (fresh=False) — callers must label it.
    from_cache: bool = False


class ForecastSlice(BaseModel):
    """One hourly forecast point."""

    time: str
    precipitation_mm: float = 0.0
    precipitation_probability_pct: float | None = None
    temperature_c: float | None = None


class ForecastResult(BaseModel):
    source: str = "open-meteo"
    observation_type: str = "forecast"
    latitude: float
    longitude: float
    retrieved_at: datetime
    hours: list[ForecastSlice] = Field(default_factory=list)
    from_cache: bool = False


class InfrastructureObservation(BaseModel):
    """Normalized OSM/Overpass feature (§8): roads, bridges, hospitals,
    shelters, schools, waterways, buildings."""

    source: str = "osm/overpass"
    observation_type: str = "infrastructure"
    osm_type: str                 # node | way | relation
    osm_id: int
    category: str                 # road | bridge | hospital | clinic | school | shelter | waterway | building
    lat: float
    lng: float
    name: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    retrieved_at: datetime
    confidence: float = 1.0


class EarthquakeObservation(BaseModel):
    """Normalized seismic event (USGS → §5 shape, §14)."""

    source: str = "usgs"
    observation_type: str = "seismic"
    usgs_id: str
    magnitude: float = 0.0
    depth_km: float | None = None
    lat: float
    lng: float
    place: str | None = None
    event_time: datetime
    risk_score: float = 0.0
    retrieved_at: datetime
    confidence: float = 1.0

    @classmethod
    def from_feature(
        cls, feature: dict, *, retrieved_at: datetime
    ) -> "EarthquakeObservation | None":
        """USGS GeoJSON feature → observation; None when malformed (§7 —
        never invent coordinates or magnitude)."""
        try:
            props = feature.get("properties") or {}
            coords = (feature.get("geometry") or {}).get("coordinates") or []
            usgs_id = feature.get("id")
            if not usgs_id or len(coords) < 2:
                return None
            mag = float(props.get("mag") or 0.0)
            time_ms = props.get("time")
            event_time = (
                datetime.fromtimestamp(time_ms / 1000, tz=retrieved_at.tzinfo)
                if time_ms
                else retrieved_at
            )
            return cls(
                usgs_id=str(usgs_id),
                magnitude=mag,
                depth_km=float(coords[2]) if len(coords) > 2 else None,
                lat=float(coords[1]),
                lng=float(coords[0]),
                place=props.get("place"),
                event_time=event_time,
                risk_score=magnitude_to_risk(mag),
                retrieved_at=retrieved_at,
            )
        except (TypeError, ValueError, IndexError):
            return None


def magnitude_to_risk(magnitude: float) -> float:
    """Richter magnitude → 0.0–1.0 risk (shared with pollers/seismic.py)."""
    if magnitude >= 7.0:
        return 1.0
    if magnitude >= 6.0:
        return 0.8
    if magnitude >= 5.0:
        return 0.6
    if magnitude >= 4.5:
        return 0.4
    if magnitude >= 4.0:
        return 0.25
    if magnitude >= 3.0:
        return 0.1
    return 0.0


class GeocodedLocation(BaseModel):
    """Normalized geocoding result (Nominatim → §5 shape)."""

    source: str = "nominatim"
    observation_type: str = "geocoded_location"
    query: str
    lat: float
    lng: float
    display_name: str | None = None
    confidence: float = 0.5
    osm_type: str | None = None
    osm_id: int | None = None
    retrieved_at: datetime


class RouteResult(BaseModel):
    """Normalized routing result (OSRM → §5 shape)."""

    source: str                     # osrm | fallback_haversine
    observation_type: str = "route"
    origin_lat: float
    origin_lng: float
    dest_lat: float
    dest_lng: float
    distance_km: float
    duration_minutes: float
    cost: float | None = None
    penalties: dict[str, float] = Field(default_factory=dict)
    geometry: list[list[float]] = Field(default_factory=list)
    computed_at: datetime
    # OSRM road network = direct measurement; fallback = estimate.
    confidence: float = 1.0


class ExternalEvidence(BaseModel):
    """§5 evidence envelope — one record of external corroboration.

    Attached to incidents (via evidence table) or fused into bundles;
    payload-free fields here, provider detail lives in `value`."""

    source: str
    observation_type: str
    location: dict[str, float] | None = None   # {"lat": .., "lng": ..}
    timestamp: datetime
    value: float | str | dict | list | None = None
    unit: str | None = None
    confidence: float = 1.0
    retrieved_at: datetime | None = None
