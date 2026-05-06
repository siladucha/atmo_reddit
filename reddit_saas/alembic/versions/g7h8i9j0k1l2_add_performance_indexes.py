"""Add performance indexes for frequently queried columns.

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-06 12:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "g7h8i9j0k1l2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # comment_drafts: filtered by status on every review page load
    op.create_index("ix_comment_drafts_status", "comment_drafts", ["status"])
    # comment_drafts: filtered by client_id + status together
    op.create_index("ix_comment_drafts_client_status", "comment_drafts", ["client_id", "status"])
    # comment_drafts: ordered by created_at desc
    op.create_index("ix_comment_drafts_created_at", "comment_drafts", ["created_at"])

    # reddit_threads: filtered by client_id (most common filter)
    op.create_index("ix_reddit_threads_client_id", "reddit_threads", ["client_id"])
    # reddit_threads: filtered by subreddit_id (FK, but no auto-index in PG)
    op.create_index("ix_reddit_threads_subreddit_id", "reddit_threads", ["subreddit_id"])
    # reddit_threads: ordered by created_at desc on every threads page
    op.create_index("ix_reddit_threads_created_at", "reddit_threads", ["created_at"])

    # activity_events: filtered by event_type + ordered by created_at
    op.create_index("ix_activity_events_type_created", "activity_events", ["event_type", "created_at"])
    # activity_events: filtered by client_id
    op.create_index("ix_activity_events_client_id", "activity_events", ["client_id"])

    # client_subreddits: filtered by client_id + is_active
    op.create_index("ix_client_subreddits_client_active", "client_subreddits", ["client_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_client_subreddits_client_active", table_name="client_subreddits")
    op.drop_index("ix_activity_events_client_id", table_name="activity_events")
    op.drop_index("ix_activity_events_type_created", table_name="activity_events")
    op.drop_index("ix_reddit_threads_created_at", table_name="reddit_threads")
    op.drop_index("ix_reddit_threads_subreddit_id", table_name="reddit_threads")
    op.drop_index("ix_reddit_threads_client_id", table_name="reddit_threads")
    op.drop_index("ix_comment_drafts_created_at", table_name="comment_drafts")
    op.drop_index("ix_comment_drafts_client_status", table_name="comment_drafts")
    op.drop_index("ix_comment_drafts_status", table_name="comment_drafts")
