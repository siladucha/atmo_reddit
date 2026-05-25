"""merge_heads_for_epg_slots

Revision ID: 6da36db9c7c4
Revises: a1b2c3d4e5f8, a2b3c4d5e6f7, c2d3e4f5g6h7
Create Date: 2026-05-25 09:41:49.115589
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = '6da36db9c7c4'
down_revision: Union[str, None] = ('a1b2c3d4e5f8', 'a2b3c4d5e6f7', 'c2d3e4f5g6h7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
