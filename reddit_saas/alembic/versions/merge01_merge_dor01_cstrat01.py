"""Merge dor01 and cstrat01 heads

Revision ID: merge01
Revises: dor01, cstrat01
Create Date: 2026-06-24
"""
from alembic import op

revision = "merge01"
down_revision = ("dor01", "cstrat01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
