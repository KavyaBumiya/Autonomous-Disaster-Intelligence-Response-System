"""schema_v0 — Phase 0 baseline tables

Revision ID: 0001
Revises:
Create Date: 2024-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable PostGIS
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # zones
    op.create_table(
        "zones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("centroid_lat", sa.Float, nullable=False),
        sa.Column("centroid_lng", sa.Float, nullable=False),
        sa.Column("radius_meters", sa.Float, default=500.0),
        sa.Column("geometry", Geometry("POLYGON", srid=4326), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # reports (Phase 0 columns only)
    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("zone_id", sa.String(36), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column("reporter_id", sa.String(64), nullable=False),
        sa.Column("message_text", sa.Text, nullable=True),
        sa.Column("transcript", sa.Text, nullable=True),
        sa.Column("audio_url", sa.Text, nullable=True),
        sa.Column("location_string", sa.Text, nullable=True),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("geometry", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("disaster_type", sa.String(50), nullable=True),
        sa.Column("nlp_confidence", sa.Float, nullable=True),
        sa.Column("informative_flag", sa.Boolean, nullable=True),
        sa.Column("language_code", sa.String(10), nullable=True),
        sa.Column("nlp_model_version", sa.String(20), default="v0_keyword"),
        sa.Column("device_type", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # incidents
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("zone_id", sa.String(36), sa.ForeignKey("zones.id"), nullable=False),
        sa.Column("disaster_type", sa.String(50), nullable=True),
        sa.Column("severity_score", sa.Float, default=0.0),
        sa.Column("priority_score", sa.Float, default=0.0),
        sa.Column("confidence", sa.Float, default=0.0),
        sa.Column("xai_reasoning", sa.Text, nullable=True),
        sa.Column("status", sa.String(30), default="active"),
        sa.Column("report_count", sa.Integer, default=0),
        sa.Column("avg_trust_score", sa.Float, default=0.0),
        sa.Column("active", sa.Boolean, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # agent_outputs
    op.create_table(
        "agent_outputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_name", sa.String(80), nullable=False),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("output_type", sa.String(30), nullable=False),
        sa.Column("payload", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("confidence", sa.Float, default=0.0),
        sa.Column("reasoning", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # resources
    op.create_table(
        "resources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("capacity", sa.Integer, default=0),
        sa.Column("current_load", sa.Integer, default=0),
        sa.Column("lat", sa.Float, nullable=True),
        sa.Column("lng", sa.Float, nullable=True),
        sa.Column("available", sa.Boolean, default=True),
        sa.Column("assigned_zone_id", sa.String(36), nullable=True),
    )

    # actions
    op.create_table(
        "actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id"), nullable=False),
        sa.Column("zone_id", sa.String(36), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("recommended_by", sa.String(80), default="decision_engine"),
        sa.Column("status", sa.String(30), default="pending_approval"),
        sa.Column("approved_by", sa.String(36), nullable=True),
        sa.Column("priority_score", sa.Float, default=0.0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # weather_readings
    op.create_table(
        "weather_readings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("zone_id", sa.String(36), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("rainfall_mm_hr", sa.Float, default=0.0),
        sa.Column("wind_speed_kmh", sa.Float, default=0.0),
        sa.Column("temperature_c", sa.Float, nullable=True),
        sa.Column("weather_main", sa.String(50), nullable=True),
        sa.Column("weather_description", sa.String(100), nullable=True),
        sa.Column("risk_score", sa.Float, default=0.0),
        sa.Column("polled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # seismic_events
    op.create_table(
        "seismic_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("usgs_id", sa.String(80), unique=True, nullable=False),
        sa.Column("magnitude", sa.Float, nullable=False),
        sa.Column("depth_km", sa.Float, nullable=True),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lng", sa.Float, nullable=False),
        sa.Column("place_description", sa.String(255), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_score", sa.Float, default=0.0),
        sa.Column("polled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("seismic_events")
    op.drop_table("weather_readings")
    op.drop_table("actions")
    op.drop_table("resources")
    op.drop_table("agent_outputs")
    op.drop_table("incidents")
    op.drop_table("reports")
    op.drop_table("zones")
