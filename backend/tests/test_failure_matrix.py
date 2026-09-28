"""Phase 16 — Failure matrix (plan §31–§32).

Every external dependency can fail; the system must:
  * keep provider state observable (registry state machine),
  * open the circuit after an OFFLINE streak (no network, no fabricated data),
  * serve cache when available and raise a DISTINCT "no cache" message when not,
  * degrade to honest fallbacks (haversine route, offline AI gateway, None geocode),
  * survive Redis/DB outages (cache swallows, auth → 503),
  * report canonical provider groups + service reasons in /api/health.

No live network calls: every provider boundary is mocked.
"""
from __future__ import annotations

import asyncio
import copy
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest
from fastapi import HTTPException

from app.integrations import cache, registry
from app.integrations.base import ConnectorError
from app.integrations.weather.open_meteo import OpenMeteoConnector
from app.main import health
from app.pollers.seismic import poll_seismic
from app.schemas.observations import ForecastResult, ForecastSlice, WeatherObservation
from app.services.geocoding import geocode
from app.services.ai_gateway import AILogRecord, AIGateway, _log_call, ai_gateway
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
        "weather", "seismic", "gis", "routing", "geocoding", "ai",
        "natural_events",
    }
    assert canon["weather"] == "ONLINE"
    assert canon["geocoding"] == "OFFLINE"   # failure, no prior success
    assert canon["seismic"] == "UNKNOWN"     # never probed
    assert canon["natural_events"] == "UNKNOWN"  # EONET never probed


def test_canonical_statuses_any_source_online():
    # Multi-source groups report capability availability: a fallback source
    # serving means weather/geocoding still work (2026-09 fallback feature).
    registry.record_failure("open-meteo", "HTTP 429")
    registry.record_success("met-norway", 40.0)
    registry.record_failure("nominatim", "cloud IP blocked")
    registry.record_success("photon", 30.0)

    canon = registry.canonical_statuses()
    assert canon["weather"] == "ONLINE"
    assert canon["geocoding"] == "ONLINE"

    # Every source down → the group is honestly OFFLINE.
    for _ in range(3):
        registry.record_failure("met-norway", "timeout")
    assert registry.canonical_statuses()["weather"] == "OFFLINE"


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
        ), patch.object(
            weather_service._fallback,
            "get_current_weather",
            new=AsyncMock(side_effect=ConnectorError("met-norway", "down")),
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
        ), patch.object(
            weather_service._fallback,
            "get_current_weather",
            new=AsyncMock(side_effect=ConnectorError("met-norway", "down")),
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
        ), patch.object(
            weather_service._fallback,
            "get_current_weather",
            new=AsyncMock(side_effect=ConnectorError("met-norway", "down")),
        ):
            with pytest.raises(ConnectorError) as ei:
                await weather_service.get_current_weather(22.0, 73.0, allow_stale=False)
        assert "no cached weather" not in ei.value.message
        assert ei.value.message == "HTTP 429"

    run(main())


def test_forecast_serves_stale_cache_when_provider_down():
    stale = {
        "latitude": 22.0,
        "longitude": 73.0,
        "retrieved_at": "2026-09-25T00:00:00+00:00",
        "hours": [],
    }

    def fake_cache_get(key: str):
        return stale if key.endswith(":latest") else None

    async def main():
        with patch(
            "app.integrations.cache.cache_get",
            new=AsyncMock(side_effect=fake_cache_get),
        ), patch.object(
            weather_service._connector,
            "get_forecast",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 429")),
        ), patch.object(
            weather_service._fallback,
            "get_forecast",
            new=AsyncMock(side_effect=ConnectorError("met-norway", "down")),
        ):
            fc = await weather_service.get_forecast(22.0, 73.0, hours=6, allow_stale=True)
        assert fc.from_cache is True
        assert fc.latitude == 22.0

    run(main())


