"""Allow warming_phase=0 for Mentor avatars.

Revision ID: y5z6a7b8c9d0
Revises: x4y5z6a7b8c9
Create Date: 2026-05-12

Mentor phase (0) means the avatar is excluded from all pipelines.
These are pre-warmed high-karma accounts used for reputation lending,
not for automated comment generation.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "y5z6a7b8c9d0"
down_revision = "x4y5z6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema change needed — warming_phase is Integer, already accepts 0.
    # This migration exists as documentation that phase=0 is now a valid state.
    # Add a CHECK constraint for clarity (optional, informational).
    op.execute(
        "ALTER TABLE avatars DROP CONSTRAINT IF EXISTS ck_avatars_warming_phase_range"
    )
    op.execute(
        "ALTER TABLE avatars ADD CONSTRAINT ck_avatars_warming_phase_range "
        "CHECK (warming_phase >= 0 AND warming_phase <= 3)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE avatars DROP CONSTRAINT IF EXISTS ck_avatars_warming_phase_range"
    )
