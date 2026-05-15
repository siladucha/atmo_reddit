"""Add composite indexes for audit_log, avatar_subreddit_presence, subreddit_karma, scrape_log.

These indexes optimize the 4 most common query patterns that currently cause
sequential scans as data grows:

1. avatar_subreddit_presence: filter by avatar_id + order by last_activity_at DESC
2. subreddit_karma: filter by avatar_id + order by last_updated_at DESC
3. scrape_log: filter by subreddit_id + order by scraped_at DESC
4. audit_log: filter by action + created_at range (system actions without client_id)

Revision ID: a1b2c3d4e5f7
Revises: z6a7b8c9d0e1
Create Date: 2026-05-13
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f7"
down_revision = "z6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. avatar_subreddit_presence: WHERE avatar_id = ? ORDER BY last_activity_at DESC NULLS LAST
    # Covers presence map display sorted by recency per avatar.
    op.create_index(
        "ix_avatar_presence_avatar_activity",
        "avatar_subreddit_presence",
        ["avatar_id", sa.text("last_activity_at DESC NULLS LAST")],
    )

    # 2. subreddit_karma: WHERE avatar_id = ? ORDER BY last_updated_at DESC
    # Covers karma breakdown display sorted by most recently updated.
    op.create_index(
        "ix_subreddit_karma_avatar_updated",
        "subreddit_karma",
        ["avatar_id", sa.text("last_updated_at DESC")],
    )

    # 3. scrape_log: WHERE subreddit_id = ? ORDER BY scraped_at DESC
    # Covers scrape history per subreddit sorted by most recent.
    op.create_index(
        "ix_scrape_log_subreddit_scraped",
        "scrape_log",
        ["subreddit_id", sa.text("scraped_at DESC")],
    )

    # 4. audit_log: WHERE action = ? AND created_at BETWEEN ? AND ? ORDER BY created_at DESC
    # Covers admin audit log page filtered by action + date range (system actions have client_id=NULL).
    op.create_index(
        "ix_audit_log_action_created",
        "audit_log",
        ["action", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_action_created", table_name="audit_log")
    op.drop_index("ix_scrape_log_subreddit_scraped", table_name="scrape_log")
    op.drop_index("ix_subreddit_karma_avatar_updated", table_name="subreddit_karma")
    op.drop_index("ix_avatar_presence_avatar_activity", table_name="avatar_subreddit_presence")
