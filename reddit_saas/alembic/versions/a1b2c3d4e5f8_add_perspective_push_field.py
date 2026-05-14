"""Add perspective_push field to comment_drafts.

Revision ID: a1b2c3d4e5f8
Revises: a0b1c2d3e4f5
Create Date: 2026-05-14
"""

from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f8"
down_revision = None  # Will be resolved by Alembic chain
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comment_drafts",
        sa.Column("perspective_push", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comment_drafts", "perspective_push")
