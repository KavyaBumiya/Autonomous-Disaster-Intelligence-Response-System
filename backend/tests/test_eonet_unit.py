"""Phase 19 — NASA EONET unit tests (§40–41).

Connector normalization is respx-mocked (no network); poller/API tests use
the local DB with distinctive EONET_TEST_* ids and clean up after themselves.
Live coverage lives in test_external_smoke.py::test_eonet_live.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.integrations import registry
from app.integrations.base import ConnectorError
from app.integrations.nasa.eonet import EonetConnector, normalize_event


def run(coro):
    """Fresh event loop + asyncpg pool disposal (loop-bound connections)."""
    from app.core.database import engine

    async def _wrap():
        await engine.dispose()
        try:
            return await coro
        finally:
            await engine.dispose()

    import asyncio

    return asyncio.run(_wrap())


@pytest.fixture(autouse=True)
def _isolate_registry():
    saved = copy.deepcopy(registry._providers)
    registry.reset()
    yield
    registry.reset()
    registry._providers.update(saved)


# ── normalize_event (§5 contract) ──────────────────────────────────────────

_WILDFIRE = {
    "id": "EONET_TEST_FIRE",
    "title": "Wildfire Test Creek",
    "description": "4 Miles S from Testville",
    "link": "https://eonet.gsfc.nasa.gov/api/v3/events/EONET_TEST_FIRE",
    "closed": None,
    "categories": [{"id": "wildfires", "title": "Wildfires"}],
    "sources": [{"id": "IRWIN", "url": "https://example.invalid/irwin"}],
    "geometry": [
        {
            "magnitudeValue": 828.0,
            "magnitudeUnit": "acres",
            "date": "2026-09-23T10:12:00Z",
            "type": "Point",
            "coordinates": [-88.83785, 31.052583],
        }
    ],
}


def test_normalize_point_event():
    n = normalize_event(_WILDFIRE)
    assert n is not None
    assert n["eonet_id"] == "EONET_TEST_FIRE"
    assert n["category"] == "wildfires"
    assert n["category_title"] == "Wildfires"
    assert n["lat"] == 31.052583 and n["lng"] == -88.83785
    assert n["magnitude_value"] == 828.0 and n["magnitude_unit"] == "acres"
    assert n["latest_geometry_date"] == "2026-09-23T10:12:00Z"
    assert n["closed"] is None
    assert n["sources"] == [{"id": "IRWIN", "url": "https://example.invalid/irwin"}]


def test_normalize_track_uses_latest_point():
    storm = {
        "id": "EONET_TEST_STORM",
        "title": "Test Storm",
        "categories": [{"id": "severeStorms", "title": "Severe Storms"}],
        "geometry": [
            {"date": "2026-09-24T00:00:00Z", "type": "Point",
             "coordinates": [-155.8, 14.6], "magnitudeValue": 40.0,
             "magnitudeUnit": "kts"},
            {"date": "2026-09-25T00:00:00Z", "type": "Point",
             "coordinates": [-156.0, 14.9], "magnitudeValue": 60.0,
             "magnitudeUnit": "kts"},
        ],
    }
    n = normalize_event(storm)
    assert n is not None
    # newest geometry wins — storms move, older points must be ignored
    assert n["lng"] == -156.0 and n["lat"] == 14.9
    assert n["magnitude_value"] == 60.0
    assert n["latest_geometry_date"] == "2026-09-25T00:00:00Z"


def test_normalize_polygon_only_keeps_null_coords():
    volcano = {
        "id": "EONET_TEST_POLY",
        "title": "Test Volcano",
        "categories": [{"id": "volcanoes", "title": "Volcanoes"}],
        "geometry": [
            {"date": "2026-09-20T00:00:00Z", "type": "Polygon",
             "coordinates": [[[73.0, 22.0], [73.1, 22.0], [73.1, 22.1], [73.0, 22.0]]]},
        ],
    }
    n = normalize_event(volcano)
    assert n is not None
    # area is never reduced to an invented centroid (§7)
    assert n["lat"] is None and n["lng"] is None
    assert n["geometry_type"] == "Polygon"


def test_normalize_malformed_skipped():
    assert normalize_event({"title": "no id"}) is None
    assert normalize_event({"id": "EONET_X"}) is None          # no title
    assert normalize_event("not-a-dict") is None
    assert normalize_event({"id": "x", "title": "t",
                            "geometry": [{"type": "Point",
                                          "coordinates": ["bad", "coords"]}]}) is not None
    # bad coords → null coords, event itself still valid
    n = normalize_event({"id": "x", "title": "t",
                         "geometry": [{"type": "Point", "coordinates": ["bad", "coords"]}]})
    assert n["lat"] is None and n["lng"] is None


# ── Connector (respx-mocked HTTP) ──────────────────────────────────────────

@respx.mock
async def test_connector_events_ok_records_registry():
    respx.get("https://eonet.gsfc.nasa.gov/api/v3/events").mock(
        return_value=httpx.Response(200, json={"title": "EONET Events",
                                               "events": [_WILDFIRE]})
    )
    data = await EonetConnector().events(status="open", limit=5)
    assert len(data["events"]) == 1
    assert registry.get_status("nasa/eonet") == "ONLINE"


@respx.mock
async def test_connector_missing_events_list_raises():
    connector = EonetConnector()
    connector.max_attempts = 1
    respx.get("https://eonet.gsfc.nasa.gov/api/v3/events").mock(
        return_value=httpx.Response(200, json={"title": "EONET Events"})
    )
    with pytest.raises(ConnectorError) as ei:
        await connector.events()
    assert "missing 'events'" in ei.value.message
    assert ei.value.retryable is True


@respx.mock
async def test_connector_empty_events_is_valid():
    respx.get("https://eonet.gsfc.nasa.gov/api/v3/events").mock(
        return_value=httpx.Response(200, json={"events": []})
    )
    assert (await EonetConnector().events())["events"] == []


# ── Poller (respx-mocked HTTP + local DB) ──────────────────────────────────

async def _cleanup_eonet_rows() -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.external import ExternalObservation

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ExternalObservation).where(
                ExternalObservation.source == "nasa_eonet",
                ExternalObservation.value["eonet_id"].astext.like("EONET_TEST%"),
            )
        )
        await db.commit()


@respx.mock
async def test_poller_insert_dedupe_and_move():
    from app.pollers.eonet import poll_eonet

    await _cleanup_eonet_rows()
    storm = {
        "id": "EONET_TEST_STORM",
        "title": "Test Storm",
        "categories": [{"id": "severeStorms", "title": "Severe Storms"}],
        "geometry": [
            {"date": "2026-09-24T00:00:00Z", "type": "Point",
             "coordinates": [73.0, 22.0], "magnitudeValue": 40.0,
             "magnitudeUnit": "kts"},
        ],
    }
    route = respx.get("https://eonet.gsfc.nasa.gov/api/v3/events")

    try:
        # run 1: wildfire + storm + malformed → 2 inserts (malformed skipped)
        route.mock(return_value=httpx.Response(
            200, json={"events": [_WILDFIRE, storm, {"title": "no id"}]}))
        assert await poll_eonet() == 2

        # run 2: unchanged → deduped, 0 writes
        route.mock(return_value=httpx.Response(
            200, json={"events": [_WILDFIRE, storm]}))
        assert await poll_eonet() == 0

        # run 3: storm moved (track) → exactly 1 refreshed row
        moved = dict(storm)
        moved["geometry"] = [
            {"date": "2026-09-25T06:00:00Z", "type": "Point",
             "coordinates": [73.4, 22.4], "magnitudeValue": 55.0,
             "magnitudeUnit": "kts"},
        ]
        route.mock(return_value=httpx.Response(
            200, json={"events": [_WILDFIRE, moved]}))
        assert await poll_eonet() == 1

        # stored row carries normalized position + category
        from sqlalchemy import select

        from app.core.database import AsyncSessionLocal
        from app.models.external import ExternalObservation

        async with AsyncSessionLocal() as db:
            row = (await db.execute(
                select(ExternalObservation).where(
                    ExternalObservation.source == "nasa_eonet",
                    ExternalObservation.value["eonet_id"].astext == "EONET_TEST_STORM",
                )
            )).scalar_one()
            assert row.lat == 22.4 and row.lng == 73.4
            assert row.value["magnitude_value"] == 55.0
            assert row.observation_type == "natural_event"
    finally:
        await _cleanup_eonet_rows()


# ── API endpoint (/api/nasa/eonet/events) ──────────────────────────────────

from app.main import app  # noqa: E402  (imported after helpers for clarity)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth_headers(client):
    r = client.post("/api/auth/login",
                    json={"username": "analyst@aegis.demo", "password": "demo123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _seed_api_rows() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.external import ExternalObservation

    await _cleanup_eonet_rows()
    async with AsyncSessionLocal() as db:
        # near, open, wildfires
        db.add(ExternalObservation(
            id="test-eonet-near", source="nasa_eonet",
            observation_type="natural_event",
            lat=22.31, lng=73.19,
            value={"eonet_id": "EONET_TEST_NEAR", "title": "Near fire",
                   "category": "wildfires", "magnitude_value": 10.0,
                   "magnitude_unit": "acres"},
            payload={"provider": "nasa_eonet", "title": "Near fire",
                     "closed": None, "category": "wildfires",
                     "category_title": "Wildfires", "sources": [],
                     "geometry_type": "Point", "link": "https://example.invalid/n",
                     "description": None, "latest_geometry_date": None},
            confidence=1.0, retrieved_at=datetime.now(timezone.utc),
        ))
        # far away, open, severeStorms
        db.add(ExternalObservation(
            id="test-eonet-far", source="nasa_eonet",
            observation_type="natural_event",
            lat=35.0, lng=-100.0,
            value={"eonet_id": "EONET_TEST_FAR", "title": "Far storm",
                   "category": "severeStorms", "magnitude_value": None,
                   "magnitude_unit": None},
            payload={"provider": "nasa_eonet", "title": "Far storm",
                     "closed": None, "category": "severeStorms",
                     "category_title": "Severe Storms", "sources": [],
                     "geometry_type": "Point", "link": None,
                     "description": None, "latest_geometry_date": None},
            confidence=1.0, retrieved_at=datetime.now(timezone.utc),
        ))
        # closed event (same area) — excluded by default status=open
        db.add(ExternalObservation(
            id="test-eonet-closed", source="nasa_eonet",
            observation_type="natural_event",
            lat=22.32, lng=73.20,
            value={"eonet_id": "EONET_TEST_CLOSED", "title": "Old fire",
                   "category": "wildfires", "magnitude_value": None,
                   "magnitude_unit": None},
            payload={"provider": "nasa_eonet", "title": "Old fire",
                     "closed": "2026-09-01T00:00:00Z", "category": "wildfires",
                     "category_title": "Wildfires", "sources": [],
                     "geometry_type": "Point", "link": None,
                     "description": None, "latest_geometry_date": None},
            confidence=1.0, retrieved_at=datetime.now(timezone.utc),
        ))
        await db.commit()


def test_eonet_endpoint_public(client: TestClient):
    r = client.get("/api/nasa/eonet/events")
    assert r.status_code == 200


def test_eonet_endpoint_contract_and_filters(client: TestClient, auth_headers):
    run(_seed_api_rows())
    try:
        # default: open only (closed excluded), near+far present
        r = client.get("/api/nasa/eonet/events", headers=auth_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["source"] == "nasa_eonet"
        assert body["provider"] == "NASA EONET v3"
        ids = {e["id"] for e in body["events"]}
        assert "EONET_TEST_NEAR" in ids and "EONET_TEST_FAR" in ids
        assert "EONET_TEST_CLOSED" not in ids
        for key in ("title", "category", "status", "lat", "lng",
                    "magnitude_value", "sources", "retrieved_at"):
            assert key in body["events"][0], key
        assert "never fabricated" in body["note"]

        # closed filter flips membership (real poller rows stay open-flagged)
        r = client.get("/api/nasa/eonet/events?status=closed", headers=auth_headers)
        closed_ids = {e["id"] for e in r.json()["events"]}
        assert "EONET_TEST_CLOSED" in closed_ids
        assert "EONET_TEST_NEAR" not in closed_ids

        # category filter (subset-style: the DB may hold real poller rows)
        r = client.get("/api/nasa/eonet/events?category=severeStorms",
                       headers=auth_headers)
        cat_ids = {e["id"] for e in r.json()["events"]}
        assert "EONET_TEST_FAR" in cat_ids
        assert "EONET_TEST_NEAR" not in cat_ids

        # radius around Alkapuri: near fires in, far storms out
        r = client.get(
            "/api/nasa/eonet/events",
            params={"lat": 22.31, "lng": 73.19, "radius_km": 50},
            headers=auth_headers,
        )
        area_ids = {e["id"] for e in r.json()["events"]}
        assert "EONET_TEST_NEAR" in area_ids
        assert "EONET_TEST_FAR" not in area_ids

        # unknown category → honest empty list, not an error
        r = client.get("/api/nasa/eonet/events?category=no_such_category",
                       headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["count"] == 0
        assert r.json()["events"] == []
    finally:
        run(_cleanup_eonet_rows())
