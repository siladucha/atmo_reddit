"""Add avatar_id, thread_id, subreddit_name to ai_usage_log

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-05-07 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "k1l2m3n4o5p6"
down_revision = "j0k1l2m3n4o5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_usage_log", sa.Column("avatar_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ai_usage_log", sa.Column("thread_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("ai_usage_log", sa.Column("subreddit_name", sa.String(255), nullable=True))

    op.create_foreign_key(
        "fk_ai_usage_log_avatar_id", "ai_usage_log", "avatars", ["avatar_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_ai_usage_log_thread_id", "ai_usage_log", "reddit_threads", ["thread_id"], ["id"]
    )

    # Indexes for efficient querying
    op.create_index("ix_ai_usage_log_avatar_id", "ai_usage_log", ["avatar_id"])
    op.create_index("ix_ai_usage_log_subreddit_name", "ai_usage_log", ["subreddit_name"])
    op.create_index("ix_ai_usage_log_created_at", "ai_usage_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_log_created_at", table_name="ai_usage_log")
    op.drop_index("ix_ai_usage_log_subreddit_name", table_name="ai_usage_log")
    op.drop_index("ix_ai_usage_log_avatar_id", table_name="ai_usage_log")
    op.drop_constraint("fk_ai_usage_log_thread_id", "ai_usage_log", type_="foreignkey")
    op.drop_constraint("fk_ai_usage_log_avatar_id", "ai_usage_log", type_="foreignkey")
    op.drop_column("ai_usage_log", "subreddit_name")
    op.drop_column("ai_usage_log", "thread_id")
    op.drop_column("ai_usage_log", "avatar_id")
