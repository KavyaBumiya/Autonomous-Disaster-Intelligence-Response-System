"""weather_readings.humidity_pct + pressure_hpa

The storm occurrence model is fitted on mean sea-level pressure, the classic
cyclone signal, and was previously denied it because the poller stored neither
pressure nor humidity. Storing them is what makes those features usable at all:
a model fed a variable the runtime cannot read would return None on every call.

Both columns are nullable with no default, so pre-existing rows read as NULL
(missing) rather than as a plausible-looking 1013 hPa / 50% — the model declines
to score on a missing feature instead of being fed an invented value.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "weather_readings",
        sa.Column("humidity_pct", sa.Float(), nullable=True),
    )
    op.add_column(
        "weather_readings",
        sa.Column("pressure_hpa", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("weather_readings", "pressure_hpa")
    op.drop_column("weather_readings", "humidity_pct")