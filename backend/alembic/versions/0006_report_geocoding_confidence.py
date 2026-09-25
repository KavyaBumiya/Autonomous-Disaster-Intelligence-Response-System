"""report_geocoding_confidence — persist NLP geocoding confidence (Phase 4)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reports",
        sa.Column("geocoding_confidence", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reports", "geocoding_confidence")
