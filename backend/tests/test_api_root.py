"""
API root / health / OpenAPI regression tests.
Run from backend/:  pytest tests/ -q
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    # Lifespan starts pollers; they are best-effort and do not block these tests.
    with TestClient(app) as c:
        yield c


def test_api_root_metadata(client: TestClient):
    r = client.get("/api")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "AegisAI API"
    assert body["version"] == "1.0.0"
    assert body["status"] == "operational"
    assert body["docs"] == "/docs"
    assert body["health"] == "/api/health"
    # Must not leak secrets
    assert "nvapi-" not in r.text
    assert "NVIDIA_API_KEY" not in body


def test_api_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"
    assert "build" in body


def test_root_get_and_head(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["message"] == "AegisAI API"
    h = client.head("/")
    assert h.status_code == 200
    assert h.content == b""


def test_health_head(client: TestClient):
    h = client.head("/api/health")
    assert h.status_code == 200
    assert h.content == b""


def test_api_root_head(client: TestClient):
    h = client.head("/api")
    assert h.status_code == 200
    assert h.content == b""


def test_docs_and_openapi(client: TestClient):
    assert client.get("/docs").status_code == 200
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    paths = spec.json()["paths"]
    # New route present
    assert "/api" in paths
    # Existing contract preserved
    for p in (
        "/api/health",
        "/api/reports",
        "/api/reports/voice",
        "/api/incidents",
        "/api/incidents/{incident_id}",
        "/api/zones",
        "/api/zones/{zone_id}",
        "/api/zones/{zone_id}/reports/summary",
        "/api/actions/{action_id}",
        "/api/resources",
        "/api/resources/{incident_id}/assign-resources",
        "/api/resources/{resource_id}",
        "/api/predictions/flood",
        "/api/predictions/fire",
        "/api/predictions/{zone_id}",
        "/api/predictions/what-if",
        "/api/command/health",
        "/api/command/query",
        "/api/command/explain/{incident_id}",
        "/api/command/summarise/{incident_id}",
        "/api/command/resources/available",
        "/api/command/zone-status",
        "/api/command/critical",
        "/api/command/reports",
        "/api/command/approval-queue",
        "/api/phase2/models",
        "/api/phase2/models/{model_name}",
        "/api/phase2/behaviour/assess",
        "/api/phase2/supply/forecast",
        "/api/phase2/volunteers/match",
        "/api/heatmaps/priority",
        "/api/heatmaps/victim-density",
        "/api/heatmaps/trust-score",
        "/api/heatmaps/disaster-type",
        "/api/heatmaps/combined",
    ):
        assert p in paths, f"missing path: {p}"


def test_no_double_api_prefix(client: TestClient):
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/api" not in paths


def test_incidents_public(client: TestClient):
    r = client.get("/api/incidents")
    assert r.status_code == 200


def test_zones_public(client: TestClient):
    r = client.get("/api/zones")
    assert r.status_code == 200


def test_create_zone_persists_and_is_idempotent(client: TestClient):
    """A declared zone must be readable back, and re-posting its name must
    update it rather than create a second row."""
    # Unique per run: the suite shares one database, and a fixed name would
    # make "created" depend on whether a previous run left the row behind.
    name = f"Test Reach {uuid.uuid4().hex[:8]}"
    payload = {
        "name": name,
        "centroid_lat": 22.3072,
        "centroid_lng": 73.1812,
        "radius_meters": 2500.0,
        "density_ratio": 0.4,
    }

    first = client.post("/api/zones", json=payload)
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["created"] is True
    assert body["density_ratio"] == 0.4
    assert body["radius_meters"] == 2500.0

    # The zone is now a real row, not just an echoed request.
    listed = client.get("/api/zones").json()
    match = [z for z in listed["zones"] if z["zone_id"] == body["zone_id"]]
    assert len(match) == 1
    assert match[0]["density_ratio"] == 0.4

    # Re-posting the same name updates geometry, and says so.
    second = client.post(
        "/api/zones",
        json={**payload, "radius_meters": 4000.0, "density_ratio": 0.7},
    )
    assert second.status_code == 201
    assert second.json()["created"] is False
    assert second.json()["zone_id"] == body["zone_id"]
    assert second.json()["radius_meters"] == 4000.0

    after = client.get("/api/zones").json()
    assert len([z for z in after["zones"] if z["zone_id"] == body["zone_id"]]) == 1


def test_create_zone_rejects_out_of_range_geometry(client: TestClient):
    """Bad coordinates must be refused rather than stored."""
    for bad in (
        {"name": "Bad Lat", "centroid_lat": 91.0, "centroid_lng": 0.0},
        {"name": "Bad Lng", "centroid_lat": 0.0, "centroid_lng": 181.0},
        {"name": "Bad Radius", "centroid_lat": 0.0, "centroid_lng": 0.0, "radius_meters": 0},
        {"name": "Bad Density", "centroid_lat": 0.0, "centroid_lng": 0.0, "density_ratio": 1.5},
        {"name": "   ", "centroid_lat": 0.0, "centroid_lng": 0.0},
    ):
        r = client.post("/api/zones", json=bad)
        assert r.status_code == 422, f"{bad} was accepted"


def test_create_zone_builds_postgis_polygon(client: TestClient):
    """A declared zone gets real geometry so provider readings can be joined
    spatially. Without a polygon, every spatial query silently returns nothing."""
    r = client.post(
        "/api/zones",
        json={
            "name": f"Geometry Check {uuid.uuid4().hex[:8]}",
            "centroid_lat": 22.3072,
            "centroid_lng": 73.1812,
            "radius_meters": 1000.0,
        },
    )
    assert r.status_code == 201
    zone_id = r.json()["zone_id"]

    detail = client.get(f"/api/zones/{zone_id}").json()
    assert detail["zone_id"] == zone_id


def test_resources_public(client: TestClient):
    r = client.get("/api/resources")
    assert r.status_code == 200


def test_command_health_public(client: TestClient):
    r = client.get("/api/command/health")
    assert r.status_code == 200
    body = r.json()
    assert "ai_available" in body
    assert "nvapi-" not in r.text


def test_approval_queue_public(client: TestClient):
    r = client.get("/api/command/approval-queue")
    assert r.status_code == 200


def test_invalid_token_ignored(client: TestClient):
    # Public demo mode: bearer tokens are not required or validated.
    r = client.get(
        "/api/incidents",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 200


# ── Phase 17 — exact §41 endpoint contract ──────────────────────────────────
# The full public surface, frozen: proof that nothing was renamed or removed
# across Phases 1–17 (additive-only changes allowed).
CONTRACT_ENDPOINTS: dict[str, set[str]] = {
    "/api": {"GET"},
    "/api/actions/{action_id}": {"PATCH"},
    "/api/ai/analyze-image": {"POST"},
    "/api/ai/analyze-report": {"POST"},
    "/api/ai/classify-hazard": {"POST"},
    "/api/ai/explain": {"POST"},
    "/api/ai/forecast": {"POST"},
    "/api/ai/health": {"GET"},
    "/api/ai/models": {"GET"},
    "/api/ai/models/{model_id}": {"GET"},
    "/api/ai/predict": {"POST"},
    "/api/ai/providers": {"GET"},
    "/api/ai/summarize": {"POST"},
    "/api/ai/verify-report": {"POST"},
    "/api/command/approval-queue": {"GET"},
    "/api/command/critical": {"GET"},
    "/api/command/explain/{incident_id}": {"GET"},
    "/api/command/health": {"GET"},
    "/api/command/query": {"POST"},
    "/api/command/reports": {"GET"},
    "/api/command/resources/available": {"GET"},
    "/api/command/summarise/{incident_id}": {"GET"},
    "/api/command/zone-status": {"GET"},
    "/api/decision/approve": {"POST"},
    "/api/decision/pending": {"GET"},
    "/api/decision/recommend": {"POST"},
    "/api/decision/reject": {"POST"},
    "/api/decision/{decision_id}": {"GET"},
    "/api/earthquakes/recent": {"GET"},
    "/api/firms/fires": {"GET"},
    "/api/firms/fires/global": {"GET"},
    "/api/globe/assets": {"GET"},
    "/api/globe/assets/{asset_id}": {"GET"},
    "/api/globe/token": {"GET"},
    "/api/health": {"GET"},
    "/api/maps/geocode": {"GET"},
    "/api/maps/places": {"GET"},
    "/api/maps/reverse-geocode": {"GET"},
    "/api/openai/analyze-disaster": {"POST"},
    "/api/openai/chat": {"POST"},
    "/api/traffic/flow": {"GET"},
    "/api/traffic/route": {"GET"},
    "/api/traffic/search": {"GET"},
    "/api/heatmaps/combined": {"GET"},
    "/api/heatmaps/disaster-type": {"GET"},
    "/api/heatmaps/priority": {"GET"},
    "/api/heatmaps/trust-score": {"GET"},
    "/api/heatmaps/victim-density": {"GET"},
    "/api/incidents": {"GET"},
    "/api/incidents/{incident_id}": {"GET"},
    "/api/nasa/eonet/events": {"GET"},
    "/api/phase2/behaviour/assess": {"POST"},
    "/api/phase2/models": {"GET"},
    "/api/phase2/models/{model_name}": {"GET"},
    "/api/phase2/supply/forecast": {"POST"},
    "/api/phase2/volunteers/match": {"POST"},
    "/api/predictions/fire": {"POST"},
    "/api/predictions/flood": {"POST"},
    "/api/predictions/what-if": {"POST"},
    "/api/predictions/{zone_id}": {"GET"},
    "/api/reports": {"GET", "POST"},
    "/api/reports/voice": {"POST"},
    "/api/resources": {"GET", "POST"},
    "/api/resources/{incident_id}/assign-resources": {"POST"},
    "/api/resources/{resource_id}": {"PUT"},
    "/api/routes/compute": {"POST"},
    "/api/weather/current": {"GET"},
    "/api/weather/forecast": {"GET"},
    "/api/zones": {"GET", "POST"},
    "/api/zones/{zone_id}": {"GET"},
    "/api/zones/{zone_id}/reports/summary": {"GET"},
}


def test_contract_exact_endpoint_set(client: TestClient):
    """OpenAPI must match the §41 list exactly — no renames, no removals,
    and no surprise endpoints outside the frozen contract."""
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    # Exact set: every contracted path exists …
    for path, methods in CONTRACT_ENDPOINTS.items():
        assert path in paths, f"contract endpoint missing: {path}"
        actual = {
            m.upper()
            for m in paths[path]
            if m in ("get", "post", "put", "patch", "delete")
        }
        assert methods <= actual, f"{path}: expected {methods}, got {actual}"

    # … and every live path is in the contract (nothing added silently).
    # HEAD/OPTIONS are routing metadata, not endpoints — ignore them.
    live = {
        p
        for p in paths
        if p in CONTRACT_ENDPOINTS
    }
    extra = set(paths) - set(CONTRACT_ENDPOINTS)
    assert not extra, f"endpoints outside the §41 contract: {sorted(extra)}"
    assert live == set(CONTRACT_ENDPOINTS)


def test_command_query_validation_without_token(client: TestClient):
    # Public demo: body validation is reached without any auth.
    r = client.post("/api/command/query", json={})
    assert r.status_code == 422


def test_heatmaps_priority(client: TestClient):
    for path in (
        "/api/heatmaps/priority",
        "/api/heatmaps/victim-density",
        "/api/heatmaps/trust-score",
        "/api/heatmaps/disaster-type",
        "/api/heatmaps/combined",
    ):
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
        body = r.json()
        assert "cells" in body


def test_command_query_validation(client: TestClient):
    # Public demo: body validation is reached without any auth.
    r = client.post("/api/command/query", json={})
    assert r.status_code == 422
