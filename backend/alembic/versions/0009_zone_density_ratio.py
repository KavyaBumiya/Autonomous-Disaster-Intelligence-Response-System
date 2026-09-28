"""zones_density_ratio — operator-declared population density

Replaces the Decision Engine's hard-coded neighbourhood lookup, which inferred
population density by substring-matching zone names against a fixed table of
Vadodara localities. Any zone outside that table silently scored a neutral 0.5.

Zones now carry an explicit nullable density_ratio (0-1). NULL means unknown
and is treated as neutral, so the factor is never invented from the name.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "zones",
        sa.Column("density_ratio", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("zones", "density_ratio")
