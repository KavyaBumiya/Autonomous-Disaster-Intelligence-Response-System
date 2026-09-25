"""gis_infrastructure — OSM/Overpass disaster-relevant infrastructure (Phase 3)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from geoalchemy2 import Geometry

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "infrastructure",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("osm_type", sa.String(length=10), nullable=False),
        sa.Column("osm_id", sa.BigInteger(), nullable=False),
        sa.Column("category", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("geometry", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("tags", JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("zone_id", sa.String(length=36), sa.ForeignKey("zones.id"), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_infrastructure_osm", "infrastructure", ["osm_type", "osm_id"])
    op.create_index("ix_infrastructure_category", "infrastructure", ["category"])
    # GIST spatial index: GeoAlchemy2 creates idx_infrastructure_geometry
    # automatically for the Geometry column — no explicit index here.


def downgrade() -> None:
    op.drop_index("ix_infrastructure_category", table_name="infrastructure")
    op.drop_table("infrastructure")  # auto spatial index dropped with the table
