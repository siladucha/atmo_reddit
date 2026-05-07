"""Add avatar freeze fields.

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-05-07
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: columns may already exist if previously applied manually
    conn = op.get_bind()
    for col_name, col_def in [
        ("is_frozen", sa.Column("is_frozen", sa.Boolean(), server_default="false", nullable=False)),
        ("freeze_reason", sa.Column("freeze_reason", sa.Text(), nullable=True)),
        ("frozen_at", sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True)),
    ]:
        result = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='avatars' AND column_name=:col"
            ),
            {"col": col_name},
        )
        if not result.fetchone():
            op.add_column("avatars", col_def)


def downgrade() -> None:
    op.drop_column("avatars", "frozen_at")
    op.drop_column("avatars", "freeze_reason")
    op.drop_column("avatars", "is_frozen")
