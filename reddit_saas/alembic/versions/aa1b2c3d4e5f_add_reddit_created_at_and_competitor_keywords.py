"""Add reddit_created_at to threads + competitor keyword category support.

Revision ID: aa1b2c3d4e5f
Revises: 6da36db9c7c4
Create Date: 2026-05-30

Addresses Tzvi's UX feedback:
- Thread date visibility (reddit_created_at stores actual Reddit post date)
- Competitor keywords (no schema change needed — JSONB already supports arbitrary keys)
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "aa1b2c3d4e5f"
down_revision = "6da36db9c7c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add reddit_created_at — the actual Reddit post creation time
    op.add_column(
        "reddit_threads",
        sa.Column("reddit_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index for filtering stale threads (older than N days)
    op.create_index(
        "ix_reddit_threads_reddit_created_at",
        "reddit_threads",
        ["reddit_created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_reddit_threads_reddit_created_at", table_name="reddit_threads")
    op.drop_column("reddit_threads", "reddit_created_at")
