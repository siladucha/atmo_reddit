"""Add daily_vibe and daily_vibe_date to subreddits table.

Revision ID: vibe01
Revises: bill01
Create Date: 2026-07-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision = "vibe01"
down_revision = "bill01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subreddits", sa.Column("daily_vibe", JSONB, nullable=True))
    op.add_column("subreddits", sa.Column("daily_vibe_date", sa.Date, nullable=True))


def downgrade() -> None:
    op.drop_column("subreddits", "daily_vibe_date")
    op.drop_column("subreddits", "daily_vibe")
