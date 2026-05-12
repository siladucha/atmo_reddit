"""Add original_ai_draft field to comment_drafts

Preserves the original AI generation before the AI Editor rewrites it.
This allows the self-learning loop to show accurate Before/After pairs:
Before = original generation, After = human-edited version.

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-05-11 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "v2w3x4y5z6a7"
down_revision = "u1v2w3x4y5z6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "comment_drafts",
        sa.Column("original_ai_draft", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("comment_drafts", "original_ai_draft")
