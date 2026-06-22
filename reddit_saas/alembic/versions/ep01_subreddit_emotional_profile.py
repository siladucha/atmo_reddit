"""Add subreddit emotional profile columns and compatibility table.

Revision ID: ep01
Revises: n0t1f1c4t10ns
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "ep01"
down_revision = "n0t1f1c4t10ns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add emotional profile columns to subreddits table
    op.add_column("subreddits", sa.Column("emotional_profile", JSONB, nullable=True))
    op.add_column("subreddits", sa.Column("previous_emotional_profile", JSONB, nullable=True))
    op.add_column("subreddits", sa.Column("emotional_profile_analyzed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("subreddits", sa.Column("emotional_profile_error", sa.Text(), nullable=True))

    # Create avatar_subreddit_compatibility table
    op.create_table(
        "avatar_subreddit_compatibility",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subreddit_name", sa.String(255), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("mismatch_reasons", JSONB, server_default="[]"),
        sa.Column("is_stale", sa.Boolean(), server_default="false"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Indexes
    op.create_index(
        "ix_asc_avatar_subreddit",
        "avatar_subreddit_compatibility",
        ["avatar_id", "subreddit_name"],
        unique=True,
    )
    op.create_index(
        "ix_asc_subreddit_score",
        "avatar_subreddit_compatibility",
        ["subreddit_name", "score"],
    )


def downgrade() -> None:
    op.drop_index("ix_asc_subreddit_score")
    op.drop_index("ix_asc_avatar_subreddit")
    op.drop_table("avatar_subreddit_compatibility")
    op.drop_column("subreddits", "emotional_profile_error")
    op.drop_column("subreddits", "emotional_profile_analyzed_at")
    op.drop_column("subreddits", "previous_emotional_profile")
    op.drop_column("subreddits", "emotional_profile")
