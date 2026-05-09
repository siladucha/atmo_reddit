"""Add avatar_profile_snapshots table.

Stores cached Reddit profile analytics per avatar, updated on demand.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "o5p6q7r8s9t0"
down_revision = "n4o5p6q7r8s9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_profile_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True), nullable=False, index=True),
        # Account metadata
        sa.Column("reddit_username", sa.String(255), nullable=False),
        sa.Column("comment_karma", sa.Integer, default=0, server_default="0"),
        sa.Column("post_karma", sa.Integer, default=0, server_default="0"),
        sa.Column("total_karma", sa.Integer, default=0, server_default="0"),
        sa.Column("account_age_days", sa.Integer, default=0, server_default="0"),
        sa.Column("account_created", sa.DateTime(timezone=True), nullable=True),
        sa.Column("has_verified_email", sa.Boolean, default=False, server_default="false"),
        sa.Column("is_gold", sa.Boolean, default=False, server_default="false"),
        sa.Column("is_mod", sa.Boolean, default=False, server_default="false"),
        sa.Column("icon_url", sa.String(500), nullable=True),
        # Activity patterns
        sa.Column("total_comments", sa.Integer, default=0, server_default="0"),
        sa.Column("total_posts", sa.Integer, default=0, server_default="0"),
        sa.Column("avg_comments_per_week", sa.Float, default=0.0, server_default="0.0"),
        sa.Column("avg_posts_per_week", sa.Float, default=0.0, server_default="0.0"),
        sa.Column("most_active_hour_utc", sa.Integer, nullable=True),
        sa.Column("most_active_day", sa.String(20), nullable=True),
        sa.Column("days_since_last_comment", sa.Integer, nullable=True),
        sa.Column("days_since_last_post", sa.Integer, nullable=True),
        # Content style
        sa.Column("avg_comment_length", sa.Integer, default=0, server_default="0"),
        sa.Column("avg_post_length", sa.Integer, default=0, server_default="0"),
        sa.Column("uses_emoji", sa.Boolean, default=False, server_default="false"),
        sa.Column("uses_links", sa.Boolean, default=False, server_default="false"),
        sa.Column("avg_comment_score", sa.Float, default=0.0, server_default="0.0"),
        sa.Column("avg_post_score", sa.Float, default=0.0, server_default="0.0"),
        sa.Column("top_comment_score", sa.Integer, default=0, server_default="0"),
        sa.Column("top_post_score", sa.Integer, default=0, server_default="0"),
        # Structured JSON data
        sa.Column("subreddits_data", postgresql.JSONB, nullable=True),
        sa.Column("recent_comments_data", postgresql.JSONB, nullable=True),
        sa.Column("recent_posts_data", postgresql.JSONB, nullable=True),
        # Fetch metadata
        sa.Column("fetch_duration_ms", sa.Integer, default=0, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("avatar_profile_snapshots")
