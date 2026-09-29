"""
IoT flood telemetry API.

Normalized ingestion, latest-reading, history, and device management for IoT
flood-monitoring devices. The same endpoints accept both real device telemetry
(source="iot") and simulated data (source="simulation") so the frontend's Sim
mode and Live mode share one pipeline.

Authentication: devices present `Authorization: Bearer <token>` obtained from
POST /api/iot/v1/devices/register. That endpoint is gated by the
IOT_REGISTRATION_TOKEN bootstrap secret.

Units:
  water_level_m    — metres
  flow_velocity_ms — metres per second
  lat / lng        — WGS84 degrees
  timestamps       — ISO 8601 with timezone
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.device import (
    generate_device_token,
    get_current_device,
    hash_device_token,
    verify_device_token,
)
from app.core.config import get_settings
from app.core.database import get_db
from app.models.device import FloodDevice, FloodTelemetry
from app.services.flood_risk import assess_flood_risk
from app.services.websocket import emit_flood_sensor_updated

router = APIRouter()
logger = structlog.get_logger()

# ── Request / response schemas ──────────────────────────────────────────────


class DeviceRegisterRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    name: str | None = Field(None, max_length=120)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    battery_pct: float | None = Field(None, ge=0, le=100)
    metadata: dict | None = None

    @field_validator("device_id")
    @classmethod
    def _device_id_alnum(cls, v: str) -> str:
        # Device ids appear in URLs and SQL; restrict to a safe charset.
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("device_id may only contain letters, digits, '-' and '_'")
        return v


class TelemetryRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=64)
    water_level: float = Field(..., ge=0, le=50)
    flow_velocity: float = Field(..., ge=0, le=100)
    timestamp: str = Field(..., min_length=8, max_length=40)
    event_id: str | None = Field(None, max_length=80)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    source: str = Field("iot", pattern="^(iot|simulation)$")

    @field_validator("timestamp")
    @classmethod
    def _valid_timestamp(cls, v: str) -> str:
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("timestamp must be a valid ISO 8601 string")
        return v


class TelemetryResponse(BaseModel):
    id: str
    device_id: str
    status: str
    risk_level: str | None = None
    risk_score: float | None = None
    received_at: str


class LatestReading(BaseModel):
    device_id: str
    water_level: float
    flow_velocity: float
    timestamp: str
    received_at: str
    age_seconds: float | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    device_status: str | None = None
    battery_pct: float | None = None
    signal_strength: float | None = None


class HistoryPoint(BaseModel):
    water_level: float
    flow_velocity: float
    timestamp: str
    risk_level: str | None = None
    risk_score: float | None = None


class DeviceResponse(BaseModel):
    device_id: str
    name: str | None
    status: str
    lat: float | None
    lng: float | None
    battery_pct: float | None
    signal_strength: float | None
    last_seen_at: str | None
    created_at: str


class RegisterResponse(BaseModel):
    device_id: str
    token: str
    name: str | None
    status: str


# ── Device registration ────────────────────────────────────────────────────


@router.post("/devices/register", response_model=RegisterResponse, status_code=201)
async def register_device(
    body: DeviceRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Register a new flood device and return its bearer token.

    Gated by the IOT_REGISTRATION_TOKEN bootstrap secret. The token is shown
    exactly once — only its hash is stored.
    """
    settings = get_settings()
    presented = request.headers.get("Authorization") or request.headers.get("authorization")
    expected = f"Bearer {settings.iot_registration_token}"
    if not settings.iot_registration_token or presented != expected:
        raise HTTPException(status_code=401, detail="Invalid registration token")

    existing = (
        await db.execute(
            select(FloodDevice).where(FloodDevice.device_id == body.device_id).limit(1)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="device_id already registered")

    token = generate_device_token()
    device = FloodDevice(
        device_id=body.device_id,
        name=body.name,
        lat=body.lat,
        lng=body.lng,
        token_hash=hash_device_token(token),
        battery_pct=body.battery_pct,
        metadata_json=body.metadata,
        status="active",
    )
    db.add(device)
    await db.commit()

    return RegisterResponse(
        device_id=device.device_id,
        token=token,
        name=device.name,
        status=device.status,
    )


@router.get("/devices", response_model=list[DeviceResponse])
async def list_devices(
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all registered devices.

    Operator read, not a device operation: the console needs it to populate a
    device picker, so it uses the same public passthrough as every other
    console read in this API. A device token is NOT accepted here on purpose --
    the browser must never hold one (see /telemetry for the device-gated path).
    """
    rows = (await db.execute(select(FloodDevice).order_by(FloodDevice.created_at.desc()))).scalars().all()
    return [
        DeviceResponse(
            device_id=d.device_id,
            name=d.name,
            status=d.status,
            lat=d.lat,
            lng=d.lng,
            battery_pct=d.battery_pct,
            signal_strength=d.signal_strength,
            last_seen_at=d.last_seen_at.isoformat() if d.last_seen_at else None,
            created_at=d.created_at.isoformat() if d.created_at else None,
        )
        for d in rows
    ]


# ── Telemetry ingestion ─────────────────────────────────────────────────────


@router.post("/telemetry", response_model=TelemetryResponse, status_code=201)
async def ingest_telemetry(
    body: TelemetryRequest,
    device: FloodDevice = Depends(get_current_device),
    db: AsyncSession = Depends(get_db),
):
    """Accept one normalized flood reading from an authenticated device.

    Idempotent on `event_id`: a device that retries after a timeout gets 200
    with the original record rather than a duplicate row.
    """
    # The path is authenticated by token; the body's device_id must match.
    if body.device_id != device.device_id:
        raise HTTPException(
            status_code=403,
            detail="device_id in body does not match the authenticated device",
        )

    # Idempotency: if this event_id was already stored, return it.
    if body.event_id:
        existing = (
            await db.execute(
                select(FloodTelemetry)
                .where(
                    FloodTelemetry.device_id == device.device_id,
                    FloodTelemetry.event_id == body.event_id,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return TelemetryResponse(
                id=existing.id,
                device_id=existing.device_id,
                status="duplicate",
                risk_level=existing.risk_level,
                risk_score=existing.risk_score,
                received_at=existing.received_at.isoformat() if existing.received_at else None,
            )

    ts = datetime.fromisoformat(body.timestamp.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    risk = assess_flood_risk(
        water_level_m=body.water_level,
        flow_velocity_ms=body.flow_velocity,
        device_timestamp=body.timestamp,
        lat=body.lat,
        lng=body.lng,
    )

    telemetry = FloodTelemetry(
        device_id=device.device_id,
        event_id=body.event_id,
        source=body.source,
        water_level_m=body.water_level,
        flow_velocity_ms=body.flow_velocity,
        device_timestamp=ts,
        lat=body.lat,
        lng=body.lng,
        risk_level=risk.risk_level,
        risk_score=risk.risk_score,
    )
    db.add(telemetry)

    device.last_seen_at = datetime.now(timezone.utc)
    if body.lat is not None and body.lng is not None:
        device.lat = body.lat
        device.lng = body.lng

    await db.commit()

    # Publish the real-time event for the dashboard. A broadcast failure must
    # not fail the ingest (the reading is already committed and readable via
    # GET /latest), but it must not be silent either: a dashboard that silently
    # stops updating looks identical to a device that stopped reporting.
    try:
        await emit_flood_sensor_updated(
            device_id=device.device_id,
            timestamp=body.timestamp,
            water_level=body.water_level,
            flow_velocity=body.flow_velocity,
            risk_level=risk.risk_level,
            risk_score=risk.risk_score,
            source=body.source,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "flood_websocket_emit_failed",
            device_id=device.device_id,
            error=type(exc).__name__,
            detail=str(exc)[:200],
        )

    return TelemetryResponse(
        id=telemetry.id,
        device_id=telemetry.device_id,
        status="accepted",
        risk_level=risk.risk_level,
        risk_score=risk.risk_score,
        received_at=telemetry.received_at.isoformat() if telemetry.received_at else None,
    )


# ── Latest reading ─────────────────────────────────────────────────────────


@router.get("/devices/{device_id}/latest", response_model=LatestReading)
async def latest_reading(
    device_id: str,
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Most recent telemetry for a device.

    Operator read used by the console's Live mode, so it follows the same
    public passthrough as the rest of the API rather than device auth -- a
    device token is a device secret and must never be shipped to a browser.

    Returns the device timestamp (what the sensor reported) separately from
    received_at (when the API accepted it) so the frontend can show the right
    one. Includes device health fields.
    """
    row = (
        await db.execute(
            select(FloodTelemetry)
            .where(FloodTelemetry.device_id == device_id)
            .order_by(FloodTelemetry.device_timestamp.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="No telemetry for this device")

    age = None
    if row.received_at is not None:
        age = round(
            max(0.0, (datetime.now(timezone.utc) - row.received_at).total_seconds()), 1
        )

    # Health fields live on the device, not the reading. The row's own
    # device_id always matches, so a miss here just means unregistered.
    device = (
        await db.execute(
            select(FloodDevice).where(FloodDevice.device_id == row.device_id).limit(1)
        )
    ).scalar_one_or_none()

    return LatestReading(
        device_id=row.device_id,
        water_level=row.water_level_m,
        flow_velocity=row.flow_velocity_ms,
        timestamp=row.device_timestamp.isoformat(),
        received_at=row.received_at.isoformat() if row.received_at else None,
        age_seconds=age,
        risk_level=row.risk_level,
        risk_score=row.risk_score,
        device_status=device.status if device else None,
        battery_pct=device.battery_pct if device else None,
        signal_strength=device.signal_strength if device else None,
    )


# ── History ────────────────────────────────────────────────────────────────


@router.get("/devices/{device_id}/history", response_model=list[HistoryPoint])
async def device_history(
    device_id: str,
    _: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    from_ts: str | None = Query(None, alias="from"),
    to_ts: str | None = Query(None, alias="to"),
):
    """Chronological telemetry history for a device (console read, not device-gated).

    `from` and `to` are ISO 8601 timestamps. Results are ascending by device
    timestamp so a chart can render them in order.
    """
    stmt = (
        select(FloodTelemetry)
        .where(FloodTelemetry.device_id == device_id)
        .order_by(FloodTelemetry.device_timestamp.asc())
    )
    if from_ts:
        try:
            stmt = stmt.where(
                FloodTelemetry.device_timestamp
                >= datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
            )
        except ValueError:
            raise HTTPException(status_code=422, detail="from must be ISO 8601")
    if to_ts:
        try:
            stmt = stmt.where(
                FloodTelemetry.device_timestamp
                <= datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
            )
        except ValueError:
            raise HTTPException(status_code=422, detail="to must be ISO 8601")

    rows = (await db.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return [
        HistoryPoint(
            water_level=r.water_level_m,
            flow_velocity=r.flow_velocity_ms,
            timestamp=r.device_timestamp.isoformat(),
            risk_level=r.risk_level,
            risk_score=r.risk_score,
        )
        for r in rows
    ]
