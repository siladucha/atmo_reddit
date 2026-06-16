"""add client_action_log table

Revision ID: cal01
Revises: n0t1f1c4t10ns
Create Date: 2026-06-15 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "cal01"
down_revision: str = "n0t1f1c4t10ns"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Idempotent: skip if table already exists
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name='client_action_log'"
    ))
    if result.fetchone():
        return

    op.create_table(
        "client_action_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("action_type", sa.String(50), nullable=False, index=True),
        sa.Column(
            "triggered_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id"),
            nullable=True,
        ),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_client_action_log_client_type_time",
        "client_action_log",
        ["client_id", "action_type", sa.text("triggered_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_client_action_log_client_type_time", table_name="client_action_log")
    op.drop_table("client_action_log")
