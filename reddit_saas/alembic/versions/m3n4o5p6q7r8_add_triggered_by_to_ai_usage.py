"""Add triggered_by column to ai_usage_log.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_usage_log",
        sa.Column("triggered_by", sa.String(100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_usage_log", "triggered_by")
