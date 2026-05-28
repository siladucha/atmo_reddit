"""Add avatar pool and industry fields.

Revision ID: a4b5c6d7e8f9
Revises: 6da36db9c7c4
Create Date: 2026-05-28

Pool classifies avatars by operational category (b2b/b2c/mentor/warm).
Industry tags avatars by domain expertise for better persona routing.
"""

from alembic import op
import sqlalchemy as sa

revision = "a4b5c6d7e8f9"
down_revision = "6da36db9c7c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add pool column with default 'b2b'
    op.add_column(
        "avatars",
        sa.Column("pool", sa.String(20), nullable=False, server_default="b2b"),
    )
    # Add industry column (free-text, nullable)
    op.add_column(
        "avatars",
        sa.Column("industry", sa.String(100), nullable=True),
    )

    # Add industry to clients table too (for avatar-client matching)
    op.add_column(
        "clients",
        sa.Column("industry", sa.String(100), nullable=True),
    )

    # Backfill: warming_phase == 0 → pool = 'mentor'
    op.execute(
        "UPDATE avatars SET pool = 'mentor' WHERE warming_phase = 0"
    )
    # Backfill: active avatars with no client_ids → pool = 'warm'
    op.execute(
        "UPDATE avatars SET pool = 'warm' WHERE (client_ids IS NULL OR client_ids = '{}') AND warming_phase != 0"
    )

    # Index for filtering by pool (common admin query)
    op.create_index("ix_avatars_pool", "avatars", ["pool"])


def downgrade() -> None:
    op.drop_index("ix_avatars_pool", table_name="avatars")
    op.drop_column("avatars", "industry")
    op.drop_column("avatars", "pool")
    op.drop_column("clients", "industry")
