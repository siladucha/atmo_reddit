"""merge_heads_before_execution_tasks

Revision ID: 994620feea1e
Revises: ep01, ux030_display
Create Date: 2026-06-20 15:28:20.405081
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = '994620feea1e'
down_revision: Union[str, None] = ('ep01', 'ux030_display')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
