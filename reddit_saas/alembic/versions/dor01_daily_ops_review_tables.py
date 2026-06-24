"""daily_ops_review_tables

Creates:
- review_snapshots (immutable data snapshots)
- daily_review_sessions (session lifecycle)
- review_decisions (decisions with follow-up tracking)
- intelligence_reports (immutable report artifacts)

Revision ID: dor01
Revises: audit01
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "dor01"
down_revision = "exec01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. review_snapshots — immutable data frozen at session start
    op.create_table(
        "review_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("health_snapshot_json", JSONB, nullable=False),
        sa.Column("signals_json", JSONB, nullable=False),
        sa.Column("trends_json", JSONB, nullable=False),
        sa.Column("cost_json", JSONB, nullable=False),
        sa.Column("forecast_inputs_json", JSONB, nullable=False),
        sa.Column("source_availability_json", JSONB, nullable=False),
    )
    op.create_index("ix_review_snapshots_created_at", "review_snapshots", ["created_at"])

    # 2. daily_review_sessions — session lifecycle
    op.create_table(
        "daily_review_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("snapshot_id", UUID(as_uuid=True), sa.ForeignKey("review_snapshots.id"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("review_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_duration_sec", sa.Integer(), nullable=True),
        sa.Column("current_section", sa.String(30), nullable=True),
        sa.Column("section_states", JSONB, server_default="{}", nullable=False),
        sa.Column("section_timestamps", JSONB, server_default="{}", nullable=False),
        sa.Column("user_inputs", JSONB, server_default="{}", nullable=False),
        sa.Column("cost_used_usd", sa.Numeric(8, 4), server_default="0", nullable=False),
    )
    op.create_index("ix_daily_review_sessions_date", "daily_review_sessions", ["review_date"])
    op.create_index("ix_daily_review_sessions_user_status", "daily_review_sessions", ["user_id", "status"])

    # 3. review_decisions — max 3 per session, tracked across sessions
    op.create_table(
        "review_decisions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("daily_review_sessions.id"), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("decision_type", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner", sa.String(100), nullable=False),
        sa.Column("deadline", sa.Date(), nullable=True),
        sa.Column("linked_entities", JSONB, nullable=True),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("defer_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_review_decisions_status_date", "review_decisions", ["status", "report_date"])
    op.create_index("ix_review_decisions_session", "review_decisions", ["session_id"])

    # 4. intelligence_reports — immutable report artifacts
    op.create_table(
        "intelligence_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("daily_review_sessions.id"), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("system_state", sa.String(20), nullable=False),
        sa.Column("report_raw", JSONB, nullable=False),
        sa.Column("report_summary", sa.Text(), nullable=True),
        sa.Column("narrative_mode", sa.String(20), server_default="template", nullable=False),
        sa.Column("forecast_accuracy", JSONB, nullable=True),
        sa.Column("overall_confidence", sa.Integer(), server_default="50", nullable=False),
        sa.Column("total_llm_cost_usd", sa.Numeric(8, 4), server_default="0", nullable=False),
    )
    op.create_index("ix_intelligence_reports_date", "intelligence_reports", ["report_date"])


def downgrade() -> None:
    op.drop_table("intelligence_reports")
    op.drop_table("review_decisions")
    op.drop_table("daily_review_sessions")
    op.drop_table("review_snapshots")