def test_forecast_distinct_no_cache_message():
    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch.object(
            weather_service._connector,
            "get_forecast",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 429")),
        ), patch.object(
            weather_service._fallback,
            "get_forecast",
            new=AsyncMock(side_effect=ConnectorError("met-norway", "down")),
        ):
            with pytest.raises(ConnectorError) as ei:
                await weather_service.get_forecast(22.0, 73.0, hours=6, allow_stale=True)
        assert "no cached forecast" in ei.value.message
        assert "fabricated" in ei.value.message
        assert ei.value.provider == "open-meteo"

    run(main())


def test_forecast_no_stale_flag_propagates_original_error():
    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch.object(
            weather_service._connector,
            "get_forecast",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 429")),
        ), patch.object(
            weather_service._fallback,
            "get_forecast",
            new=AsyncMock(side_effect=ConnectorError("met-norway", "down")),
        ):
            with pytest.raises(ConnectorError) as ei:
                await weather_service.get_forecast(22.0, 73.0, hours=6, allow_stale=False)
        assert "no cached forecast" not in ei.value.message
        assert ei.value.message == "HTTP 429"

    run(main())


# ── Fallback sources: primary down → secondary serves real data (§31) ─────────

def test_weather_falls_back_to_met_norway_when_primary_down():
    fallback_obs = WeatherObservation(
        source="met-norway", observation_type="weather",
        latitude=22.0, longitude=73.0,
        timestamp=datetime.now(timezone.utc),
        rainfall_mm_hr=0.7, temperature_c=29.0,
        wind_speed_kmh=14.4, weather_main="Rain",
        weather_description="Moderate rain",
    )

    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch(
            "app.integrations.cache.cache_set", new=AsyncMock()
        ), patch.object(
            weather_service._connector,
            "get_current_weather",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 429")),
        ), patch.object(
            weather_service._fallback,
            "get_current_weather",
            new=AsyncMock(return_value=fallback_obs),
        ):
            obs = await weather_service.get_current_weather(
                22.0, 73.0, allow_stale=False
            )
        # Live fallback data is allowed even with allow_stale=False —
        # it is a fresh fetch from a secondary source, not a cached value.
        assert obs.source == "met-norway"
        assert obs.rainfall_mm_hr == 0.7
        assert obs.from_cache is False

    run(main())


def test_forecast_falls_back_to_met_norway_when_primary_down():
    fallback_fc = ForecastResult(
        source="met-norway", observation_type="forecast",
        latitude=22.0, longitude=73.0,
        retrieved_at=datetime.now(timezone.utc),
        hours=[ForecastSlice(time="2026-09-25T15:00:00+00:00",
                             precipitation_mm=1.2, temperature_c=28.0)],
    )

    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch(
            "app.integrations.cache.cache_set", new=AsyncMock()
        ), patch.object(
            weather_service._connector,
            "get_forecast",
            new=AsyncMock(side_effect=ConnectorError("open-meteo", "HTTP 429")),
        ), patch.object(
            weather_service._fallback,
            "get_forecast",
            new=AsyncMock(return_value=fallback_fc),
        ):
            fc = await weather_service.get_forecast(
                22.0, 73.0, hours=6, allow_stale=False
            )
        assert fc.source == "met-norway"
        assert fc.hours[0].precipitation_mm == 1.2
        assert fc.from_cache is False

    run(main())


