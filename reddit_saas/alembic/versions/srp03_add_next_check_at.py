"""Add next_check_at to subreddit_risk_profiles for adaptive refresh.

Revision ID: srp03
Revises: cdu01
Create Date: 2026-07-06
"""
from alembic import op
import sqlalchemy as sa

revision = "srp03"
down_revision = "cdu01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subreddit_risk_profiles",
        sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subreddit_risk_profiles", "next_check_at")
