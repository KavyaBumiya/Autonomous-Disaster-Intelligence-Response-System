"""evidence_tables — external_observations + evidence (Phase 7)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_observations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("observation_type", sa.String(length=40), nullable=False),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("value", JSONB(), nullable=True),
        sa.Column("unit", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_external_observations_source_time",
        "external_observations",
        ["source", "retrieved_at"],
    )
    op.create_index(
        "ix_external_observations_type", "external_observations", ["observation_type"]
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "incident_id",
            sa.String(length=36),
            sa.ForeignKey("incidents.id"),
            nullable=True,
        ),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("observation_type", sa.String(length=40), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_evidence_incident_id", "evidence", ["incident_id"])
    op.create_index("ix_evidence_source", "evidence", ["source"])


def downgrade() -> None:
    op.drop_index("ix_evidence_source", table_name="evidence")
    op.drop_index("ix_evidence_incident_id", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_external_observations_type", table_name="external_observations")
    op.drop_index("ix_external_observations_source_time", table_name="external_observations")
    op.drop_table("external_observations")
