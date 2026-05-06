"""Add reddit_comment_url to comment_drafts.

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-05-06
"""

from alembic import op
import sqlalchemy as sa

revision = "i9j0k1l2m3n4"
down_revision = None  # standalone — apply manually
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comment_drafts",
        sa.Column("reddit_comment_url", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comment_drafts", "reddit_comment_url")
