"""Add karma_snapshots table for time-series outcome tracking.

Creates karma_snapshots table — stores periodic karma/reply/deletion
snapshots for posted comments at 4h, 24h, 48h intervals.
Foundation for the Feedback Layer (outcomes → EPG re-evaluation, 
Discovery hypothesis validation, strategy confidence updates).

Revision ID: fb01
Revises: pd01
Create Date: 2026-06-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "fb01"
down_revision = "fb00"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "karma_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("comment_draft_id", UUID(as_uuid=True), sa.ForeignKey("comment_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("karma_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("check_window", sa.String(10), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("karma_delta", sa.Integer(), nullable=True),
        sa.Column("subreddit", sa.String(255), nullable=True),
    )

    # Indexes for common access patterns
    op.create_index("ix_karma_snapshots_draft_checked", "karma_snapshots", ["comment_draft_id", "checked_at"])
    op.create_index("ix_karma_snapshots_avatar_checked", "karma_snapshots", ["avatar_id", "checked_at"])
    op.create_index("ix_karma_snapshots_window", "karma_snapshots", ["check_window", "checked_at"])
    op.create_index("ix_karma_snapshots_subreddit_checked", "karma_snapshots", ["subreddit", "checked_at"])


def downgrade() -> None:
    op.drop_index("ix_karma_snapshots_subreddit_checked", table_name="karma_snapshots")
    op.drop_index("ix_karma_snapshots_window", table_name="karma_snapshots")
    op.drop_index("ix_karma_snapshots_avatar_checked", table_name="karma_snapshots")
    op.drop_index("ix_karma_snapshots_draft_checked", table_name="karma_snapshots")
    op.drop_table("karma_snapshots")
