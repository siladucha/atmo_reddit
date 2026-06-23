"""Moderation Profiler service — KarmaSnapshot aggregation + pattern detection.

Aggregates historical deletion data from KarmaSnapshot and CommentDraft to build
a ModerationProfile per subreddit. Identifies dangerous hours, classifies
moderator aggressiveness, detects patterns.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8
"""

from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.comment_draft import CommentDraft
from app.models.karma_snapshot import KarmaSnapshot
from app.models.subreddit_daily_stats import SubredditDailyStats
from app.models.thread import RedditThread
from app.services.transparency import record_activity_event

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MODERATION_WINDOW_DAYS = 30
DANGEROUS_HOUR_MULTIPLIER = 2.0
PATTERN_THRESHOLD_PCT = 0.30
MIN_POSTS_FOR_DANGEROUS_HOURS = 10
MIN_POSTS_FOR_CONFIDENCE = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ModerationProfile:
    """Aggregated moderation intelligence for a subreddit."""

    removal_rate: float  # 0.0 - 1.0
    aggressiveness: str  # low | medium | high | extreme
    dangerous_hours: list[int]  # hours (0-23) in dominant timezone
    patterns: list[dict]  # [{"type": "time_of_day", "detail": "14-16", "pct": 0.35}]
    confidence_level: str  # insufficient_data | low | medium | high
    total_posted: int
    total_deleted: int


# ---------------------------------------------------------------------------
# Aggressiveness classification (Req 2.4)
# ---------------------------------------------------------------------------


def _classify_aggressiveness(removal_rate: float) -> str:
    """Classify moderator aggressiveness based on removal rate thresholds.

    low: <10%, medium: 10-25%, high: 25-50%, extreme: >50%
    """
    if removal_rate > 0.50:
        return "extreme"
    elif removal_rate > 0.25:
        return "high"
    elif removal_rate >= 0.10:
        return "medium"
    else:
        return "low"


# ---------------------------------------------------------------------------
# Confidence level (Req 2.5, 2.6)
# ---------------------------------------------------------------------------


def _classify_confidence(total_posted: int) -> str:
    """Classify confidence level based on sample size.

    <5: insufficient_data, 5-9: low, 10+: medium/high
    """
    if total_posted < MIN_POSTS_FOR_CONFIDENCE:
        return "insufficient_data"
    elif total_posted < MIN_POSTS_FOR_DANGEROUS_HOURS:
        return "low"
    elif total_posted < 30:
        return "medium"
    else:
        return "high"


# ---------------------------------------------------------------------------
# Dangerous hours computation (Req 2.3)
# ---------------------------------------------------------------------------


def _compute_dangerous_hours(
    hourly_deletions: dict[int, int],
    overall_removal_rate: float,
    hourly_totals: dict[int, int],
) -> list[int]:
    """Find hours where removal rate exceeds 2x the overall rate.

    Only called when total_posted >= MIN_POSTS_FOR_DANGEROUS_HOURS.
    """
    dangerous = []

    for hour in range(24):
        total_in_hour = hourly_totals.get(hour, 0)
        if total_in_hour == 0:
            continue

        deleted_in_hour = hourly_deletions.get(hour, 0)
        hour_rate = deleted_in_hour / total_in_hour

        if hour_rate > overall_removal_rate * DANGEROUS_HOUR_MULTIPLIER:
            dangerous.append(hour)

    return sorted(dangerous)


# ---------------------------------------------------------------------------
# Pattern detection (Req 2.7)
# ---------------------------------------------------------------------------


