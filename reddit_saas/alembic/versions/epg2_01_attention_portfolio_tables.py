"""Add EPG 2.0 Attention Portfolio tables.

Creates:
- opportunities table (scored engagement opportunities per daily run)
- decision_records table (immutable allocation decision log per avatar per day)
- zero_day_reports table (structured reports for zero-action days)
- performance_metrics table (daily per-avatar performance tracking)
- Adds return_weights, brand_mention_cap, max_comments_per_month to clients table

Revision ID: epg2_01
Revises: disc01
Create Date: 2026-06-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "epg2_01"
down_revision = "disc01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. CREATE TABLE opportunities
    op.create_table(
        "opportunities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("decision_date", sa.Date, nullable=False),
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("reddit_threads.id"), nullable=True),
        sa.Column("hobby_post_id", UUID(as_uuid=True), nullable=True),
        sa.Column("subreddit", sa.String(255), nullable=False),
        sa.Column("opportunity_type", sa.String(20), nullable=False, server_default="comment"),
        # Six-dimensional scoring
        sa.Column("visibility_score", sa.Integer, nullable=False),
        sa.Column("competition_score", sa.Integer, nullable=False),
        sa.Column("trust_potential_score", sa.Integer, nullable=False),
        sa.Column("karma_potential_score", sa.Integer, nullable=False),
        sa.Column("risk_score", sa.Integer, nullable=False),
        sa.Column("strategic_alignment_score", sa.Integer, nullable=False),
        sa.Column("composite_score", sa.Integer, nullable=False),
        # Expected return (filled by Return Engine)
        sa.Column("expected_return", JSONB, nullable=True),
        # Lifecycle
        sa.Column("status", sa.String(20), nullable=False, server_default="evaluated"),
        sa.Column("rejection_reason", sa.Text, nullable=True),
        # Outcome tracking (filled by karma feedback loop)
        sa.Column("actual_karma", sa.Integer, nullable=True),
        sa.Column("actual_removal", sa.Boolean, server_default="false"),
        sa.Column("outcome_checked_at", sa.DateTime(timezone=True), nullable=True),
        # Metadata
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # CHECK constraints for score columns (0-100)
        sa.CheckConstraint("visibility_score BETWEEN 0 AND 100", name="ck_opportunity_visibility_score"),
        sa.CheckConstraint("competition_score BETWEEN 0 AND 100", name="ck_opportunity_competition_score"),
        sa.CheckConstraint("trust_potential_score BETWEEN 0 AND 100", name="ck_opportunity_trust_potential_score"),
        sa.CheckConstraint("karma_potential_score BETWEEN 0 AND 100", name="ck_opportunity_karma_potential_score"),
        sa.CheckConstraint("risk_score BETWEEN 0 AND 100", name="ck_opportunity_risk_score"),
        sa.CheckConstraint("strategic_alignment_score BETWEEN 0 AND 100", name="ck_opportunity_strategic_alignment_score"),
        sa.CheckConstraint("composite_score BETWEEN 0 AND 100", name="ck_opportunity_composite_score"),
    )
    op.create_index("ix_opportunities_avatar_date", "opportunities", ["avatar_id", "decision_date"])
    op.create_index("ix_opportunities_status", "opportunities", ["status"])
    op.create_index("ix_opportunities_avatar_date_status", "opportunities", ["avatar_id", "decision_date", "status"])

    # 2. CREATE TABLE decision_records
    op.create_table(
        "decision_records",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("decision_date", sa.Date, nullable=False),
        # State snapshots at decision time
        sa.Column("avatar_state", JSONB, nullable=False),
        sa.Column("community_states", JSONB, nullable=False),
        sa.Column("market_state", JSONB, nullable=False),
        sa.Column("client_state", JSONB, nullable=True),
        # Allocation details
        sa.Column("portfolio_allocation", JSONB, nullable=False),
        sa.Column("budget_available", JSONB, nullable=False),
        sa.Column("budget_consumed", JSONB, nullable=False),
        # Results
        sa.Column("metrics", JSONB, nullable=False),
        sa.Column("zero_day", sa.Boolean, nullable=False, server_default="false"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Constraints
        sa.UniqueConstraint("avatar_id", "decision_date", name="uq_decision_avatar_date"),
    )
    op.create_index("ix_decision_records_avatar_date", "decision_records", ["avatar_id", "decision_date"])

    # 3. CREATE TABLE zero_day_reports
    op.create_table(
        "zero_day_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("report_date", sa.Date, nullable=False),
        sa.Column("reason_code", sa.String(50), nullable=False),
        sa.Column("report_content", JSONB, nullable=False),
        sa.Column("recommendations", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_zero_day_reports_avatar_date", "zero_day_reports", ["avatar_id", "report_date"])

    # 4. CREATE TABLE performance_metrics
    op.create_table(
        "performance_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("metric_date", sa.Date, nullable=False),
        # Core metrics
        sa.Column("return_on_attention", sa.Float, nullable=True),
        sa.Column("risk_adjusted_return", sa.Float, nullable=True),
        sa.Column("portfolio_diversification", sa.Float, nullable=True),
        sa.Column("decision_accuracy", sa.Float, nullable=True),
        sa.Column("opportunity_cost", sa.Float, nullable=True),
        sa.Column("zero_day_rate", sa.Float, nullable=True),
        # Counts
        sa.Column("actions_taken", sa.Integer, nullable=False, server_default="0"),
        sa.Column("karma_gained", sa.Integer, nullable=False, server_default="0"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Constraints
        sa.UniqueConstraint("avatar_id", "metric_date", name="uq_metrics_avatar_date"),
    )
    op.create_index("ix_performance_metrics_avatar_date", "performance_metrics", ["avatar_id", "metric_date"])

    # 5. ALTER TABLE clients — Add EPG 2.0 columns
    op.add_column(
        "clients",
        sa.Column(
            "return_weights",
            JSONB,
            nullable=True,
            server_default='{"karma": 20, "trust": 25, "visibility": 20, "influence": 15, "strategic_value": 20}',
        ),
    )
    op.add_column(
        "clients",
        sa.Column("brand_mention_cap", sa.Integer, nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("max_comments_per_month", sa.Integer, nullable=True),
    )


def downgrade() -> None:
    # Reverse order: drop client columns, then tables

    # 5. DROP client columns
    op.drop_column("clients", "max_comments_per_month")
    op.drop_column("clients", "brand_mention_cap")
    op.drop_column("clients", "return_weights")

    # 4. DROP performance_metrics
    op.drop_index("ix_performance_metrics_avatar_date", table_name="performance_metrics")
    op.drop_table("performance_metrics")

    # 3. DROP zero_day_reports
    op.drop_index("ix_zero_day_reports_avatar_date", table_name="zero_day_reports")
    op.drop_table("zero_day_reports")

    # 2. DROP decision_records
    op.drop_index("ix_decision_records_avatar_date", table_name="decision_records")
    op.drop_table("decision_records")

    # 1. DROP opportunities
    op.drop_index("ix_opportunities_avatar_date_status", table_name="opportunities")
    op.drop_index("ix_opportunities_status", table_name="opportunities")
    op.drop_index("ix_opportunities_avatar_date", table_name="opportunities")
    op.drop_table("opportunities")
