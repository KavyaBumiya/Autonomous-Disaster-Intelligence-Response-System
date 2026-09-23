"""schema_v1 — Phase 1 additions (additive only, no breaking changes)

Adds: users table, social_media_polls, audio_uploads,
      Phase 1 columns on reports (source, trust_score, suppressed, social_post_id).

Revision ID: 0002
Revises: 0001
Create Date: 2024-01-02 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(100), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
    )

    # ── social_media_polls ───────────────────────────────────
    op.create_table(
        "social_media_polls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("hashtag", sa.String(100), nullable=False),
        sa.Column("api_source", sa.String(30), nullable=False),
        sa.Column("posts_fetched", sa.Integer, default=0),
        sa.Column("posts_stored", sa.Integer, default=0),
        sa.Column("posts_filtered", sa.Integer, default=0),
        sa.Column("polled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── audio_uploads ────────────────────────────────────────
    op.create_table(
        "audio_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("report_id", sa.String(36), sa.ForeignKey("reports.id"), nullable=False),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=True),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("whisper_model", sa.String(20), default="base"),
        sa.Column("transcription_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── New columns on reports (all nullable/defaulted — no existing row breaks) ──
    op.add_column("reports", sa.Column("source", sa.String(30), nullable=True, server_default="citizen_text"))
    op.add_column("reports", sa.Column("trust_score", sa.Float, nullable=True))
    op.add_column("reports", sa.Column("suppressed", sa.Boolean, nullable=True, server_default="false"))
    op.add_column("reports", sa.Column("social_post_id", sa.String(80), nullable=True))

    # FK from actions.approved_by → users.id (add after users table exists)
    op.add_column("actions", sa.Column("approved_by", sa.String(36), nullable=True))


def downgrade() -> None:
    op.drop_column("actions", "approved_by")
    op.drop_column("reports", "social_post_id")
    op.drop_column("reports", "suppressed")
    op.drop_column("reports", "trust_score")
    op.drop_column("reports", "source")
    op.drop_table("audio_uploads")
    op.drop_table("social_media_polls")
    op.drop_table("users")
