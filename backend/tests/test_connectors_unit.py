"""Phase 17 — Connector normalization unit tests (§40–41).

Every external provider response is mocked with respx (httpx transport) —
no live network. Verifies the §5 normalization contracts:
    Open-Meteo  → WeatherObservation / ForecastResult
    MET Norway  → WeatherObservation / ForecastResult (weather fallback)
    USGS        → GeoJSON passthrough + bare-Feature normalization
    OSRM        → {distance_m, duration_s, geometry} | None
    Nominatim   → ranked candidates with honest confidence
    Photon      → ranked candidates (geocoding fallback)
    Overpass    → InfrastructureObservation categories

Plus BaseConnector registry recording (§34) on success and failure.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from app.integrations import registry
from app.integrations.base import ConnectorError
from app.integrations.gis.nominatim import NominatimConnector
from app.integrations.gis.osrm import OsrmConnector
from app.integrations.gis.overpass import (
    OverpassConnector,
    build_infrastructure_query,
    normalize_elements,
)
from app.integrations.gis.photon import PhotonConnector
from app.integrations.seismic.usgs import UsgsConnector
from app.integrations.weather.met_norway import MetNorwayConnector, symbol_to_main_desc
from app.integrations.weather.open_meteo import OpenMeteoConnector
from app.schemas.observations import EarthquakeObservation


@pytest.fixture(autouse=True)
def _isolate_registry():
    saved = copy.deepcopy(registry._providers)
    registry.reset()
    yield
    registry.reset()
    registry._providers.update(saved)


@pytest.fixture(autouse=True)
def _no_throttle():
    """Nominatim/Overpass enforce a 1 s process throttle — irrelevant here."""
    with patch(
        "app.integrations.gis.nominatim._throttle", new=AsyncMock()
    ), patch("app.integrations.gis.overpass._throttle", new=AsyncMock()):
        yield


# ── Open-Meteo ──────────────────────────────────────────────────────────────

_OPEN_METEO_CURRENT = {
    "latitude": 22.3,
    "longitude": 73.2,
    "current": {
        "time": "2026-09-25T12:00",
        "temperature_2m": 29.4,
        "precipitation": 3.2,
        "weather_code": 63,
        "wind_speed_10m": 41.0,
        "relative_humidity_2m": 88,
    },
}


@respx.mock
async def test_open_meteo_current_normalization():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, json=_OPEN_METEO_CURRENT)
    )
    obs = await OpenMeteoConnector().get_current_weather(22.3, 73.2)

    assert obs.source == "open-meteo"
    assert obs.latitude == 22.3 and obs.longitude == 73.2
    assert obs.rainfall_mm_hr == 3.2
    assert obs.temperature_c == 29.4
    assert obs.wind_speed_kmh == 41.0
    assert obs.humidity_pct == 88
    assert obs.weather_code == 63
    assert obs.weather_main == "Rain"
    assert obs.timestamp == datetime(2026, 9, 25, 12, 0)
    assert registry.get_status("open-meteo") == "ONLINE"   # §34


@respx.mock
async def test_open_meteo_missing_current_block_raises():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, json={"latitude": 22.3})
    )
    with pytest.raises(ConnectorError) as ei:
        await OpenMeteoConnector().get_current_weather(22.3, 73.2)
    assert "missing 'current'" in ei.value.message
    assert ei.value.retryable is False


@respx.mock
async def test_open_meteo_forecast_normalization():
    respx.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(
            200,
            json={
                "latitude": 22.3,
                "longitude": 73.2,
                "hourly": {
                    "time": ["2026-09-25T00:00", "2026-09-25T01:00"],
                    "precipitation": [0.0, 1.5],
                    "precipitation_probability": [10, 80],
                    "temperature_2m": [28.0, 27.5],
                },
            },
        )
    )
    fc = await OpenMeteoConnector().get_forecast(22.3, 73.2, hours=2)
    assert fc.source == "open-meteo"
    assert fc.observation_type == "forecast"
    assert len(fc.hours) >= 1
    assert all(h.precipitation_mm >= 0 for h in fc.hours)


@respx.mock
async def test_open_meteo_html_200_body_is_retryable_error():
    """Rate-limit pages answer 200 + HTML — must not be trusted as data."""
    connector = OpenMeteoConnector()
    connector.max_attempts = 1
    respx.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(200, text="<html>rate limited</html>")
    )
    with pytest.raises(ConnectorError) as ei:
        await connector.get_current_weather(22.3, 73.2)
    assert "invalid JSON" in ei.value.message
    assert ei.value.retryable is True


# ── USGS ────────────────────────────────────────────────────────────────────

@respx.mock
async def test_usgs_recent_events_passthrough():
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "us7000test",
                "properties": {"mag": 5.1, "place": "10 km of Testville", "time": 1758000000000},
                "geometry": {"coordinates": [73.2, 22.3, 10.0]},
            }
        ],
    }
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, json=payload)
    )
    data = await UsgsConnector().recent_events(minutes=30, min_magnitude=3.0, limit=5)
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 1
    assert registry.get_status("usgs") == "ONLINE"


@respx.mock
async def test_usgs_get_event_normalizes_bare_feature():
    feature = {
        "type": "Feature",
        "id": "us7000bare",
        "properties": {"mag": 4.2, "place": "Bare", "time": 1758000000000},
        "geometry": {"coordinates": [73.0, 22.0, 5.0]},
    }
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(200, json=feature)
    )
    out = await UsgsConnector().get_event("us7000bare")
    assert out["type"] == "FeatureCollection"
    assert out["features"][0]["id"] == "us7000bare"


@respx.mock
async def test_usgs_get_event_unknown_id_returns_none():
    respx.get("https://earthquake.usgs.gov/fdsnws/event/1/query").mock(
        return_value=httpx.Response(404, json={"code": 404, "status": "not found"})
    )
    assert await UsgsConnector().get_event("us0000nope") is None


def test_earthquake_observation_from_feature_contract():
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    obs = EarthquakeObservation.from_feature(
        {
            "id": "abc123",
            "properties": {"mag": 6.2, "place": "X", "time": 1758000000000},
            "geometry": {"coordinates": [73.0, 22.0, 8.0]},
        },
        retrieved_at=now,
    )
    assert obs is not None
    assert obs.magnitude == 6.2
    assert obs.depth_km == 8.0
    assert obs.risk_score == 0.8            # 6.0 ≤ mag < 7.0
    # Malformed feature → None (never invent coordinates, §7)
    assert EarthquakeObservation.from_feature({"geometry": {}}, retrieved_at=now) is None
    assert (
        EarthquakeObservation.from_feature(
            {"id": "x", "geometry": {"coordinates": []}}, retrieved_at=now
        )
        is None
    )


# ── OSRM ────────────────────────────────────────────────────────────────────

@respx.mock
async def test_osrm_route_normalization():
    respx.get(url__regex=r"https://router\.project-osrm\.org/route/v1/driving/.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "Ok",
                "routes": [
                    {
                        "distance": 5432.1,
                        "duration": 600.0,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[73.2, 22.3], [73.25, 22.35]],
                        },
                    }
                ],
            },
        )
    )
    out = await OsrmConnector().route(22.3, 73.2, 22.35, 73.25)
    assert out == {
        "distance_m": 5432.1,
        "duration_s": 600.0,
        "geometry": [[73.2, 22.3], [73.25, 22.35]],
        "route_count": 1,
    }
    assert registry.get_status("osrm") == "ONLINE"


@respx.mock
async def test_osrm_no_route_returns_none():
    respx.get(url__regex=r"https://router\.project-osrm\.org/route/v1/driving/.*").mock(
        return_value=httpx.Response(200, json={"code": "NoRoute", "routes": []})
    )
    assert await OsrmConnector().route(0.0, 0.0, 1.0, 1.0) is None


# ── Nominatim ───────────────────────────────────────────────────────────────

@respx.mock
async def test_nominatim_search_normalization():
    respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "lat": "23.0225",
                    "lon": "72.5714",
                    "display_name": "Ahmedabad, India",
                    "importance": 0.85,
                    "osm_type": "relation",
                    "osm_id": 12345,
                },
                {"lat": "not-a-number", "lon": "x"},   # skipped — malformed
                {"display_name": "no coords"},          # skipped — no lat/lon
                {
                    "lat": "23.0",
                    "lon": "72.0",
                    "display_name": "Low rank",
                    "importance": None,                # missing → neutral 0.5
                },
            ],
        )
    )
    out = await NominatimConnector().search("Ahmedabad", limit=5)
    assert len(out) == 2
    assert out[0]["lat"] == 23.0225 and out[0]["lng"] == 72.5714
    assert out[0]["confidence"] == 0.85
    assert out[0]["osm_type"] == "relation"
    assert out[1]["confidence"] == 0.5
    assert registry.get_status("nominatim") == "ONLINE"


@respx.mock
async def test_nominatim_error_object_returns_empty_list():
    respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(200, json={"error": "Unable to geocode"})
    )
    assert await NominatimConnector().search("???", limit=3) == []


# ── MET Norway (weather fallback) ────────────────────────────────────────────

_MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact"

_MET_COMPACT = {
    "properties": {
        "meta": {"updated_at": "2026-09-25T13:17:50Z"},
        "timeseries": [
            {
                "time": "2026-09-25T15:00:00Z",
                "data": {
                    "instant": {"details": {
                        "air_temperature": 29.1,
                        "wind_speed": 5.0,          # m/s → 18.0 km/h
                        "relative_humidity": 76.7,
                    }},
                    "next_1_hours": {
                        "summary": {"symbol_code": "heavyrain_day"},
                        "details": {"precipitation_amount": 2.5},
                    },
                },
            },
            {
                "time": "2026-09-25T16:00:00Z",
                "data": {
                    "instant": {"details": {
                        "air_temperature": 28.4, "wind_speed": 4.0,
                        "relative_humidity": 80.0,
                    }},
                    # No next_1_hours — only the 6-hour bucket available
                    "next_6_hours": {
                        "summary": {"symbol_code": "partlycloudy_day"},
                        "details": {"precipitation_amount": 6.0},
                    },
                },
            },
        ],
    }
}


@respx.mock
async def test_met_norway_current_normalization():
    respx.get(_MET_URL).mock(return_value=httpx.Response(200, json=_MET_COMPACT))
    obs = await MetNorwayConnector().get_current_weather(22.30, 73.19)
    assert obs.source == "met-norway"
    assert obs.temperature_c == 29.1
    assert obs.wind_speed_kmh == 18.0          # 5.0 m/s × 3.6
    assert obs.humidity_pct == 76.7
    assert obs.rainfall_mm_hr == 2.5           # next_1_hours bucket
    assert obs.weather_main == "Rain"
    assert obs.weather_description == "Heavy rain"
    assert obs.timestamp == datetime(2026, 9, 25, 15, 0, tzinfo=timezone.utc)
    assert registry.get_status("met-norway") == "ONLINE"


@respx.mock
async def test_met_norway_forecast_normalization():
    respx.get(_MET_URL).mock(return_value=httpx.Response(200, json=_MET_COMPACT))
    fc = await MetNorwayConnector().get_forecast(22.30, 73.19, hours=6)
    assert fc.source == "met-norway"
    assert len(fc.hours) == 2                  # only 2 entries available
    assert fc.hours[0].precipitation_mm == 2.5  # next_1_hours
    assert fc.hours[1].precipitation_mm == 1.0  # next_6_hours 6.0 / 6
    assert fc.hours[0].temperature_c == 29.1
    assert fc.hours[0].precipitation_probability_pct is None  # honest: no prob


@respx.mock
async def test_met_norway_missing_timeseries_raises():
    respx.get(_MET_URL).mock(return_value=httpx.Response(200, json={"properties": {}}))
    with pytest.raises(ConnectorError) as ei:
        await MetNorwayConnector().get_current_weather(22.0, 73.0)
    assert ei.value.retryable is False


def test_met_norway_symbol_mapping():
    assert symbol_to_main_desc("clearsky_day") == ("Clear", "Clear sky")
    assert symbol_to_main_desc("heavyrainshowers_night") == (
        "Rain Showers", "Heavy rain showers",
    )
    assert symbol_to_main_desc("thunderstorm") == ("Thunderstorm", "Thunderstorm")
    assert symbol_to_main_desc("partlycloudy_polartwilight") == (
        "Clouds", "Partly cloudy",
    )
    assert symbol_to_main_desc("lightsnow") == ("Snow", "Light snow")
    assert symbol_to_main_desc(None) == ("Unknown", "Unknown condition")


# ── Photon (geocoding fallback) ──────────────────────────────────────────────

@respx.mock
async def test_photon_search_normalization():
    respx.get("https://photon.komoot.io/api/").mock(
        return_value=httpx.Response(
            200,
            json={
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "name": "Vadodara", "state": "Gujarat",
                            "country": "India", "countrycode": "IN",
                            "osm_type": "N", "osm_id": 2022807192,
                            "osm_key": "place", "osm_value": "city",
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [73.1942567, 22.2973142],
                        },
                    },
                    {"type": "Feature", "geometry": None},   # skipped — no coords
                ],
            },
        )
    )
    out = await PhotonConnector().search("Vadodara", limit=5)
    assert len(out) == 1
    first = out[0]
    assert first["lat"] == 22.2973142 and first["lng"] == 73.1942567
    assert first["display_name"] == "Vadodara, Gujarat, India"
    assert first["confidence"] == 0.5          # neutral — photon has no importance
    assert first["category"] == "place" and first["type"] == "city"
    assert first["osm_type"] == "N" and first["osm_id"] == 2022807192
    assert registry.get_status("photon") == "ONLINE"


# ── Overpass ────────────────────────────────────────────────────────────────

def test_overpass_query_covers_disaster_categories():
    q = build_infrastructure_query(22.0, 73.0, 22.5, 73.5)
    assert "[out:json]" in q
    assert '(22.0,73.0,22.5,73.5)' in q
    for token in ('"highway"', '"bridge"', '"amenity"', '"waterway"', '"building"'):
        assert token in q
    assert "out geom;" in q


def test_overpass_normalize_elements_categories():
    elements = [
        {"type": "way", "id": 1, "tags": {"highway": "primary"},
         "geometry": [{"lat": 22.0, "lon": 73.0}, {"lat": 22.1, "lon": 73.1}]},
        {"type": "way", "id": 2, "tags": {"bridge": "yes", "highway": "road"},
         "geometry": [{"lat": 22.2, "lon": 73.2}, {"lat": 22.3, "lon": 73.3}]},
        {"type": "node", "id": 3, "lat": 22.4, "lon": 73.4,
         "tags": {"amenity": "hospital", "name": "Civil Hospital"}},
        {"type": "node", "id": 4, "lat": 22.5, "lon": 73.5,
         "tags": {"amenity": "cafe"}},                    # out of scope
        {"type": "way", "id": 5, "tags": {"waterway": "river"},
         "geometry": [{"lat": 22.6, "lon": 73.6}, {"lat": 22.7, "lon": 73.7}]},
        {"type": "node", "id": 6, "tags": {"building": "residential"},
         "lat": 22.8, "lon": 73.8},
        {"type": "way", "id": 7, "tags": {"highway": "track"}},   # no coords → skipped
    ]
    obs = normalize_elements(elements)
    cats = [o.category for o in obs]
    assert cats == ["road", "bridge", "hospital", "waterway", "building"]
    assert obs[2].name == "Civil Hospital"
    assert all(o.osm_id > 0 for o in obs)


@respx.mock
async def test_overpass_fetch_infrastructure_normalized():
    respx.get("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(
            200,
            json={
                "elements": [
                    {
                        "type": "node",
                        "id": 42,
                        "lat": 22.4,
                        "lon": 73.4,
                        "tags": {"amenity": "shelter", "name": "Relief Camp"},
                    }
                ]
            },
        )
    )
    out = await OverpassConnector().fetch_infrastructure(22.0, 73.0, 22.5, 73.5)
    assert len(out) == 1
    assert out[0].category == "shelter"
    assert out[0].name == "Relief Camp"
    assert registry.get_status("osm/overpass") == "ONLINE"


@respx.mock
async def test_overpass_remark_response_is_retryable_error():
    connector = OverpassConnector()
    connector.max_attempts = 1
    connector.backoff_base_seconds = 0.01
    respx.get("https://overpass-api.de/api/interpreter").mock(
        return_value=httpx.Response(200, json={"remark": "runtime error"})
    )
    with pytest.raises(ConnectorError) as ei:
        await connector.fetch_infrastructure(22.0, 73.0, 22.5, 73.5)
    assert "no elements" in ei.value.message
    assert ei.value.retryable is True


# ── Registry recording via BaseConnector (§34) ──────────────────────────────

@respx.mock
async def test_registry_failure_recorded_on_http_5xx():
    connector = OsrmConnector()
    connector.max_attempts = 1
    connector.backoff_base_seconds = 0.01
    respx.get(url__regex=r"https://router\.project-osrm\.org/route/v1/driving/.*").mock(
        return_value=httpx.Response(503, text="maintenance")
    )
    with pytest.raises(ConnectorError):
        await connector.route(22.3, 73.2, 22.35, 73.25)
    snap = registry.snapshot()["osrm"]
    assert snap["status"] == "OFFLINE"
    assert snap["last_error"] == "HTTP 503"
    assert snap["total_failures"] == 1
