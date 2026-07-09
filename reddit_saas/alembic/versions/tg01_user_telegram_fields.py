"""Add telegram notification fields to users.

Revision ID: tg01
Revises: srp03
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa


revision = "tg01"
down_revision = "srp03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("telegram_chat_id", sa.String(100), nullable=True))
    op.add_column("users", sa.Column("telegram_connected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("telegram_notifications_level", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "telegram_notifications_level")
    op.drop_column("users", "telegram_connected_at")
    op.drop_column("users", "telegram_chat_id")
