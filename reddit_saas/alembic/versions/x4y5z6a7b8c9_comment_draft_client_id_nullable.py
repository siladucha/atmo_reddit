"""comment_draft_client_id_nullable

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'x4y5z6a7b8c9'
down_revision: Union[str, None] = 'w3x4y5z6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'comment_drafts',
        'client_id',
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill NULLs before making NOT NULL again
    op.execute("UPDATE comment_drafts SET client_id = (SELECT id FROM clients LIMIT 1) WHERE client_id IS NULL")
    op.alter_column(
        'comment_drafts',
        'client_id',
        existing_type=sa.UUID(),
        nullable=False,
    )
