"""schema_v3 — zone priority/victim aggregates + incident victim fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision    = "0004"
down_revision = "0003"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # zones: Decision Engine writes priority + victim rollup
    op.add_column("zones", sa.Column("priority_score", sa.Float(), nullable=True,
                                      server_default="0"))
    op.add_column("zones", sa.Column("victim_count", sa.Integer(), nullable=True,
                                      server_default="0"))

    # incidents: victim detection results (CV agent)
    op.add_column("incidents", sa.Column("victim_count", sa.Integer(),
                                          nullable=False, server_default="0"))
    op.add_column("incidents", sa.Column("victim_confidence", sa.Float(),
                                          nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("incidents", "victim_confidence")
    op.drop_column("incidents", "victim_count")
    op.drop_column("zones", "victim_count")
    op.drop_column("zones", "priority_score")
