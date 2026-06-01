"""Add autopilot_enabled to clients table.

When enabled, generated drafts are auto-approved without human review.
Used for local end-to-end testing and trusted clients.

Revision ID: ap02
Revises: ap01
Create Date: 2026-06-01
"""
from alembic import op
import sqlalchemy as sa

revision = "ap02"
down_revision = "ap01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clients",
        sa.Column("autopilot_enabled", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("clients", "autopilot_enabled")
