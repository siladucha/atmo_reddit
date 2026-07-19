"""Add LLM quality monitoring fields to ai_usage_log + quality snapshot table.

Revision ID: lqm01
Revises: vibe01
Create Date: 2026-07-19

Adds:
- quality_outcome to ai_usage_log (success/empty/parse_error/timeout/error/fallback_used)
- retry_count to ai_usage_log
- fallback_model to ai_usage_log (if fallback was used, which model succeeded)
- New table: llm_quality_snapshots (periodic aggregated quality metrics)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "lqm01"
down_revision = "vibe01"
branch_labels = None
depends_on = None


def upgrade():
    # Add quality tracking columns to ai_usage_log
    op.add_column(
        "ai_usage_log",
        sa.Column("quality_outcome", sa.String(30), nullable=True),
    )
    op.add_column(
        "ai_usage_log",
        sa.Column("retry_count", sa.Integer(), nullable=True, server_default="0"),
    )
    op.add_column(
        "ai_usage_log",
        sa.Column("fallback_model", sa.String(255), nullable=True),
    )

    # Index for quality analysis queries
    op.create_index(
        "ix_ai_usage_log_quality_outcome",
        "ai_usage_log",
        ["quality_outcome"],
    )

    # Aggregated quality snapshots — periodic rollups
    op.create_table(
        "llm_quality_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("operation", sa.String(100), nullable=False),
        sa.Column("total_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("empty_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("timeout_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fallback_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_duration_ms", sa.Integer(), nullable=True),
        sa.Column("p95_duration_ms", sa.Integer(), nullable=True),
        sa.Column("avg_output_tokens", sa.Integer(), nullable=True),
        sa.Column("success_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("avg_cost_usd", sa.Numeric(10, 6), nullable=True),
        sa.Column("baseline_success_rate", sa.Numeric(5, 2), nullable=True),
        sa.Column("baseline_avg_duration_ms", sa.Integer(), nullable=True),
        sa.Column("degradation_detected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("degradation_details", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index(
        "ix_llm_quality_snapshots_window",
        "llm_quality_snapshots",
        ["window_start", "model", "operation"],
    )
    op.create_index(
        "ix_llm_quality_snapshots_degradation",
        "llm_quality_snapshots",
        ["degradation_detected", "created_at"],
    )


def downgrade():
    op.drop_table("llm_quality_snapshots")
    op.drop_index("ix_ai_usage_log_quality_outcome", table_name="ai_usage_log")
    op.drop_column("ai_usage_log", "fallback_model")
    op.drop_column("ai_usage_log", "retry_count")
    op.drop_column("ai_usage_log", "quality_outcome")
