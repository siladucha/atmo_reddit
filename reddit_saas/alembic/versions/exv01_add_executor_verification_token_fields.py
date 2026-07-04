"""Add executor_verification_token_hash and executor_verification_token_expires to avatars

Revision ID: exv01
Revises: ab01
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "exv01"
down_revision = "ab01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("avatars", sa.Column("executor_verification_token_hash", sa.String(64), nullable=True))
    op.add_column("avatars", sa.Column("executor_verification_token_expires", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("avatars", "executor_verification_token_expires")
    op.drop_column("avatars", "executor_verification_token_hash")
