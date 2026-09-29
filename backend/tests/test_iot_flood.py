"""IoT flood telemetry integration tests.

Covers the full flow: device registration, authentication, telemetry ingestion,
idempotency, latest reading, history, validation, and flood risk analysis.
No network, no real devices — everything runs against the test database.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app  # noqa: E402

from app.auth.device import generate_device_token, hash_device_token, verify_device_token
from app.services.flood_risk import (
    FLOW_VELOCITY_HIGH_MS,
    FLOW_VELOCITY_LOW_MS,
    FLOW_VELOCITY_MEDIUM_MS,
    WATER_LEVEL_HIGH_M,
    WATER_LEVEL_LOW_M,
    WATER_LEVEL_MEDIUM_M,
    assess_flood_risk,
)


def _uid() -> str:
    """Unique device id per call so tests do not collide on a persistent DB."""
    return f"FLOOD-{uuid.uuid4().hex[:12].upper()}"


@pytest.fixture(scope="module")
def client():
    # Deliberately does NOT clear the settings cache. conftest sets
    # IOT_REGISTRATION_TOKEN before any app import, so the cached Settings
    # already carry it. Clearing here would wipe the process-wide cache during
    # teardown and make later test modules re-read .env, breaking tests that
    # rely on a patched key (e.g. test_ai_providers::test_health_no_key).
    with TestClient(app) as c:
        yield c

# ── Flood risk analysis (pure) ──────────────────────────────────────────────


class TestFloodRisk:
    def test_normal_reading(self):
        r = assess_flood_risk(water_level_m=1.0, flow_velocity_ms=0.5)
        assert r.risk_level == "NORMAL"
        assert r.risk_score == 0.0
        assert r.basis == []

    def test_water_level_warning(self):
        r = assess_flood_risk(water_level_m=WATER_LEVEL_LOW_M, flow_velocity_ms=0.5)
        assert r.risk_level == "WARNING"
        assert r.water_level_band == "MEDIUM"
        assert "water_level" in r.basis

    def test_water_level_critical(self):
        r = assess_flood_risk(water_level_m=WATER_LEVEL_HIGH_M, flow_velocity_ms=0.5)
        assert r.risk_level == "CRITICAL"
        assert r.risk_score == 1.0

    def test_flow_velocity_drives_risk(self):
        r = assess_flood_risk(water_level_m=0.5, flow_velocity_ms=FLOW_VELOCITY_HIGH_MS)
        assert r.risk_level == "CRITICAL"
        assert "flow_velocity" in r.basis

    def test_max_of_two_bands(self):
        # Water level is WARNING, flow is CRITICAL → overall CRITICAL
        r = assess_flood_risk(
            water_level_m=WATER_LEVEL_MEDIUM_M,
            flow_velocity_ms=FLOW_VELOCITY_HIGH_MS,
        )
        assert r.risk_level == "CRITICAL"

    def test_score_is_normalised_severity(self):
        low = assess_flood_risk(water_level_m=WATER_LEVEL_LOW_M, flow_velocity_ms=0.0)
        med = assess_flood_risk(water_level_m=WATER_LEVEL_MEDIUM_M, flow_velocity_ms=0.0)
        high = assess_flood_risk(water_level_m=WATER_LEVEL_HIGH_M, flow_velocity_ms=0.0)
        assert low.risk_score < med.risk_score < high.risk_score

    def test_thresholds_match_frontend(self):
        """The backend thresholds must agree with the frontend's banding or the
        console and the API will disagree about what 'warning' means."""
        assert WATER_LEVEL_LOW_M == 1.5
        assert WATER_LEVEL_MEDIUM_M == 2.5
        assert WATER_LEVEL_HIGH_M == 3.5
        assert FLOW_VELOCITY_LOW_MS == 1.0
        assert FLOW_VELOCITY_MEDIUM_MS == 2.0
        assert FLOW_VELOCITY_HIGH_MS == 3.0

    def test_output_has_no_fabricated_confidence(self):
        r = assess_flood_risk(water_level_m=1.0, flow_velocity_ms=0.5)
        d = r.to_dict()
        assert d["model"] == "rule_based_thresholds"
        assert "confidence" not in d


# ── Device token hashing (pure) ─────────────────────────────────────────────


class TestDeviceToken:
    def test_hash_is_deterministic(self):
        assert hash_device_token("abc") == hash_device_token("abc")

    def test_hash_differs_per_token(self):
        assert hash_device_token("abc") != hash_device_token("abd")

    def test_verify_correct_token(self):
        t = generate_device_token()
        assert verify_device_token(t, hash_device_token(t)) is True

    def test_verify_wrong_token(self):
        t = generate_device_token()
        assert verify_device_token("wrong", hash_device_token(t)) is False

    def test_token_is_high_entropy(self):
        t = generate_device_token()
        assert len(t) == 48


# ── API integration (DB-backed) ─────────────────────────────────────────────
# asyncio_mode = auto (pytest.ini) collects bare `async def` tests without a
# marker, so no pytestmark is needed here.


class TestDeviceRegistration:
    async def test_register_returns_token_once(self, client):
        resp = client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": _uid(), "name": "Test Sensor"},
            headers={"Authorization": "Bearer test-reg-token"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["device_id"]
        assert body["token"]
        assert body["status"] == "active"

    async def test_register_requires_bootstrap_token(self, client):
        resp = client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": _uid()},
        )
        assert resp.status_code == 401

    async def test_register_duplicate_device_id(self, client):
        headers = {"Authorization": "Bearer test-reg-token"}
        device_id = _uid()
        client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": device_id},
            headers=headers,
        )
        resp = client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": device_id},
            headers=headers,
        )
        assert resp.status_code == 409

    async def test_register_rejects_bad_device_id(self, client):
        resp = client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": "bad id with spaces!"},
            headers={"Authorization": "Bearer test-reg-token"},
        )
        assert resp.status_code == 422


class TestTelemetryIngestion:
    async def _register(self, client, device_id=None):
        """Register a device and return (token, device_id).

        The device_id MUST be reused in the telemetry body: the endpoint rejects
        a body whose device_id does not match the authenticated device, so
        generating a fresh id for the payload would always 403.
        """
        if device_id is None:
            device_id = _uid()
        resp = client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": device_id},
            headers={"Authorization": "Bearer test-reg-token"},
        )
        return resp.json()["token"], device_id

    async def test_ingest_requires_auth(self, client):
        resp = client.post(
            "/api/iot/v1/telemetry",
            json={
                "device_id": _uid(),
                "water_level": 1.0,
                "flow_velocity": 0.5,
                "timestamp": "2026-09-29T16:00:00Z",
            },
        )
        assert resp.status_code == 401

    async def test_ingest_valid_telemetry(self, client):
        token, device_id = await self._register(client)
        resp = client.post(
            "/api/iot/v1/telemetry",
            json={
                "device_id": device_id,
                "water_level": 1.5,
                "flow_velocity": 0.8,
                "timestamp": "2026-09-29T16:00:00Z",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "accepted"
        assert body["risk_level"] == "WARNING"

    async def test_ingest_rejects_bad_measurement(self, client):
        token, device_id = await self._register(client)
        resp = client.post(
            "/api/iot/v1/telemetry",
            json={
                "device_id": device_id,
                "water_level": -1,
                "flow_velocity": 0.5,
                "timestamp": "2026-09-29T16:00:00Z",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_ingest_rejects_bad_timestamp(self, client):
        token, device_id = await self._register(client)
        resp = client.post(
            "/api/iot/v1/telemetry",
            json={
                "device_id": device_id,
                "water_level": 1.0,
                "flow_velocity": 0.5,
                "timestamp": "not-a-date",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_ingest_rejects_unknown_device(self, client):
        resp = client.post(
            "/api/iot/v1/telemetry",
            json={
                "device_id": _uid(),
                "water_level": 1.0,
                "flow_velocity": 0.5,
                "timestamp": "2026-09-29T16:00:00Z",
            },
            headers={"Authorization": "Bearer totally-made-up-token"},
        )
        assert resp.status_code == 403

    async def test_ingest_idempotent_on_event_id(self, client):
        token, device_id = await self._register(client)
        payload = {
            "device_id": device_id,
            "water_level": 2.0,
            "flow_velocity": 1.0,
            "timestamp": "2026-09-29T16:00:00Z",
            "event_id": "evt-001",
        }
        headers = {"Authorization": f"Bearer {token}"}
        r1 = client.post("/api/iot/v1/telemetry", json=payload, headers=headers)
        r2 = client.post("/api/iot/v1/telemetry", json=payload, headers=headers)
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r2.json()["status"] == "duplicate"
        assert r1.json()["id"] == r2.json()["id"]

    async def test_ingest_body_device_must_match_token(self, client):
        token, _ = await self._register(client)
        resp = client.post(
            "/api/iot/v1/telemetry",
            json={
                "device_id": _uid(),
                "water_level": 1.0,
                "flow_velocity": 0.5,
                "timestamp": "2026-09-29T16:00:00Z",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


class TestLatestAndHistory:
    async def _register_and_send(self, client, device_id, readings):
        reg = client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": device_id},
            headers={"Authorization": "Bearer test-reg-token"},
        )
        token = reg.json()["token"]
        for i, (wl, fv) in enumerate(readings):
            client.post(
                "/api/iot/v1/telemetry",
                json={
                    "device_id": device_id,
                    "water_level": wl,
                    "flow_velocity": fv,
                    "timestamp": f"2026-09-29T16:{i:02d}:00Z",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
        return token

    async def test_latest_returns_most_recent(self, client):
        device_id = _uid()
        token = await self._register_and_send(
            client, device_id, [(1.0, 0.5), (2.0, 1.0), (3.0, 1.5)]
        )
        resp = client.get(
            f"/api/iot/v1/devices/{device_id}/latest",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["water_level"] == 3.0
        assert body["flow_velocity"] == 1.5
        assert body["timestamp"] == "2026-09-29T16:02:00+00:00"
        assert body["received_at"] is not None
        assert body["device_status"] == "active"

    async def test_latest_404_when_no_data(self, client):
        device_id = _uid()
        reg = client.post(
            "/api/iot/v1/devices/register",
            json={"device_id": device_id},
            headers={"Authorization": "Bearer test-reg-token"},
        )
        token = reg.json()["token"]
        resp = client.get(
            f"/api/iot/v1/devices/{device_id}/latest",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    async def test_history_chronological(self, client):
        device_id = _uid()
        token = await self._register_and_send(
            client, device_id, [(1.0, 0.5), (2.0, 1.0), (3.0, 1.5)]
        )
        resp = client.get(
            f"/api/iot/v1/devices/{device_id}/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 3
        assert rows[0]["water_level"] == 1.0
        assert rows[2]["water_level"] == 3.0

    async def test_history_respects_limit(self, client):
        device_id = _uid()
        token = await self._register_and_send(
            client, device_id, [(1.0, 0.5), (2.0, 1.0), (3.0, 1.5)]
        )
        resp = client.get(
            f"/api/iot/v1/devices/{device_id}/history?limit=2",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_history_is_an_operator_read_not_device_gated(self, client):
        """The console reads history without a device token, because a device
        token is a device secret and must never reach a browser. Ingestion stays
        device-gated (see TestTelemetryIngestion::test_ingest_requires_auth)."""
        device_id = _uid()
        token = await self._register_and_send(client, device_id, [(1.2, 0.6)])
        resp = client.get(f"/api/iot/v1/devices/{device_id}/history")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_latest_is_readable_without_a_device_token(self, client):
        device_id = _uid()
        await self._register_and_send(client, device_id, [(2.1, 1.2)])
        resp = client.get(f"/api/iot/v1/devices/{device_id}/latest")
        assert resp.status_code == 200
        assert resp.json()["water_level"] == 2.1

    async def test_devices_list_is_an_operator_read(self, client):
        resp = client.get("/api/iot/v1/devices")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
