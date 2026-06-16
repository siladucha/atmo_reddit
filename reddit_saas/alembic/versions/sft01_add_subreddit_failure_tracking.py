"""Add consecutive failure tracking to subreddits

Auto-disables subreddits after N consecutive scrape failures.
Prevents wasting Reddit API calls on permanently broken subreddits
(403 private, invalid names, redirects).

Revision ID: sft01
Revises: cps01
Create Date: 2026-06-16

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "sft01"
down_revision = "cps01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subreddits",
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "subreddits",
        sa.Column("disabled_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "subreddits",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subreddits", "disabled_at")
    op.drop_column("subreddits", "disabled_reason")
    op.drop_column("subreddits", "consecutive_failures")
