"""Phase 17 — Real-API smoke tests (§41, opt-in).

Every test here hits a live provider. They are SKIPPED by default; run with:

    pytest tests/test_external_smoke.py --run-external -q

These proved the connectors work against production endpoints during the
Phase 18 verification (§48 report). Mocked coverage lives in
test_connectors_unit.py.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.external


async def test_open_meteo_live():
    from app.integrations.weather.open_meteo import OpenMeteoConnector

    obs = await OpenMeteoConnector().get_current_weather(22.30, 73.20)
    assert obs.source == "open-meteo"
    assert obs.rainfall_mm_hr >= 0.0
    assert obs.timestamp is not None


async def test_osrm_live():
    from app.integrations.gis.osrm import OsrmConnector

    route = await OsrmConnector().route(22.30, 73.20, 22.40, 73.30)
    assert route is not None
    assert route["distance_m"] > 0
    assert len(route["geometry"]) >= 2


async def test_usgs_live():
    from app.integrations.seismic.usgs import UsgsConnector

    data = await UsgsConnector().recent_events(
        minutes=1440, min_magnitude=2.0, limit=5
    )
    assert data["type"] == "FeatureCollection"
    assert isinstance(data["features"], list)


async def test_nominatim_live():
    from app.integrations.gis.nominatim import NominatimConnector

    out = await NominatimConnector().search("Ahmedabad, India", limit=3)
    assert out, "expected at least one candidate"
    assert -90.0 <= out[0]["lat"] <= 90.0
    assert -180.0 <= out[0]["lng"] <= 180.0


async def test_overpass_live():
    from app.integrations.gis.overpass import OverpassConnector

    obs = await OverpassConnector().fetch_infrastructure(22.28, 73.18, 22.33, 73.24)
    assert obs, "expected infrastructure features in central Ahmedabad"
    assert all(o.category in (
        "road", "bridge", "hospital", "clinic", "shelter",
        "school", "waterway", "building",
    ) for o in obs)
