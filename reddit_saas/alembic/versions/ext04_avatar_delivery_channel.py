"""Add delivery_channel to avatars

Revision ID: ext04
Revises: ext03
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "ext04"
down_revision = "raa01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatars",
        sa.Column("delivery_channel", sa.String(20), server_default="email", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("avatars", "delivery_channel")
