"""Add CQS (Contributor Quality Score) fields to avatars

Tracks Reddit's hidden trust classification per avatar.
Levels: lowest, low, moderate, high, highest.
Used to gate avatar usage in pipeline phases.

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-05-11 22:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "w3x4y5z6a7b8"
down_revision = "v2w3x4y5z6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatars",
        sa.Column("cqs_level", sa.String(20), nullable=True),
    )
    op.add_column(
        "avatars",
        sa.Column("cqs_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "avatars",
        sa.Column("cqs_notes", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("avatars", "cqs_notes")
    op.drop_column("avatars", "cqs_checked_at")
    op.drop_column("avatars", "cqs_level")
