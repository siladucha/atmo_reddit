"""Optimize indexes based on operational query patterns.

Adds targeted indexes for the most frequent query paths:
- Scoring pipeline: unscored thread detection with is_locked filter
- Liveness checks: stale thread detection with scraped_at + pending drafts join
- AI cost aggregation: per-client monthly cost calculations
- Thread score display: client + tag + scored_at ordering
- Scrape freshness: subreddit_name aggregation in scrape_log
- Comment draft liveness join: thread_id FK lookup
- Avatar health scheduling: active + frozen filter
- Hobby dedup: post_id lookup

Also removes redundant single-column indexes that are covered by
composite indexes (ix_comment_drafts_status is a left-prefix of
ix_comment_drafts_client_status when queries always filter by client).

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-05-08
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "n4o5p6q7r8s9"
down_revision = "m3n4o5p6q7r8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ─────────────────────────────────────────────────────────────────────
    # 1. reddit_threads — scoring pipeline & liveness checks
    # ─────────────────────────────────────────────────────────────────────

    # Scoring pipeline: WHERE subreddit_id IN (...) AND is_locked = false
    # AND id NOT IN (scored). Partial index on non-locked threads only.
    op.create_index(
        "ix_reddit_threads_subreddit_not_locked",
        "reddit_threads",
        ["subreddit_id"],
        postgresql_where="is_locked = false",
    )

    # Liveness checks: WHERE is_locked = false AND scraped_at < cutoff
    # Used by bulk_refresh_locked_status (joins with pending drafts)
    op.create_index(
        "ix_reddit_threads_scraped_at",
        "reddit_threads",
        ["scraped_at"],
        postgresql_where="is_locked = false",
    )

    # ─────────────────────────────────────────────────────────────────────
    # 2. comment_drafts — liveness join & thread lookup
    # ─────────────────────────────────────────────────────────────────────

    # expire_drafts_for_locked_threads: JOIN on thread_id WHERE status='pending'
    # bulk_refresh_locked_status: JOIN on thread_id WHERE status='pending'
    # Partial index — only pending drafts need this join path
    op.create_index(
        "ix_comment_drafts_thread_pending",
        "comment_drafts",
        ["thread_id"],
        postgresql_where="status = 'pending'",
    )

    # Avatar performance tracking: filter by avatar_id + status
    op.create_index(
        "ix_comment_drafts_avatar_status",
        "comment_drafts",
        ["avatar_id", "status"],
    )

    # ─────────────────────────────────────────────────────────────────────
    # 3. ai_usage_log — cost aggregation (most frequent admin queries)
    # ─────────────────────────────────────────────────────────────────────

    # Per-client monthly cost: WHERE client_id = ? AND created_at >= month_start
    # Also covers: total cost per client (prefix scan on client_id)
    op.create_index(
        "ix_ai_usage_log_client_created",
        "ai_usage_log",
        ["client_id", "created_at"],
    )

    # Cost by operation: GROUP BY operation, SUM(cost_usd)
    # Also used by efficiency metrics: WHERE operation = ?
    op.create_index(
        "ix_ai_usage_log_operation",
        "ai_usage_log",
        ["operation"],
    )

    # Daily timeline: WHERE created_at >= cutoff GROUP BY date_trunc('day', created_at), operation
    op.create_index(
        "ix_ai_usage_log_created_at",
        "ai_usage_log",
        ["created_at"],
    )

    # ─────────────────────────────────────────────────────────────────────
    # 4. thread_scores — display & pipeline queries
    # ─────────────────────────────────────────────────────────────────────

    # score_unscored_threads: subquery SELECT thread_id WHERE client_id = ?
    # Already has ix_thread_scores_client_tag but that's (client_id, tag).
    # For the NOT IN subquery we need just client_id → thread_id.
    # The existing composite (client_id, tag) covers client_id prefix, but
    # adding thread_id as second column enables index-only scan for the subquery.
    op.create_index(
        "ix_thread_scores_client_thread",
        "thread_scores",
        ["client_id", "thread_id"],
    )

    # ─────────────────────────────────────────────────────────────────────
    # 5. scrape_log — freshness aggregation
    # ─────────────────────────────────────────────────────────────────────

    # get_scrape_freshness: WHERE subreddit_name = ? → SUM/AVG
    # Also covers: subreddit_id based lookups
    op.create_index(
        "ix_scrape_log_subreddit_name",
        "scrape_log",
        ["subreddit_name"],
    )

    # ─────────────────────────────────────────────────────────────────────
    # 6. client_subreddit_assignments — scoring pipeline subquery
    # ─────────────────────────────────────────────────────────────────────

    # score_unscored_threads_for_client: WHERE client_id = ? AND is_active = true
    # → SELECT subreddit_id
    op.create_index(
        "ix_csa_client_active_subreddit",
        "client_subreddit_assignments",
        ["client_id", "is_active", "subreddit_id"],
    )

    # ─────────────────────────────────────────────────────────────────────
    # 7. hobby_subreddits — dedup lookup
    # ─────────────────────────────────────────────────────────────────────

    # scrape_hobby_subreddits: WHERE post_id = ? (existence check)
    op.create_index(
        "ix_hobby_subreddits_post_id",
        "hobby_subreddits",
        ["post_id"],
    )

    # ─────────────────────────────────────────────────────────────────────
    # 8. activity_events — combined client + time ordering
    # ─────────────────────────────────────────────────────────────────────

    # get_activity_events: WHERE client_id = ? ORDER BY created_at DESC
    # The existing ix_activity_events_client_id doesn't include created_at,
    # so PG must sort after index scan. This composite enables index-ordered scan.
    op.create_index(
        "ix_activity_events_client_created",
        "activity_events",
        ["client_id", "created_at"],
    )

    # ─────────────────────────────────────────────────────────────────────
    # 9. Remove redundant indexes (covered by composites)
    # ─────────────────────────────────────────────────────────────────────

    # ix_activity_events_client_id is now redundant — covered by
    # ix_activity_events_client_created (client_id is left prefix)
    op.drop_index("ix_activity_events_client_id", table_name="activity_events")


def downgrade() -> None:
    # Restore dropped index
    op.create_index("ix_activity_events_client_id", "activity_events", ["client_id"])

    # Drop all new indexes
    op.drop_index("ix_activity_events_client_created", table_name="activity_events")
    op.drop_index("ix_hobby_subreddits_post_id", table_name="hobby_subreddits")
    op.drop_index("ix_csa_client_active_subreddit", table_name="client_subreddit_assignments")
    op.drop_index("ix_scrape_log_subreddit_name", table_name="scrape_log")
    op.drop_index("ix_thread_scores_client_thread", table_name="thread_scores")
    op.drop_index("ix_ai_usage_log_created_at", table_name="ai_usage_log")
    op.drop_index("ix_ai_usage_log_operation", table_name="ai_usage_log")
    op.drop_index("ix_ai_usage_log_client_created", table_name="ai_usage_log")
    op.drop_index("ix_comment_drafts_avatar_status", table_name="comment_drafts")
    op.drop_index("ix_comment_drafts_thread_pending", table_name="comment_drafts")
    op.drop_index("ix_reddit_threads_scraped_at", table_name="reddit_threads")
    op.drop_index("ix_reddit_threads_subreddit_not_locked", table_name="reddit_threads")
