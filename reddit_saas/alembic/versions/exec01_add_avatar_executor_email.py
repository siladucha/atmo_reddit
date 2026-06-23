"""Add executor_email and executor_email_verified to avatars

Revision ID: exec01
Revises: srp02
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "exec01"
down_revision = "srp02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("avatars", sa.Column("executor_email", sa.String(255), nullable=True))
    op.add_column(
        "avatars",
        sa.Column("executor_email_verified", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("avatars", "executor_email_verified")
    op.drop_column("avatars", "executor_email")
