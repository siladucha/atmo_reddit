"""Add approval and edit_note fields to strategy_documents

Adds:
- is_approved (bool, default false) — marks strategy as ready for pipeline use
- approved_at (timestamp) — when it was approved
- approved_by_user_id (uuid) — who approved it
- edit_note (text) — optional note when manually editing

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-05-11 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "u1v2w3x4y5z6"
down_revision: Union[str, None] = "t0u1v2w3x4y5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "strategy_documents",
        sa.Column("is_approved", sa.Boolean, nullable=False, server_default="false"),
    )
    op.add_column(
        "strategy_documents",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "strategy_documents",
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "strategy_documents",
        sa.Column("edit_note", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strategy_documents", "edit_note")
    op.drop_column("strategy_documents", "approved_by_user_id")
    op.drop_column("strategy_documents", "approved_at")
    op.drop_column("strategy_documents", "is_approved")
