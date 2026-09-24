"""schema_v2 — Groq integration, audit logs, missing fields
Revision ID: 0003
Revises: 0002
Create Date: 2026-09-22
"""
from alembic import op
import sqlalchemy as sa

revision    = "0003"
down_revision = "0002"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── zones: soft-delete flag ──────────────────────────────────────────
    op.add_column("zones", sa.Column("deleted", sa.Boolean(), nullable=True,
                                      server_default="false"))

    # ── incidents: timestamps and Groq fields ────────────────────────────
    op.add_column("incidents", sa.Column("polled_at",
                  sa.DateTime(timezone=True), nullable=True))
    op.add_column("incidents", sa.Column("groq_summary",
                  sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("groq_explanation",
                  sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("priority_band",
                  sa.String(20), nullable=True, server_default="LOW"))

    # ── reports: Groq parse fields ───────────────────────────────────────
    op.add_column("reports", sa.Column("groq_parsed_hazard",
                  sa.String(50), nullable=True))
    op.add_column("reports", sa.Column("groq_parsed_urgency",
                  sa.String(20), nullable=True))
    op.add_column("reports", sa.Column("groq_people_estimated",
                  sa.Integer(), nullable=True))
    op.add_column("reports", sa.Column("groq_condition",
                  sa.String(50), nullable=True))

    # ── audit_logs: human approval trail ────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id",          sa.String(36),  primary_key=True),
        sa.Column("decision_id", sa.String(36),  nullable=True),
        sa.Column("action_id",   sa.String(36),
                  sa.ForeignKey("actions.id"), nullable=True),
        sa.Column("event_type",  sa.String(60),  nullable=False),
        sa.Column("actor_id",    sa.String(36),  nullable=True),
        sa.Column("actor_role",  sa.String(30),  nullable=True),
        sa.Column("recommended_by", sa.String(80), nullable=True),
        sa.Column("payload",     sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("note",        sa.Text(),      nullable=True),
        sa.Column("created_at",  sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_action_id",  "audit_logs", ["action_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])

    # ── groq_logs: AI call telemetry ─────────────────────────────────────
    op.create_table(
        "groq_logs",
        sa.Column("id",             sa.String(36), primary_key=True),
        sa.Column("call_id",        sa.String(36), nullable=False),
        sa.Column("task_type",      sa.String(40), nullable=False),
        sa.Column("model",          sa.String(60), nullable=False),
        sa.Column("prompt_template", sa.String(40), nullable=True),
        sa.Column("input_tokens",   sa.Integer(),  nullable=True),
        sa.Column("output_tokens",  sa.Integer(),  nullable=True),
        sa.Column("latency_ms",     sa.Float(),    nullable=True),
        sa.Column("success",        sa.Boolean(),  nullable=True, server_default="true"),
        sa.Column("error",          sa.Text(),     nullable=True),
        sa.Column("tool_calls",     sa.dialects.postgresql.JSONB, nullable=True),
        sa.Column("created_at",     sa.DateTime(timezone=True),
                  server_default=sa.func.now()),
    )
    op.create_index("ix_groq_logs_task_type",  "groq_logs", ["task_type"])
    op.create_index("ix_groq_logs_created_at", "groq_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("groq_logs")
    op.drop_table("audit_logs")
    op.drop_column("reports",   "groq_condition")
    op.drop_column("reports",   "groq_people_estimated")
    op.drop_column("reports",   "groq_parsed_urgency")
    op.drop_column("reports",   "groq_parsed_hazard")
    op.drop_column("incidents", "priority_band")
    op.drop_column("incidents", "groq_explanation")
    op.drop_column("incidents", "groq_summary")
    op.drop_column("incidents", "polled_at")
    op.drop_column("zones",     "deleted")
