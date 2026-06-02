"""Add performance indexes for avatar list page.

Fixes slow page load for client_manager users:
1. GIN index on avatars.client_ids — speeds up ARRAY ANY() filter for client-scoped users
2. Composite index on comment_drafts(avatar_id, status, created_at) — covers week count queries

Revision ID: perf01
Revises: ap02
Create Date: 2026-06-07
"""
from alembic import op

revision = "perf01"
down_revision = "ap02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GIN index for ARRAY column — supports Avatar.client_ids.any(...) filter
    op.execute(
        "CREATE INDEX ix_avatars_client_ids_gin ON avatars USING GIN (client_ids)"
    )

    # Composite index covering get_avatar_health weekly counts:
    # WHERE avatar_id = ? AND status IN ('approved', 'posted') AND created_at >= ?
    op.create_index(
        "ix_comment_drafts_avatar_status_created",
        "comment_drafts",
        ["avatar_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_comment_drafts_avatar_status_created", table_name="comment_drafts")
    op.drop_index("ix_avatars_client_ids_gin", table_name="avatars")
