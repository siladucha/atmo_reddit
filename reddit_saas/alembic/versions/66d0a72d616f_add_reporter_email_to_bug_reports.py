"""add_reporter_email_to_bug_reports

Revision ID: 66d0a72d616f
Revises: 692e77190ace
Create Date: 2026-07-23 14:35:30.714970
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision: str = '66d0a72d616f'
down_revision: Union[str, None] = '692e77190ace'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bug_reports', sa.Column('reporter_email', sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column('bug_reports', 'reporter_email')
