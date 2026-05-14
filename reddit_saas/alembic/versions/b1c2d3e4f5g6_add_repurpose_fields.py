"""Add repurpose scraping fields: subreddits.last_repurpose_scraped_at.

Revision ID: b1c2d3e4f5g6
Revises: a0b1c2d3e4f5
Create Date: 2026-05-14

Adds:
- subreddits.last_repurpose_scraped_at (nullable DateTime) — tracks last repurpose scrape per subreddit
"""

revision = "b1c2d3e4f5g6"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "subreddits",
        sa.Column("last_repurpose_scraped_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subreddits", "last_repurpose_scraped_at")
