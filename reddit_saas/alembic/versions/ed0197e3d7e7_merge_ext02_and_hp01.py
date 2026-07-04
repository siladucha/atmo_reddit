"""merge ext02 and hp01

Revision ID: ed0197e3d7e7
Revises: ext02, hp01
Create Date: 2026-06-28 20:33:21.305472
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'ed0197e3d7e7'
down_revision: Union[str, None] = ('ext02', 'hp01')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
