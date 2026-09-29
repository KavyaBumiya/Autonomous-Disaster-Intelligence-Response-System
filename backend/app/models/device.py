import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import String, Float, DateTime, Boolean, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FloodDevice(Base):
    """A registered IoT flood-monitoring device.

    Devices are registered by an operator (or the device itself with a
    registration token) and then authenticate each telemetry POST with a
    per-device bearer token. The token hash is stored, never the plaintext.
    """

    __tablename__ = "flood_devices"

    __table_args__ = (
        Index("ix_flood_devices_status", "status"),
        Index("ix_flood_devices_last_seen", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    device_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    device_type: Mapped[str] = mapped_column(String(40), default="flood_sensor")
    status: Mapped[str] = mapped_column(String(20), default="active")
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FloodTelemetry(Base):
    """One normalized flood-sensor reading.

    `device_timestamp` is what the sensor reported; `received_at` is when the
    API accepted it. They can differ on lossy IoT networks, and the frontend
    must show the device time, not the server time.

    `source` distinguishes real IoT data from simulated data fed into the same
    pipeline for testing. `event_id` gives idempotency: a device retrying a
    POST after a timeout must not create a duplicate row.
    """

    __tablename__ = "flood_telemetry"

    __table_args__ = (
        Index("ix_flood_telemetry_device_time", "device_id", "device_timestamp"),
        Index("ix_flood_telemetry_event_id", "event_id"),
        Index("ix_flood_telemetry_source", "source"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("flood_devices.device_id"), nullable=False
    )
    event_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="iot")
    water_level_m: Mapped[float] = mapped_column(Float, nullable=False)
    flow_velocity_ms: Mapped[float] = mapped_column(Float, nullable=False)
    device_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry = mapped_column(Geometry(geometry_type="POINT", srid=4326), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    processing_status: Mapped[str] = mapped_column(String(20), default="processed")
