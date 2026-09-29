"""iot flood devices + telemetry

Registers IoT flood-monitoring devices and stores their normalized telemetry.
Separate from weather_readings (which is polled from Open-Meteo) and from
external_observations (which is for non-domain feeds).

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
# `sa.dialects.postgresql` is not reachable through a bare `import sqlalchemy as
# sa` -- the dialect submodule has to be imported explicitly or the JSONB
# reference below raises AttributeError and takes the whole migration down.
from sqlalchemy.dialects import postgresql

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "flood_devices",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("device_type", sa.String(40), server_default="flood_sensor"),
        sa.Column("status", sa.String(20), server_default="active"),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("geometry", Geometry(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column("token_hash", sa.String(128), nullable=True),
        sa.Column("battery_pct", sa.Float(), nullable=True),
        sa.Column("signal_strength", sa.Float(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("device_id", name="uq_flood_devices_device_id"),
    )
    op.create_index("ix_flood_devices_status", "flood_devices", ["status"])
    op.create_index("ix_flood_devices_last_seen", "flood_devices", ["last_seen_at"])

    op.create_table(
        "flood_telemetry",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(80), nullable=True),
        sa.Column("source", sa.String(20), server_default="iot"),
        sa.Column("water_level_m", sa.Float(), nullable=False),
        sa.Column("flow_velocity_ms", sa.Float(), nullable=False),
        sa.Column("device_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("geometry", Geometry(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column("risk_level", sa.String(20), nullable=True),
        sa.Column("risk_score", sa.Float(), nullable=True),
        sa.Column("processing_status", sa.String(20), server_default="processed"),
        sa.ForeignKeyConstraint(["device_id"], ["flood_devices.device_id"]),
    )
    op.create_index(
        "ix_flood_telemetry_device_time", "flood_telemetry",
        ["device_id", "device_timestamp"],
    )
    op.create_index("ix_flood_telemetry_event_id", "flood_telemetry", ["event_id"])
    op.create_index("ix_flood_telemetry_source", "flood_telemetry", ["source"])


def downgrade() -> None:
    op.drop_table("flood_telemetry")
    op.drop_table("flood_devices")
