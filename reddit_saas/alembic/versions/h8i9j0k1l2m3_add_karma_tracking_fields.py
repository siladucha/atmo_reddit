"""Add karma tracking fields to post_drafts and comment_drafts.

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-05-06

PostDraft gains:
- reddit_native_id (for matching with Reddit API)
- reddit_score (post karma)
- reddit_upvote_ratio
- reddit_num_comments
- is_deleted / deleted_detected_at
- last_karma_check_at

CommentDraft gains:
- last_karma_check_at (to avoid re-checking too frequently)

Indexes:
- ix_post_drafts_status
- ix_post_drafts_avatar_status
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "h8i9j0k1l2m3"
down_revision = ("a7b8c9d0e1f2", "g7h8i9j0k1l2")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostDraft new columns
    op.add_column("post_drafts", sa.Column("reddit_native_id", sa.String(255), nullable=True))
    op.add_column("post_drafts", sa.Column("reddit_score", sa.Integer(), nullable=True))
    op.add_column("post_drafts", sa.Column("reddit_upvote_ratio", sa.Float(), nullable=True))
    op.add_column("post_drafts", sa.Column("reddit_num_comments", sa.Integer(), nullable=True))
    op.add_column(
        "post_drafts",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("post_drafts", sa.Column("deleted_detected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("post_drafts", sa.Column("last_karma_check_at", sa.DateTime(timezone=True), nullable=True))

    # PostDraft indexes
    op.create_index("ix_post_drafts_status", "post_drafts", ["status"])
    op.create_index("ix_post_drafts_avatar_status", "post_drafts", ["avatar_id", "status"])

    # CommentDraft new column
    op.add_column("comment_drafts", sa.Column("last_karma_check_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # CommentDraft
    op.drop_column("comment_drafts", "last_karma_check_at")

    # PostDraft indexes
    op.drop_index("ix_post_drafts_avatar_status", table_name="post_drafts")
    op.drop_index("ix_post_drafts_status", table_name="post_drafts")

    # PostDraft columns
    op.drop_column("post_drafts", "last_karma_check_at")
    op.drop_column("post_drafts", "deleted_detected_at")
    op.drop_column("post_drafts", "is_deleted")
    op.drop_column("post_drafts", "reddit_num_comments")
    op.drop_column("post_drafts", "reddit_upvote_ratio")
    op.drop_column("post_drafts", "reddit_score")
    op.drop_column("post_drafts", "reddit_native_id")
