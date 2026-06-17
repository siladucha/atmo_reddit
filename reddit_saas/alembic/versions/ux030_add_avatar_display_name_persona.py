"""Add avatar display_name and persona_bio for client-facing UI.

Revision ID: b1c2d3e4f5g6
Revises: (head)
Create Date: 2026-06-16

These fields support the UX Brief v2 requirement: clients see a persona
display name and one-line bio instead of the Reddit username and raw karma.
"""

from alembic import op
import sqlalchemy as sa


revision = "ux030_display"
down_revision = "sft01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("avatars", sa.Column("display_name", sa.String(100), nullable=True))
    op.add_column("avatars", sa.Column("persona_bio", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("avatars", "persona_bio")
    op.drop_column("avatars", "display_name")
