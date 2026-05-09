"""Add avatar health check fields for shadowban detection.

Adds health_status, health_status_changed_at, health_check_details,
consecutive_check_failures, and last_health_check columns to the avatars table.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "p6q7r8s9t0u1"
down_revision = "o5p6q7r8s9t0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatars",
        sa.Column("health_status", sa.String(20), server_default="unknown", nullable=False),
    )
    op.add_column(
        "avatars",
        sa.Column("health_status_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "avatars",
        sa.Column("health_check_details", postgresql.JSONB, nullable=True),
    )
    op.add_column(
        "avatars",
        sa.Column("consecutive_check_failures", sa.Integer, server_default="0", nullable=False),
    )
    op.add_column(
        "avatars",
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("avatars", "last_health_check")
    op.drop_column("avatars", "consecutive_check_failures")
    op.drop_column("avatars", "health_check_details")
    op.drop_column("avatars", "health_status_changed_at")
    op.drop_column("avatars", "health_status")
