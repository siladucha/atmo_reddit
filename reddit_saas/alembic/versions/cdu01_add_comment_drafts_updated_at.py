"""add updated_at to comment_drafts

Revision ID: cdu01
Revises: exv01
Create Date: 2026-07-05
"""
from alembic import op
import sqlalchemy as sa


revision = "cdu01"
down_revision = "exv01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comment_drafts",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("comment_drafts", "updated_at")