def _detect_patterns(
    deleted_hours: list[int],
    total_deleted: int,
) -> list[dict]:
    """Identify patterns where >30% of removals come from the same cause.

    Currently detects time_of_day patterns (consecutive hours with high removal).
    """
    if total_deleted == 0:
        return []

    patterns: list[dict] = []

    # Time-of-day pattern: group deletions by 2-hour windows
    window_counts: Counter = Counter()
    for hour in deleted_hours:
        # Map to 2-hour window start
        window_start = (hour // 2) * 2
        window_counts[window_start] += 1

    for window_start, count in window_counts.most_common():
        pct = count / total_deleted
        if pct >= PATTERN_THRESHOLD_PCT:
            window_end = window_start + 2
            patterns.append({
                "type": "time_of_day",
                "detail": f"{window_start:02d}-{window_end:02d}",
                "pct": round(pct, 2),
            })

    return patterns


# ---------------------------------------------------------------------------
# Core function: compute_moderation_profile (Req 2.1-2.7)
# ---------------------------------------------------------------------------


def compute_moderation_profile(
    db: Session, subreddit_name: str
) -> ModerationProfile:
    """Aggregate KarmaSnapshot + CommentDraft deletion data for 30-day window.

    Steps:
    1. Query comment_drafts WHERE subreddit matches AND status="posted"
       AND posted_at >= 30 days ago
    2. Join with latest KarmaSnapshot per draft for is_deleted status
    3. Compute removal_rate = deleted / total
    4. If total >= 10: compute hourly distribution, find dangerous hours (>2x avg)
    5. Classify aggressiveness by thresholds
    6. Identify patterns (>30% of removals from same cause)
    """
    window_start = datetime.now(timezone.utc) - timedelta(days=MODERATION_WINDOW_DAYS)

    logger.info(
        "MODERATION_PROFILER | action=compute | subreddit=r/%s | window_start=%s",
        subreddit_name,
        window_start.isoformat(),
    )

    # Step 1: Query posted comments in this subreddit within the 30-day window.
    # CommentDraft links to RedditThread which has the subreddit name.
    # We use CommentDraft.is_deleted which is updated by snapshot_comment_outcomes.
    posted_drafts = (
        db.query(
            CommentDraft.id,
            CommentDraft.posted_at,
            CommentDraft.is_deleted,
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            sa.func.lower(RedditThread.subreddit) == subreddit_name.lower(),
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= window_start,
            CommentDraft.posted_at.isnot(None),
        )
        .all()
    )

    total_posted = len(posted_drafts)
    total_deleted = sum(1 for d in posted_drafts if d.is_deleted)

    # Compute removal rate (Req 2.2)
    removal_rate = total_deleted / total_posted if total_posted > 0 else 0.0

    # Classify confidence (Req 2.5, 2.6)
    confidence_level = _classify_confidence(total_posted)

    # Classify aggressiveness (Req 2.4)
    aggressiveness = _classify_aggressiveness(removal_rate)

    # Compute dangerous hours (Req 2.3) — only if >= 10 posts
    dangerous_hours: list[int] = []
    patterns: list[dict] = []

    if total_posted >= MIN_POSTS_FOR_DANGEROUS_HOURS:
        # Build hourly distributions
        hourly_totals: Counter = Counter()
        hourly_deletions: Counter = Counter()
        deleted_hours_list: list[int] = []

        for draft in posted_drafts:
            if draft.posted_at is not None:
                hour = draft.posted_at.hour
                hourly_totals[hour] += 1
                if draft.is_deleted:
                    hourly_deletions[hour] += 1
                    deleted_hours_list.append(hour)

        # Find dangerous hours (Req 2.3)
        dangerous_hours = _compute_dangerous_hours(
            dict(hourly_deletions), removal_rate, dict(hourly_totals)
        )

        # Detect patterns (Req 2.7)
        patterns = _detect_patterns(deleted_hours_list, total_deleted)

    logger.info(
        "MODERATION_PROFILER | action=compute | subreddit=r/%s | "
        "total_posted=%d | total_deleted=%d | removal_rate=%.3f | "
        "aggressiveness=%s | confidence=%s | dangerous_hours=%s | patterns=%d",
        subreddit_name,
        total_posted,
        total_deleted,
        removal_rate,
        aggressiveness,
        confidence_level,
        dangerous_hours,
        len(patterns),
    )

    return ModerationProfile(
        removal_rate=round(removal_rate, 4),
        aggressiveness=aggressiveness,
        dangerous_hours=dangerous_hours,
        patterns=patterns,
        confidence_level=confidence_level,
        total_posted=total_posted,
        total_deleted=total_deleted,
    )


# ---------------------------------------------------------------------------
# Daily stats computation (Req 6.3, Property 5: Idempotent upsert)
# ---------------------------------------------------------------------------


def compute_daily_stats(db: Session, subreddit_name: str) -> None:
    """Upsert SubredditDailyStats for last 30 days.

    Groups posted comments by date, computes posted vs survived (not deleted),
    and upserts into SubredditDailyStats with ON CONFLICT UPDATE.
    """
    from app.models.subreddit import Subreddit

    window_start = datetime.now(timezone.utc) - timedelta(days=MODERATION_WINDOW_DAYS)

    logger.info(
        "MODERATION_PROFILER | action=compute_daily_stats | subreddit=r/%s",
        subreddit_name,
    )

    # Resolve subreddit_id
    subreddit = (
        db.query(Subreddit)
        .filter(sa.func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit:
        logger.warning(
            "MODERATION_PROFILER | action=compute_daily_stats | "
            "subreddit=r/%s | status=not_found",
            subreddit_name,
        )
        return

    subreddit_id = subreddit.id

    # Query daily aggregates: GROUP BY date(posted_at)
    daily_rows = (
        db.query(
            sa.func.date(CommentDraft.posted_at).label("post_date"),
            sa.func.count(CommentDraft.id).label("comments_posted"),
            sa.func.sum(
                sa.case((CommentDraft.is_deleted.is_(False), 1), else_=0)
            ).label("comments_survived"),
        )
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            sa.func.lower(RedditThread.subreddit) == subreddit_name.lower(),
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= window_start,
            CommentDraft.posted_at.isnot(None),
        )
        .group_by(sa.func.date(CommentDraft.posted_at))
        .all()
    )

    now = datetime.now(timezone.utc)
    upserted_count = 0

    for row in daily_rows:
        post_date = row.post_date
        comments_posted = row.comments_posted or 0
        comments_survived = row.comments_survived or 0

        # Compute removal rate
        removal_rate = (
            1.0 - (comments_survived / comments_posted)
            if comments_posted > 0
            else 0.0
        )

        # Upsert using PostgreSQL INSERT ON CONFLICT UPDATE (Property 5)
        stmt = sa.dialects.postgresql.insert(SubredditDailyStats.__table__).values(
            id=sa.text("gen_random_uuid()"),
            subreddit_id=subreddit_id,
            date=post_date,
            comments_posted=comments_posted,
            comments_survived=comments_survived,
            removal_rate=round(removal_rate, 4),
            computed_at=now,
        )

        stmt = stmt.on_conflict_do_update(
            constraint="uq_sds_subreddit_date",
            set_={
                "comments_posted": stmt.excluded.comments_posted,
                "comments_survived": stmt.excluded.comments_survived,
                "removal_rate": stmt.excluded.removal_rate,
                "computed_at": stmt.excluded.computed_at,
            },
        )

        db.execute(stmt)
        upserted_count += 1

    db.commit()

    logger.info(
        "MODERATION_PROFILER | action=compute_daily_stats | subreddit=r/%s | "
        "days_upserted=%d",
        subreddit_name,
        upserted_count,
    )
