"""add_trial_conversion_intelligence_tables

Creates:
- trial_signals table (engagement signal collection)
- trial_scores table (deterministic scoring snapshots)
- trial_failures table (expired trial classification)
- trial_sales_summaries table (cached AI sales briefings)
- trial_intelligence_events table (audit trail)

Revision ID: tci01
Revises: byoa01_add_avatar_drafts
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "tci01"
down_revision = "byoa01_add_avatar_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. trial_signals
    op.create_table(
        "trial_signals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("signal_type", sa.String(50), nullable=False),
        sa.Column("signal_category", sa.String(30), nullable=False),
        sa.Column("signal_value", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trial_signals_client_created", "trial_signals", ["client_id", "created_at"])
    op.create_index("ix_trial_signals_client_category", "trial_signals", ["client_id", "signal_category"])

    # 2. trial_scores
    op.create_table(
        "trial_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversion_score", sa.Integer, nullable=False),
        sa.Column("priority_score", sa.Integer, nullable=False),
        sa.Column("opportunity_value_cents", sa.Integer, nullable=False),
        sa.Column("recommended_action", sa.Text, nullable=False),
        sa.Column("score_explanation", JSONB, nullable=False),
        sa.Column("signal_snapshot", JSONB, nullable=False),
        sa.Column("lifecycle_state", sa.String(20), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("conversion_score >= 0 AND conversion_score <= 100", name="ck_trial_scores_conversion_range"),
        sa.CheckConstraint("priority_score >= 0 AND priority_score <= 100", name="ck_trial_scores_priority_range"),
        sa.CheckConstraint("opportunity_value_cents >= 0", name="ck_trial_scores_value_non_negative"),
    )
    op.create_index("ix_trial_scores_client_scored", "trial_scores", ["client_id", sa.text("scored_at DESC")])

    # 3. trial_failures
    op.create_table(
        "trial_failures",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("failure_category", sa.String(30), nullable=False),
        sa.Column("ai_analysis", sa.Text, nullable=True),
        sa.Column("ai_analysis_status", sa.String(10), server_default="pending", nullable=False),
        sa.Column("reactivation_recommended", sa.Boolean, server_default="false"),
        sa.Column("win_back_window_days", sa.Integer, nullable=True),
        sa.Column("next_best_action", sa.Text, nullable=True),
        sa.Column("reactivation_confidence", sa.Float, nullable=True),
        sa.Column("classified_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 4. trial_sales_summaries
    op.create_table(
        "trial_sales_summaries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("score_id", UUID(as_uuid=True), sa.ForeignKey("trial_scores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sales_summary_version", sa.Integer, server_default="1", nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("cached_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # 5. trial_intelligence_events
    op.create_table(
        "trial_intelligence_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(30), nullable=False),
        sa.Column("event_metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_trial_intelligence_events_client_created", "trial_intelligence_events", ["client_id", sa.text("created_at DESC")])


def downgrade() -> None:
    # Drop tables in reverse order (respecting FK dependencies)
    op.drop_index("ix_trial_intelligence_events_client_created", table_name="trial_intelligence_events")
    op.drop_table("trial_intelligence_events")

    op.drop_table("trial_sales_summaries")

    op.drop_table("trial_failures")

    op.drop_index("ix_trial_scores_client_scored", table_name="trial_scores")
    op.drop_table("trial_scores")

    op.drop_index("ix_trial_signals_client_category", table_name="trial_signals")
    op.drop_index("ix_trial_signals_client_created", table_name="trial_signals")
    op.drop_table("trial_signals")
