"""
API root / health / OpenAPI regression tests.
Run from backend/:  pytest tests/ -q
"""
from __future__ import annotations

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
    assert "gsk_" not in r.text
    assert "GROQ_API_KEY" not in body


def test_api_health(client: TestClient):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "version": "1.0.0"}


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
        "/api/auth/login",
        "/api/auth/me",
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


def test_login_validation(client: TestClient):
    r = client.post("/api/auth/login", json={})
    assert r.status_code == 422


def test_incidents_requires_auth(client: TestClient):
    r = client.get("/api/incidents")
    assert r.status_code == 401


def test_zones_requires_auth(client: TestClient):
    r = client.get("/api/zones")
    assert r.status_code == 401


def test_resources_requires_auth(client: TestClient):
    r = client.get("/api/resources")
    assert r.status_code == 401


def test_command_health_public(client: TestClient):
    r = client.get("/api/command/health")
    assert r.status_code == 200
    body = r.json()
    assert "groq_available" in body
    assert "gsk_" not in r.text


def test_approval_queue_requires_auth(client: TestClient):
    r = client.get("/api/command/approval-queue")
    assert r.status_code == 401


def test_invalid_token_rejected(client: TestClient):
    r = client.get(
        "/api/incidents",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


def test_command_query_requires_auth(client: TestClient):
    r = client.post("/api/command/query", json={})
    assert r.status_code == 401


def test_heatmaps_priority(client: TestClient):
    lr = client.post(
        "/api/auth/login",
        json={"username": "commander@aegis.demo", "password": "demo123"},
    )
    assert lr.status_code == 200, lr.text
    headers = {"Authorization": f"Bearer {lr.json()['access_token']}"}
    for path in (
        "/api/heatmaps/priority",
        "/api/heatmaps/victim-density",
        "/api/heatmaps/trust-score",
        "/api/heatmaps/disaster-type",
        "/api/heatmaps/combined",
    ):
        r = client.get(path, headers=headers)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
        body = r.json()
        assert "cells" in body


def test_command_query_validation(client: TestClient):
    # Auth runs before body validation — log in first to reach the 422 path.
    lr = client.post(
        "/api/auth/login",
        json={"username": "analyst@aegis.demo", "password": "demo123"},
    )
    assert lr.status_code == 200, lr.text
    token = lr.json()["access_token"]
    r = client.post(
        "/api/command/query",
        json={},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 422
