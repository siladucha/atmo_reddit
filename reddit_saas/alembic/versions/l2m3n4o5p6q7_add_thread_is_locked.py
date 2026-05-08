"""Add is_locked field to reddit_threads

Tracks whether a Reddit thread is locked (comments disabled).
Threads can become locked after scraping — this field allows the pipeline
to skip locked threads and avoid wasting LLM resources on un-postable comments.

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-05-08 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "l2m3n4o5p6q7"
down_revision = "k1l2m3n4o5p6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reddit_threads",
        sa.Column("is_locked", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "reddit_threads",
        sa.Column(
            "locked_detected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Partial index: only locked threads (sparse, cheap)
    op.create_index(
        "ix_reddit_threads_is_locked",
        "reddit_threads",
        ["is_locked"],
        postgresql_where=sa.text("is_locked = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_reddit_threads_is_locked", table_name="reddit_threads")
    op.drop_column("reddit_threads", "locked_detected_at")
    op.drop_column("reddit_threads", "is_locked")
