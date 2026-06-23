"""add_subreddit_risk_profile

Creates:
- subreddit_risk_profiles table (1:1 with subreddits, all JSONB fields)
- subreddit_daily_stats table (daily posting stats per subreddit)
- is_high_risk column on subreddits table

Revision ID: srp01
Revises: audit01
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "srp01"
down_revision = "audit01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. subreddit_risk_profiles
    op.create_table(
        "subreddit_risk_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subreddit_id", UUID(as_uuid=True), sa.ForeignKey("subreddits.id", ondelete="CASCADE"), nullable=False, unique=True),
        # Risk score
        sa.Column("risk_score", sa.Integer, server_default="50", nullable=False),
        sa.Column("risk_score_history", JSONB, server_default="[]", nullable=False),
        # Extracted rules
        sa.Column("extracted_rules", JSONB, server_default="[]", nullable=False),
        sa.Column("extraction_status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("last_rule_extraction_at", sa.DateTime(timezone=True), nullable=True),
        # Moderation profile
        sa.Column("moderation_profile", JSONB, server_default="{}", nullable=False),
        sa.Column("dangerous_hours", JSONB, server_default="[]", nullable=False),
        sa.Column("confidence_level", sa.String(30), server_default="insufficient_data", nullable=False),
        sa.Column("last_profile_computed_at", sa.DateTime(timezone=True), nullable=True),
        # Recommendations
        sa.Column("recommendations", JSONB, server_default="[]", nullable=False),
        sa.Column("dominant_timezone", sa.String(50), server_default="UTC", nullable=False),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        # CHECK constraint on risk_score
        sa.CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_srp_risk_score_range"),
    )
    op.create_index("ix_srp_subreddit_id", "subreddit_risk_profiles", ["subreddit_id"], unique=True)
    op.create_index("ix_srp_risk_score", "subreddit_risk_profiles", ["risk_score"])
    op.create_index("ix_srp_extraction_status", "subreddit_risk_profiles", ["extraction_status"])

    # 2. subreddit_daily_stats
    op.create_table(
        "subreddit_daily_stats",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subreddit_id", UUID(as_uuid=True), sa.ForeignKey("subreddits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("comments_posted", sa.Integer, server_default="0", nullable=False),
        sa.Column("comments_survived", sa.Integer, server_default="0", nullable=False),
        sa.Column("removal_rate", sa.Float, nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("subreddit_id", "date", name="uq_sds_subreddit_date"),
    )
    op.create_index("ix_sds_subreddit_date", "subreddit_daily_stats", ["subreddit_id", "date"])

    # 3. Add is_high_risk to subreddits table
    op.add_column(
        "subreddits",
        sa.Column("is_high_risk", sa.Boolean, server_default="false", nullable=False),
    )


def downgrade() -> None:
    # Remove is_high_risk from subreddits
    op.drop_column("subreddits", "is_high_risk")

    # Drop subreddit_daily_stats
    op.drop_index("ix_sds_subreddit_date", table_name="subreddit_daily_stats")
    op.drop_table("subreddit_daily_stats")

    # Drop subreddit_risk_profiles
    op.drop_index("ix_srp_extraction_status", table_name="subreddit_risk_profiles")
    op.drop_index("ix_srp_risk_score", table_name="subreddit_risk_profiles")
    op.drop_index("ix_srp_subreddit_id", table_name="subreddit_risk_profiles")
    op.drop_table("subreddit_risk_profiles")
