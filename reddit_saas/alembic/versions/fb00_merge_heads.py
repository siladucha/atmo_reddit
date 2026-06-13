"""Merge all current heads into a single revision.

Revision ID: fb00
Revises: a3b4c5d6e7f8, a4b5c6d7e8f9, aa1b2c3d4e5f, epg2_01
Create Date: 2026-06-08
"""

from alembic import op

revision = "fb00"
down_revision = ("a3b4c5d6e7f8", "a4b5c6d7e8f9", "aa1b2c3d4e5f", "epg2_01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
