"""Phase 12 — Command Center tool tests (PRD §20/§21).

Tool schema integrity + ToolExecutor integration with mocked service results.
No live LLM calls: the executor layer is tested with mocked tool results,
which is where deterministic execution actually happens.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.integrations.base import ConnectorError
from app.services.ai_gateway import COMMAND_TOOLS, ToolExecutor


def run(coro):
    """Run a coroutine in a fresh event loop, clearing the asyncpg pool
    first (pooled connections are bound to the previous loop)."""
    from app.core.database import engine

    async def _wrap():
        await engine.dispose()
        try:
            return await coro
        finally:
            await engine.dispose()

    return asyncio.run(_wrap())


# ── Schema integrity ───────────────────────────────────────────────────────

def test_tool_count_and_uniqueness():
    names = [t["function"]["name"] for t in COMMAND_TOOLS]
    assert len(names) == 16, names          # 11 legacy + 5 Phase 12
    assert len(set(names)) == len(names)
    for t in COMMAND_TOOLS:
        assert t["type"] == "function"
        assert "properties" in t["function"]["parameters"]


def test_every_tool_has_executor_handler():
    for t in COMMAND_TOOLS:
        name = t["function"]["name"]
        assert hasattr(ToolExecutor, f"_tool_{name}"), name


def test_unknown_tool_error():
    async def main():
        async with AsyncSessionLocal() as db:
            out = await ToolExecutor(db).execute("not_a_tool", {})
            assert "error" in out and "not_a_tool" in out["error"]
    run(main())


# ── get_weather_forecast (mocked provider) ─────────────────────────────────

def test_weather_forecast_tool_mocked():
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)

            class FakeForecast:
                def model_dump(self, mode=None):
                    return {"hourly": {"temperature_c": [29.1]}, "hours": 24}

            with patch(
                "app.services.weather_service.weather_service.get_forecast",
                new=AsyncMock(return_value=FakeForecast()),
            ):
                out = await ex.execute("get_weather_forecast", {"zone_id": "z1"})
            # zone z1 doesn't exist → resolver reports honestly
            assert "error" in out

            # explicit coordinates path
            with patch(
                "app.services.weather_service.weather_service.get_forecast",
                new=AsyncMock(return_value=FakeForecast()),
            ):
                out = await ex.execute(
                    "get_weather_forecast", {"lat": 22.31, "lng": 73.19, "hours": 12}
                )
            assert out["hourly"]["temperature_c"] == [29.1]
            assert "not LLM-generated" in out["note"]
            assert out["provider"] == "open-meteo"
    run(main())


def test_weather_forecast_provider_down_degrades():
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)
            with patch(
                "app.services.weather_service.weather_service.get_forecast",
                new=AsyncMock(side_effect=ConnectorError("open-meteo", "timeout")),
            ):
                out = await ex.execute("get_weather_forecast", {"lat": 22.0, "lng": 73.0})
            assert out["degraded"] is True
            assert "unavailable" in out["error"]
    run(main())


# ── get_earthquakes (mocked live / degraded fallback) ──────────────────────

_FAKE_USGS_FEATURE = {
    "type": "Feature",
    "id": "mock123",
    "properties": {"mag": 5.1, "place": "Test Region", "time": 1785000000000},
    "geometry": {"coordinates": [70.9, 26.9, 10.0]},
}


def test_earthquakes_live_mocked():
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)
            with patch(
                "app.integrations.seismic.usgs.UsgsConnector.recent_events",
                new=AsyncMock(return_value={"type": "FeatureCollection",
                                            "features": [_FAKE_USGS_FEATURE]}),
            ):
                out = await ex.execute("get_earthquakes", {"limit": 3})
            assert out["source"] == "usgs/live"
            assert out["total"] == 1
            ev = out["events"][0]
            assert ev["magnitude"] == 5.1
            assert ev["usgs_id"] == "mock123"
            assert ev["lat"] == 26.9 and ev["lng"] == 70.9
            assert ev["risk_score"] > 0
    run(main())


def test_earthquakes_degraded_fallback():
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)
            with patch(
                "app.integrations.seismic.usgs.UsgsConnector.recent_events",
                new=AsyncMock(side_effect=ConnectorError("usgs", "timeout")),
            ):
                out = await ex.execute("get_earthquakes", {"minutes": 60})
            assert out["degraded"] is True
            assert out["source"] == "local_usgs_poll_fallback"
            assert isinstance(out["events"], list)
            assert "degraded" in out["note"]
    run(main())


# ── geocode_location (mocked) ──────────────────────────────────────────────

def test_geocode_location_mocked():
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)
            with patch(
                "app.services.geocoding.geocode",
                new=AsyncMock(return_value={"lat": 22.307, "lng": 73.181,
                                            "display_name": "Vadodara",
                                            "confidence": 0.55}),
            ):
                out = await ex.execute("geocode_location", {"query": "Vadodara"})
            assert out["result"]["lat"] == 22.307
            assert out["provider"] == "nominatim"

            with patch(
                "app.services.geocoding.geocode",
                new=AsyncMock(return_value=None),
            ):
                out = await ex.execute("geocode_location", {"query": "nowhere-xyz"})
            assert out["result"] is None
            assert "nothing invented" in out["note"]
    run(main())


# ── get_infrastructure (DB) ────────────────────────────────────────────────

def test_infrastructure_tool_db():
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)
            bid = 8800011
            from app.models.infrastructure import Infrastructure
            row = Infrastructure(
                id=str(uuid.uuid4()), osm_type="way", osm_id=bid,
                category="bridge", name="Test Span",
                lat=22.310, lng=73.190, tags={"bridge": "yes"},
                retrieved_at=datetime.now(timezone.utc),
            )
            db.add(row)
            await db.flush()
            # mirror refresh_infrastructure's geometry fixup (§9)
            from sqlalchemy import text as sql_text
            await db.execute(sql_text(
                "UPDATE infrastructure SET geometry = "
                "ST_SetSRID(ST_MakePoint(lng, lat), 4326) WHERE osm_id = 8800011"))
            await db.commit()
            try:
                out = await ex.execute(
                    "get_infrastructure",
                    {"lat": 22.310, "lng": 73.190, "category": "bridge"},
                )
                # table may hold real Overpass data (§27 refresh) — assert our
                # row is found, not that it is the only bridge in the area
                assert out["total"] >= 1
                names = [f.get("name") for f in out["features"]]
                assert "Test Span" in names

                out2 = await ex.execute(
                    "get_infrastructure", {"lat": 22.310, "lng": 73.190}
                )
                assert out2["counts"]["bridge"] >= 1

                # honest empty area
                out3 = await ex.execute(
                    "get_infrastructure", {"lat": 10.0, "lng": 10.0}
                )
                assert out3["total"] == 0
                assert "never invented" in out3["note"]
            finally:
                await db.execute(delete(Infrastructure).where(
                    Infrastructure.osm_id == bid))
                await db.commit()
    run(main())


# ── get_satellite_evidence (honest §32) ────────────────────────────────────

def test_satellite_evidence_not_configured_then_cached():
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)
            out = await ex.execute("get_satellite_evidence",
                                   {"lat": 22.3, "lng": 73.2})
            assert out["available"] is False
            assert out["provider"] == "not_configured"
            assert "never fabricated" in out["note"]

            from app.models.external import ExternalObservation
            obs = ExternalObservation(
                id=str(uuid.uuid4()), source="sentinel_test",
                observation_type="satellite", lat=22.31, lng=73.20,
                value={"ndvi": 0.3}, confidence=0.9,
                retrieved_at=datetime.now(timezone.utc),
            )
            db.add(obs)
            await db.commit()
            try:
                out2 = await ex.execute("get_satellite_evidence",
                                        {"lat": 22.3, "lng": 73.2})
                assert out2["available"] is True
                assert out2["observations"][0]["source"] == "sentinel_test"
            finally:
                await db.execute(delete(ExternalObservation).where(
                    ExternalObservation.id == obs.id))
                await db.commit()
    run(main())


# ── §21 Command Center examples with mocked tool results ───────────────────

def test_command_center_examples():
    """Representative commander queries → intended tool calls (§21),
    executed through the ToolExecutor with mocked service results."""
    async def main():
        async with AsyncSessionLocal() as db:
            ex = ToolExecutor(db)

            # "What's the weather forecast for zone X?"
            class FakeForecast:
                def model_dump(self, mode=None):
                    return {"hours": 24, "hourly": {"rain": [12.0]}}
            with patch("app.services.weather_service.weather_service.get_forecast",
                       new=AsyncMock(return_value=FakeForecast())):
                r = await ex.execute("get_weather_forecast",
                                     {"lat": 22.3, "lng": 73.1, "hours": 24})
            assert r["hours"] == 24 and "provider" in r

            # "Any earthquakes recently?"
            with patch("app.integrations.seismic.usgs.UsgsConnector.recent_events",
                       new=AsyncMock(return_value={"type": "FeatureCollection",
                                                   "features": [_FAKE_USGS_FEATURE]})):
                r = await ex.execute("get_earthquakes", {"limit": 5, "minutes": 120})
            assert r["total"] == 1 and r["source"] == "usgs/live"

            # "Where is Vadodara exactly?"
            with patch("app.services.geocoding.geocode",
                       new=AsyncMock(return_value={"lat": 22.307, "lng": 73.181,
                                                   "display_name": "Vadodara",
                                                   "confidence": 0.55})):
                r = await ex.execute("geocode_location", {"query": "Vadodara"})
            assert r["result"]["confidence"] == 0.55

            # "How many bridges are cached near this point?"
            r = await ex.execute("get_infrastructure",
                                 {"lat": 22.31, "lng": 73.19, "category": "bridge"})
            assert "total" in r and r["source"] == "cached_osm_gis"

            # "Give me satellite imagery of the flood zone."
            r = await ex.execute("get_satellite_evidence", {"lat": 22.3, "lng": 73.2})
            assert r["available"] is False and r["provider"] == "not_configured"
    run(main())
