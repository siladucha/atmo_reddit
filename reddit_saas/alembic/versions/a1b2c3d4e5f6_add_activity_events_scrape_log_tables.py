"""Add activity_events, scrape_log tables and last_scraped_at column

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2025-01-15 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "000_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create activity_events table (skip if already exists from initial migration)
    from sqlalchemy import inspect
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if "activity_events" not in existing_tables:
        op.create_table(
            "activity_events",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=True),
            sa.Column("event_type", sa.VARCHAR(50), nullable=False),
            sa.Column("message", sa.TEXT(), nullable=False),
            sa.Column("metadata", postgresql.JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "scrape_log" not in existing_tables:
        # Create scrape_log table
        op.create_table(
            "scrape_log",
            sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
            sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False),
            sa.Column("subreddit_name", sa.VARCHAR(255), nullable=False),
            sa.Column("scraped_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("posts_found", sa.INTEGER(), nullable=False),
            sa.Column("posts_new", sa.INTEGER(), nullable=False),
            sa.Column("errors", sa.TEXT(), nullable=True),
            sa.Column("duration_ms", sa.INTEGER(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )

        # Create composite index on scrape_log
        op.create_index(
            "ix_scrape_log_client_sub_time",
            "scrape_log",
            ["client_id", "subreddit_name", "scraped_at"],
        )

    # Add last_scraped_at column to client_subreddits (if not already there)
    if "client_subreddits" in existing_tables:
        cols = [c["name"] for c in inspector.get_columns("client_subreddits")]
        if "last_scraped_at" not in cols:
            op.add_column(
                "client_subreddits",
                sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
            )


def downgrade() -> None:
    # Remove last_scraped_at column from client_subreddits
    op.drop_column("client_subreddits", "last_scraped_at")

    # Drop scrape_log index and table
    op.drop_index("ix_scrape_log_client_sub_time", table_name="scrape_log")
    op.drop_table("scrape_log")

    # Drop activity_events table
    op.drop_table("activity_events")