def test_geocode_falls_back_to_photon_when_nominatim_down():
    photon_candidates = [{
        "lat": 22.3119, "lng": 73.1812,
        "display_name": "Vadodara, Gujarat, India",
        "confidence": 0.5, "osm_type": "N", "osm_id": 2022807192,
        "category": "place", "type": "city",
    }]

    async def main():
        with patch(
            "app.integrations.cache.cache_get", new=AsyncMock(return_value=None)
        ), patch(
            "app.integrations.cache.cache_set", new=AsyncMock()
        ), patch(
            "app.services.geocoding.NominatimConnector.search",
            new=AsyncMock(side_effect=ConnectorError("nominatim", "blocked")),
        ), patch(
            "app.services.geocoding.PhotonConnector.search",
            new=AsyncMock(return_value=photon_candidates),
        ):
            out = await geocode("Vadodara, India")
        assert out is not None
        assert out["lat"] == 22.3119
        assert out["display_name"] == "Vadodara, Gujarat, India"

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
        ), patch(
            "app.services.geocoding.PhotonConnector.search",
            new=AsyncMock(side_effect=ConnectorError("photon", "timeout")),
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


# ── AI gateway: offline fallback + registry recording (§31/§34) ────────────────

def test_ai_unavailable_returns_offline_fallback():
    async def main():
        with patch.object(
            AIGateway, "available", new_callable=PropertyMock, return_value=False
        ):
            resp = await ai_gateway.command_query("Which resources are available?")
        assert "offline" in resp.response.lower()
        assert resp.model_used == "offline-fallback"

    run(main())


def test_ai_unavailable_reports_ai_used_false():
    """A missing key must not be reported as a successful AI answer."""
    async def main():
        with patch.object(
            AIGateway, "available", new_callable=PropertyMock, return_value=False
        ):
            resp = await ai_gateway.command_query("Which resources are available?")
        assert resp.ai_used is False

    run(main())


def test_ai_call_failure_does_not_claim_the_nim_model():
    """
    A configured-but-failing key (401, network, rate limit) previously returned
    the deterministic reply while still naming the NIM model in `model_used`,
    so callers could not tell a real answer from a fallback.
    """
    async def main():
        with patch.object(
            AIGateway, "available", new_callable=PropertyMock, return_value=True
        ), patch.object(
            AIGateway,
            "_call_with_tools",
            new=AsyncMock(side_effect=RuntimeError("401 Unauthorized")),
        ):
            resp = await ai_gateway.command_query("What is the flood risk?")
        assert resp.ai_used is False
        assert resp.model_used == "offline-fallback"

    run(main())


def test_ai_success_reports_ai_used_true():
    async def main():
        with patch.object(
            AIGateway, "available", new_callable=PropertyMock, return_value=True
        ), patch.object(
            AIGateway, "_call_with_tools", new=AsyncMock(return_value="Zone 17 is critical.")
        ):
            resp = await ai_gateway.command_query("Which zone is critical?")
        assert resp.ai_used is True
        assert resp.model_used != "offline-fallback"
        assert resp.response == "Zone 17 is critical."

    run(main())


def test_ai_call_failure_falls_back_and_records_registry():
    async def main():
        with patch.object(
            AIGateway, "available", new_callable=PropertyMock, return_value=True
        ), patch.object(
            AIGateway,
            "_call_with_tools",
            new=AsyncMock(side_effect=RuntimeError("nvidia down")),
        ):
            resp = await ai_gateway.command_query("What is the flood risk?")
        assert "offline" in resp.response.lower()   # honest fallback, no crash
        assert registry.get_status("nvidia") in ("DEGRADED", "OFFLINE")

    run(main())


def test_ai_success_recorded_in_registry():
    log = AILogRecord(task_type="test", model="m", success=True, latency_ms=42.0)
    _log_call(log)
    assert registry.get_status("nvidia") == "ONLINE"
    snap = registry.snapshot()["nvidia"]
    assert snap["latency_ms"] == 42.0
    assert log.success is True


def test_ai_failure_recorded_in_registry():
    _log_call(AILogRecord(task_type="test", model="m", success=False, error="rate limited"))
    snap = registry.snapshot()["nvidia"]
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


# ── /api/health: canonical providers + service reasons (Phase 16) ───────────

def test_health_canonical_provider_keys_and_services():
    async def main():
        with patch("app.main._database_ping", new=AsyncMock()), patch(
            "app.main._cache_ping", new=AsyncMock()
        ):
            body = await health()
        assert body["status"] == "ok"
        assert body["reasons"] == []
        for key in ("weather", "seismic", "gis", "routing", "geocoding", "ai",
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
