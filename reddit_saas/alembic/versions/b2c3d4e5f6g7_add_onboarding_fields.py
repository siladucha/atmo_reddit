"""add onboarding fields to clients

Revision ID: b2c3d4e5f6g7
Revises: cal01
Create Date: 2026-06-15 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6g7"
down_revision: str = "cal01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: skip columns that already exist
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='clients' AND column_name='current_onboarding_step'"
    ))
    if not result.fetchone():
        op.add_column("clients", sa.Column("current_onboarding_step", sa.Integer(), server_default="0", nullable=False))

    result = conn.execute(sa.text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='clients' AND column_name='onboarding_completed_at'"
    ))
    if not result.fetchone():
        op.add_column("clients", sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("clients", "onboarding_completed_at")
    op.drop_column("clients", "current_onboarding_step")
