"""Shared subreddit registry migration.

Creates subreddits, client_subreddit_assignments, and thread_scores tables.
Migrates data from client_subreddits and reddit_threads to the new schema.
Drops scoring columns from reddit_threads and updates scrape_log.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-05-20 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "e5f6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ──────────────────────────────────────────────────────────────────────
    # Step 1: Create new tables
    # ──────────────────────────────────────────────────────────────────────

    # subreddits table
    op.create_table(
        "subreddits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("subreddit_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_scraped_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_subreddits_lower_name ON subreddits (lower(subreddit_name))"
    )

    # client_subreddit_assignments table
    op.create_table(
        "client_subreddit_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("subreddit_id", UUID(as_uuid=True), sa.ForeignKey("subreddits.id"), nullable=False),
        sa.Column("type", sa.String(50), server_default="'professional'"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", "subreddit_id", name="uq_client_subreddit_assignment"),
    )

    # thread_scores table
    op.create_table(
        "thread_scores",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("reddit_threads.id"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False),
        sa.Column("tag", sa.String(50), nullable=True),
        sa.Column("alert", sa.Boolean(), server_default="false"),
        sa.Column("relevance", sa.Integer(), nullable=True),
        sa.Column("quality", sa.Integer(), nullable=True),
        sa.Column("strategic", sa.Integer(), nullable=True),
        sa.Column("composite", sa.Integer(), nullable=True),
        sa.Column("intent", sa.String(100), nullable=True),
        sa.Column("scoring_reasoning", sa.Text(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("thread_id", "client_id", name="uq_thread_client_score"),
    )
    op.create_index("ix_thread_scores_client_tag", "thread_scores", ["client_id", "tag"])

    # ──────────────────────────────────────────────────────────────────────
    # Step 2: Populate subreddits from existing client_subreddits
    # ──────────────────────────────────────────────────────────────────────

    op.execute(
        """
        INSERT INTO subreddits (id, subreddit_name, is_active, created_at, last_scraped_at)
        SELECT gen_random_uuid(), sub_name, bool_or(is_active), min(created_at), max(last_scraped_at)
        FROM (
            SELECT DISTINCT ON (lower(subreddit_name))
                subreddit_name AS sub_name, is_active, created_at, last_scraped_at
            FROM client_subreddits
            ORDER BY lower(subreddit_name), is_active DESC, created_at ASC
        ) deduped
        GROUP BY sub_name
        """
    )

    # ──────────────────────────────────────────────────────────────────────
    # Step 3: Populate client_subreddit_assignments from client_subreddits
    # ──────────────────────────────────────────────────────────────────────

    op.execute(
        """
        INSERT INTO client_subreddit_assignments (id, client_id, subreddit_id, type, is_active, created_at)
        SELECT gen_random_uuid(), cs.client_id, s.id, cs.type, cs.is_active, cs.created_at
        FROM client_subreddits cs
        JOIN subreddits s ON lower(s.subreddit_name) = lower(cs.subreddit_name)
        """
    )

    # ──────────────────────────────────────────────────────────────────────
    # Step 4: Add subreddit_id to reddit_threads and populate
    # ──────────────────────────────────────────────────────────────────────

    op.add_column(
        "reddit_threads",
        sa.Column("subreddit_id", UUID(as_uuid=True), sa.ForeignKey("subreddits.id"), nullable=True),
    )

    # Populate subreddit_id from matching subreddits
    op.execute(
        """
        UPDATE reddit_threads rt
        SET subreddit_id = s.id
        FROM subreddits s
        WHERE lower(s.subreddit_name) = lower(rt.subreddit)
        """
    )

    # Create missing subreddit records for orphaned threads
    op.execute(
        """
        INSERT INTO subreddits (id, subreddit_name, is_active, created_at)
        SELECT gen_random_uuid(), rt.subreddit, false, now()
        FROM reddit_threads rt
        WHERE rt.subreddit_id IS NULL
        AND NOT EXISTS (SELECT 1 FROM subreddits s WHERE lower(s.subreddit_name) = lower(rt.subreddit))
        GROUP BY rt.subreddit
        """
    )

    # Re-run the update for newly created records
    op.execute(
        """
        UPDATE reddit_threads rt
        SET subreddit_id = s.id
        FROM subreddits s
        WHERE lower(s.subreddit_name) = lower(rt.subreddit)
        AND rt.subreddit_id IS NULL
        """
    )

    # Make subreddit_id NOT NULL now that all rows are populated
    op.alter_column("reddit_threads", "subreddit_id", nullable=False)

    # ──────────────────────────────────────────────────────────────────────
    # Step 5: Migrate scoring data from reddit_threads to thread_scores
    # ──────────────────────────────────────────────────────────────────────

    op.execute(
        """
        INSERT INTO thread_scores (id, thread_id, client_id, tag, alert, relevance, quality, strategic, composite, intent, scoring_reasoning, scored_at)
        SELECT gen_random_uuid(), rt.id, rt.client_id, rt.tag, rt.alert, rt.relevance, rt.quality, rt.strategic, rt.composite, rt.intent, rt.scoring_reasoning, rt.created_at
        FROM reddit_threads rt
        WHERE rt.tag IS NOT NULL
        """
    )

    # ──────────────────────────────────────────────────────────────────────
    # Step 6: Drop old columns and update constraints
    # ──────────────────────────────────────────────────────────────────────

    # Drop scoring columns from reddit_threads
    op.drop_column("reddit_threads", "client_id")
    op.drop_column("reddit_threads", "tag")
    op.drop_column("reddit_threads", "alert")
    op.drop_column("reddit_threads", "relevance")
    op.drop_column("reddit_threads", "quality")
    op.drop_column("reddit_threads", "strategic")
    op.drop_column("reddit_threads", "composite")
    op.drop_column("reddit_threads", "intent")
    op.drop_column("reddit_threads", "scoring_reasoning")

    # Drop old unique index on client_subreddits
    op.execute("DROP INDEX IF EXISTS uq_client_subreddits_active_name")

    # Make scrape_log.client_id nullable and add subreddit_id FK
    op.alter_column("scrape_log", "client_id", nullable=True)
    op.add_column(
        "scrape_log",
        sa.Column("subreddit_id", UUID(as_uuid=True), sa.ForeignKey("subreddits.id"), nullable=True),
    )


def downgrade() -> None:
    # Remove subreddit_id from scrape_log
    op.drop_column("scrape_log", "subreddit_id")

    # Restore scrape_log.client_id to NOT NULL
    op.alter_column("scrape_log", "client_id", nullable=False)

    # Recreate the old unique index on client_subreddits
    op.execute(
        "CREATE UNIQUE INDEX uq_client_subreddits_active_name "
        "ON client_subreddits (lower(subreddit_name)) "
        "WHERE is_active = true"
    )

    # Re-add scoring columns to reddit_threads
    op.add_column("reddit_threads", sa.Column("scoring_reasoning", sa.Text(), nullable=True))
    op.add_column("reddit_threads", sa.Column("intent", sa.String(100), nullable=True))
    op.add_column("reddit_threads", sa.Column("composite", sa.Integer(), nullable=True))
    op.add_column("reddit_threads", sa.Column("strategic", sa.Integer(), nullable=True))
    op.add_column("reddit_threads", sa.Column("quality", sa.Integer(), nullable=True))
    op.add_column("reddit_threads", sa.Column("relevance", sa.Integer(), nullable=True))
    op.add_column("reddit_threads", sa.Column("alert", sa.Boolean(), server_default="false"))
    op.add_column("reddit_threads", sa.Column("tag", sa.String(50), nullable=True))
    op.add_column("reddit_threads", sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=True))

    # Remove subreddit_id from reddit_threads
    op.drop_column("reddit_threads", "subreddit_id")

    # Drop new tables (in reverse dependency order)
    op.drop_index("ix_thread_scores_client_tag", table_name="thread_scores")
    op.drop_table("thread_scores")
    op.drop_table("client_subreddit_assignments")
    op.execute("DROP INDEX IF EXISTS uq_subreddits_lower_name")
    op.drop_table("subreddits")
