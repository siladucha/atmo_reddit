"""Merge ev01 and incub01 heads.

Revision ID: merge_ev01_incub01
"""
from alembic import op

revision = "merge_ev01_incub01"
down_revision = ("ev01", "incub01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
