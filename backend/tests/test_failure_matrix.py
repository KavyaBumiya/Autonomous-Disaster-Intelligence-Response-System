"""Phase 16 — Failure matrix (plan §31–§32).

Every external dependency can fail; the system must:
  * keep provider state observable (registry state machine),
  * open the circuit after an OFFLINE streak (no network, no fabricated data),
  * serve cache when available and raise a DISTINCT "no cache" message when not,
  * degrade to honest fallbacks (haversine route, offline Groq, None geocode),
  * survive Redis/DB outages (cache swallows, auth → 503),
  * report canonical provider groups + service reasons in /api/health.

No live network calls: every provider boundary is mocked.
"""
from __future__ import annotations

import asyncio
import copy
import time
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from fastapi import HTTPException

from app.integrations import cache, registry
from app.integrations.base import ConnectorError
from app.integrations.weather.open_meteo import OpenMeteoConnector
from app.main import health
from app.pollers.seismic import poll_seismic
from app.services.geocoding import geocode
from app.services.groq_gateway import AILogRecord, GroqGateway, _log_call, groq_gateway
from app.services.route_intelligence import calculate_route
from app.services.weather_service import weather_service


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


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Blank registry per test; restore prior state afterwards so other
    suites (poller-written provider states) are unaffected."""
    saved = copy.deepcopy(registry._providers)
    registry.reset()
    yield
    registry.reset()
    registry._providers.update(saved)


# ── Registry state machine (§34) ────────────────────────────────────────────

def test_registry_status_state_machine():
    assert registry.get_status("never-probed") == "UNKNOWN"

    registry.record_success("p1", 10.0)
    assert registry.get_status("p1") == "ONLINE"

    registry.record_failure("p1", "error 1")
    assert registry.get_status("p1") == "DEGRADED"

    registry.record_failure("p1", "error 2")
    assert registry.get_status("p1") == "DEGRADED"

    registry.record_failure("p1", "error 3")
    assert registry.get_status("p1") == "OFFLINE"
    assert registry.circuit_open("p1")

    registry.record_success("p1", 5.0)
    assert registry.get_status("p1") == "ONLINE"
    assert not registry.circuit_open("p1")


def test_first_failure_without_prior_success_is_offline():
    registry.record_failure("fresh", "boom")
    assert registry.get_status("fresh") == "OFFLINE"
    # Circuit needs the full OFFLINE_AFTER_FAILURES streak — one failure
    # must not short-circuit live calls yet.
    assert not registry.circuit_open("fresh")


def test_canonical_statuses_worst_wins():
    registry.record_success("open-meteo", 12.0)
    registry.record_failure("nominatim", "timeout")

    canon = registry.canonical_statuses()
    assert set(canon) == {
        "weather", "seismic", "gis", "routing", "geocoding", "groq",
        "natural_events",
    }
    assert canon["weather"] == "ONLINE"
    assert canon["geocoding"] == "OFFLINE"   # failure, no prior success
    assert canon["seismic"] == "UNKNOWN"     # never probed
    assert canon["natural_events"] == "UNKNOWN"  # EONET never probed


def test_snapshot_reports_circuit_field():
    for _ in range(3):
        registry.record_failure("osrm", "down")
    snap = registry.snapshot()["osrm"]
    assert snap["circuit"] == "open"
    assert snap["consecutive_failures"] == 3


# ── Circuit breaker: fail fast, no network (§31) ────────────────────────────

def test_circuit_open_fails_fast_without_network():
    for _ in range(3):
        registry.record_failure("open-meteo", "HTTP 503")
    assert registry.circuit_open("open-meteo")

    connector = OpenMeteoConnector()
    mock_req = AsyncMock(side_effect=AssertionError("network must not be touched"))
    with patch("httpx.AsyncClient.request", new=mock_req):
        with pytest.raises(ConnectorError) as ei:
            asyncio.run(connector.get_current_weather(22.0, 73.0))

    mock_req.assert_not_called()
    assert "circuit open" in ei.value.message
    assert ei.value.provider == "open-meteo"
    # Circuit-skip must NOT record a failure — otherwise the cooldown
    # window would slide forward forever and half-open could never probe.
    assert registry.snapshot()["open-meteo"]["consecutive_failures"] == 3


def test_circuit_half_open_after_cooldown():
    for _ in range(3):
        registry.record_failure("osrm", "down")
    assert registry.circuit_open("osrm")

    # Simulate the cooldown window expiring.
    st = registry._providers["osrm"]
    st.last_failure_at = time.time() - (registry.CIRCUIT_COOLDOWN_SECONDS + 5.0)
    assert not registry.circuit_open("osrm")   # half-open: one probe allowed

    registry.record_success("osrm", 120.0)
    assert not registry.circuit_open("osrm")
    assert registry.get_status("osrm") == "ONLINE"
    assert registry.snapshot()["osrm"]["circuit"] == "closed"


# ── Weather: stale cache vs distinct "no cache" (§31) ───────────────────────

def test_weather_serves_stale_cache_when_provider_down():
    stale = {
        "latitude": 22.0,
        "longitude": 73.0,
        "timestamp": "2026-09-25T00:00:00+00:00",
        "rainfall_mm_hr": 1.5,
    }

    def fake_cache_get(key: str):
        return stale if key.endswith(":latest") else None

    async def main():
        with patch(
            "app.integrations.cache.cache_get",
            new=AsyncMock(side_effect=fake_cache_get),
        ), patch.object(
            weather_service._connector,
            "get_current_weather",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 503")),
        ):
            obs = await weather_service.get_current_weather(22.0, 73.0, allow_stale=True)
        assert obs.from_cache is True
        assert obs.rainfall_mm_hr == 1.5

    run(main())


def test_weather_distinct_no_cache_message():
    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch.object(
            weather_service._connector,
            "get_current_weather",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 503")),
        ):
            with pytest.raises(ConnectorError) as ei:
                await weather_service.get_current_weather(22.0, 73.0, allow_stale=True)
        # Distinct message — caller can tell "provider down" from
        # "provider down AND nothing cached". Never fabricated.
        assert "no cached weather" in ei.value.message
        assert "fabricated" in ei.value.message
        assert ei.value.provider == "open-meteo"

    run(main())


def test_weather_no_stale_flag_propagates_original_error():
    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch.object(
            weather_service._connector,
            "get_current_weather",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 429")),
        ):
            with pytest.raises(ConnectorError) as ei:
                await weather_service.get_current_weather(22.0, 73.0, allow_stale=False)
        assert "no cached weather" not in ei.value.message
        assert ei.value.message == "HTTP 429"

    run(main())


# ── Nominatim: provider down → honest None (§31) ────────────────────────────

def test_geocode_returns_none_when_provider_down():
    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch(
            "app.integrations.cache.cache_set", new=AsyncMock()
        ), patch(
            "app.services.geocoding.NominatimConnector.search",
            new=AsyncMock(side_effect=ConnectorError("nominatim", "timeout")),
        ):
            out = await geocode("Somewhereville, Nowhere")
        assert out is None   # never invented coordinates

    run(main())


# ── OSRM: provider down → labelled haversine fallback (§31) ─────────────────

def test_route_falls_back_to_haversine_when_osrm_down():
    async def main():
        with patch(
            "app.integrations.gis.osrm.OsrmConnector.route",
            new=AsyncMock(side_effect=ConnectorError("osrm", "HTTP 503")),
        ):
            route = await calculate_route(22.30, 73.20, 22.40, 73.30, db=None)
        assert route["source"] == "fallback_haversine"
        assert "DEGRADED" in route["note"]
        assert route["distance_km"] > 0   # real straight-line distance, honest label

    run(main())


# ── USGS: poller survives provider outage (§31) ─────────────────────────────

def test_poll_seismic_survives_usgs_down():
    async def main():
        with patch(
            "app.integrations.seismic.usgs.UsgsConnector.recent_events",
            new=AsyncMock(side_effect=ConnectorError("usgs", "timeout")),
        ):
            result = await poll_seismic()
        assert result is None   # logged + skipped, no exception, no fake events

    run(main())


# ── Groq: offline fallback + registry recording (§31/§34) ───────────────────

def test_groq_unavailable_returns_offline_fallback():
    async def main():
        with patch.object(
            GroqGateway, "available", new_callable=PropertyMock, return_value=False
        ):
            resp = await groq_gateway.command_query("Which resources are available?")
        assert "offline" in resp.response.lower()
        assert resp.model_used == "offline-fallback"

    run(main())


def test_groq_call_failure_falls_back_and_records_registry():
    async def main():
        with patch.object(
            GroqGateway, "available", new_callable=PropertyMock, return_value=True
        ), patch.object(
            GroqGateway,
            "_call_with_tools",
            new=AsyncMock(side_effect=RuntimeError("groq down")),
        ):
            resp = await groq_gateway.command_query("What is the flood risk?")
        assert "offline" in resp.response.lower()   # honest fallback, no crash
        assert registry.get_status("groq") in ("DEGRADED", "OFFLINE")

    run(main())


def test_groq_success_recorded_in_registry():
    log = AILogRecord(task_type="test", model="m", success=True, latency_ms=42.0)
    _log_call(log)
    assert registry.get_status("groq") == "ONLINE"
    snap = registry.snapshot()["groq"]
    assert snap["latency_ms"] == 42.0
    assert log.success is True


def test_groq_failure_recorded_in_registry():
    _log_call(AILogRecord(task_type="test", model="m", success=False, error="rate limited"))
    snap = registry.snapshot()["groq"]
    assert snap["status"] == "OFFLINE"          # no prior success → OFFLINE
    assert "rate limited" in snap["last_error"]
    assert snap["total_failures"] == 1


# ── Redis: cache swallows outages (§27) ─────────────────────────────────────

def test_cache_survives_redis_down():
    async def main():
        with patch(
            "app.integrations.cache.get_redis",
            new=AsyncMock(side_effect=ConnectionError("redis down")),
        ):
            assert await cache.cache_get("weather:1:2") is None
            await cache.cache_set("weather:1:2", {"a": 1})   # must not raise

    run(main())


# ── DB: auth surfaces 503, not a bare 500 ───────────────────────────────────

def test_login_returns_503_when_db_down():
    from app.api.auth import LoginRequest, login

    async def main():
        broken_db = AsyncMock()
        broken_db.execute.side_effect = RuntimeError("connection refused")
        with pytest.raises(HTTPException) as ei:
            await login(LoginRequest(username="x", password="y"), db=broken_db)
        assert ei.value.status_code == 503
        assert "RuntimeError" in str(ei.value.detail)

    run(main())


# ── /api/health: canonical providers + service reasons (Phase 16) ───────────

def test_health_canonical_provider_keys_and_services():
    async def main():
        with patch("app.main._database_ping", new=AsyncMock()), patch(
            "app.main._cache_ping", new=AsyncMock()
        ):
            body = await health()
        assert body["status"] == "ok"
        assert body["reasons"] == []
        for key in ("weather", "seismic", "gis", "routing", "geocoding", "groq",
                    "natural_events"):
            assert key in body["providers"], key
            assert body["providers"][key]["status"] in (
                "ONLINE", "DEGRADED", "OFFLINE", "UNKNOWN",
            )
        # Raw provider names kept for the frontend (open-meteo, usgs, ...).
        if "open-meteo" in registry.snapshot():
            assert body["providers"]["open-meteo"]["status"] in (
                "ONLINE", "DEGRADED", "OFFLINE",
            )
        assert body["services"] == {"database": "ONLINE", "cache": "ONLINE"}

    run(main())


def test_health_degraded_when_db_down():
    async def main():
        with patch(
            "app.main._database_ping",
            new=AsyncMock(side_effect=RuntimeError("connection refused")),
        ), patch("app.main._cache_ping", new=AsyncMock()):
            body = await health()
        assert body["status"] == "degraded"
        assert body["services"]["database"] == "OFFLINE"
        assert any("database" in r for r in body["reasons"])

    run(main())


def test_health_degraded_when_cache_down():
    async def main():
        with patch("app.main._database_ping", new=AsyncMock()), patch(
            "app.main._cache_ping", new=AsyncMock(side_effect=ConnectionError("redis down"))
        ):
            body = await health()
        assert body["status"] == "degraded"
        assert body["services"]["cache"] == "DEGRADED"
        assert any("cache" in r and "never blocks" in r for r in body["reasons"])

    run(main())


def test_health_providers_reflect_registry_failures():
    registry.record_failure("open-meteo", "HTTP 503")
    registry.record_success("usgs", 80.0)

    async def main():
        with patch("app.main._database_ping", new=AsyncMock()), patch(
            "app.main._cache_ping", new=AsyncMock()
        ):
            body = await health()
        assert body["providers"]["weather"]["status"] == "OFFLINE"
        assert body["providers"]["open-meteo"]["status"] == "OFFLINE"
        assert body["providers"]["seismic"]["status"] == "ONLINE"
        assert body["providers"]["usgs"]["status"] == "ONLINE"
        # Core deps are fine — system stays "ok" while providers degrade
        # (optional providers never take the system down, §31).
        assert body["status"] == "ok"

    run(main())
