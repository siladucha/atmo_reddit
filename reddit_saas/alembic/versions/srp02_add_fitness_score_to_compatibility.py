"""add_fitness_score_to_avatar_subreddit_compatibility

Adds fitness_score (Integer 0-100, nullable) and fitness_computed_at
(DateTime(tz), nullable) columns to avatar_subreddit_compatibility table
for the Subreddit Risk Profile fitness gate system.

Revision ID: srp02
Revises: srp01
Create Date: 2026-06-23
"""

from alembic import op
import sqlalchemy as sa

revision = "srp02"
down_revision = "srp01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatar_subreddit_compatibility",
        sa.Column("fitness_score", sa.Integer, nullable=True),
    )
    op.add_column(
        "avatar_subreddit_compatibility",
        sa.Column("fitness_computed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("avatar_subreddit_compatibility", "fitness_computed_at")
    op.drop_column("avatar_subreddit_compatibility", "fitness_score")
