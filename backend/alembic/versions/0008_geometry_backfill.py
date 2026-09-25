"""geometry_backfill — reports/zones geometry from lat/lng (Phase 9)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-25
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE reports SET geometry = "
        "ST_SetSRID(ST_MakePoint(lng, lat), 4326) "
        "WHERE geometry IS NULL AND lat IS NOT NULL AND lng IS NOT NULL"
    )
    op.execute(
        "UPDATE zones SET geometry = "
        "ST_Buffer(ST_SetSRID(ST_MakePoint(centroid_lng, centroid_lat), 4326)::geography, "
        "GREATEST(radius_meters, 50))::geometry "
        "WHERE geometry IS NULL"
    )


def downgrade() -> None:
    # Backfill is additive — clearing geometry would lose nothing (nullable).
    op.execute("UPDATE reports SET geometry = NULL")
    op.execute("UPDATE zones SET geometry = NULL")
