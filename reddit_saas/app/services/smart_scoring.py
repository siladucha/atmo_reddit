"""Smart Scoring — avatar-centric thread selection for scoring.

Instead of scoring ALL unscored threads for a client (expensive, wasteful),
this service scores only threads that a specific avatar can actually engage with,
limited by the avatar's daily budget.

Key insight: if an avatar can post 3 comments today, we only need to score
~9 threads (budget × 3) to give the LLM enough to choose from.

Flow:
1. Check avatar budget (daily limit - already posted today)
2. Determine available subreddits (based on phase + avatar config)
3. Pull fresh threads from those subreddits, ranked by engagement
4. Score only TOP-N threads (N = remaining_budget × multiplier)
5. Return scored "engage" threads ready for generation

This reduces scoring calls from 300+/day to 10-30/day per avatar.
"""

from app.logging_config import get_logger
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.models.subreddit_karma import SubredditKarma
from app.services.phase import (
    MAX_COMMENTS_PER_DAY_PHASE1,
    MAX_COMMENTS_PER_DAY_PHASE2,
    MAX_COMMENTS_PER_DAY_PHASE3,
)

logger = get_logger(__name__)

# How many threads to score per remaining budget slot.
# budget_remaining × MULTIPLIER = threads to score.
# 3 gives enough variety for LLM to pick from without waste.
BUDGET_MULTIPLIER = 3

# Hard cap: never score more than this in one call, regardless of budget.
HARD_CAP = 15

# Minimum engagement (upvotes) for a thread to be worth scoring.
MIN_UPS_THRESHOLD = 3

# Maximum thread age for scoring consideration.
MAX_AGE_HOURS = 48

# Minimum estimated comments for a thread to be interesting.
MIN_COMMENTS_ESTIMATE = 2


@dataclass
class SmartScoreResult:
    """Result of smart scoring for an avatar."""

    avatar_id: uuid.UUID
    avatar_username: str
    client_id: uuid.UUID

    # Budget info
    daily_limit: int = 0
    used_today: int = 0
    remaining_budget: int = 0

    # Scoring results
    threads_considered: int = 0
    threads_scored: int = 0
    engage_threads: list = field(default_factory=list)  # ThreadScore objects
    monitor_threads: list = field(default_factory=list)
    skip_threads: list = field(default_factory=list)

    # Status
    status: str = "ok"  # ok | budget_exhausted | no_threads | frozen | excluded
    message: str = ""

    @property
    def engage_count(self) -> int:
        return len(self.engage_threads)

    def to_dict(self) -> dict:
        return {
            "avatar_id": str(self.avatar_id),
            "avatar_username": self.avatar_username,
            "client_id": str(self.client_id),
            "daily_limit": self.daily_limit,
            "used_today": self.used_today,
            "remaining_budget": self.remaining_budget,
            "threads_considered": self.threads_considered,
            "threads_scored": self.threads_scored,
            "engage_count": self.engage_count,
            "monitor_count": len(self.monitor_threads),
            "skip_count": len(self.skip_threads),
            "status": self.status,
            "message": self.message,
        }


def get_avatar_daily_limit(avatar: Avatar) -> int:
    """Get the daily comment limit based on avatar's warming phase."""
    phase = avatar.warming_phase
    if phase == 0:
        return 0  # Mentor — excluded from pipelines
    elif phase == 1:
        # CQS lowest gets reduced limit
        if avatar.cqs_level == "lowest":
            return 1
        return MAX_COMMENTS_PER_DAY_PHASE1
    elif phase == 2:
        return MAX_COMMENTS_PER_DAY_PHASE2
    elif phase == 3:
        return MAX_COMMENTS_PER_DAY_PHASE3
    return 0


def get_avatar_used_today(db: Session, avatar: Avatar) -> int:
    """Count comments already created/approved/posted today for this avatar."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    count = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(["approved", "posted", "pending"]),
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    )
    return count or 0


def get_avatar_available_subreddit_names(
    db: Session, avatar: Avatar, client: Client
) -> list[str]:
    """Get subreddit names this avatar can post to based on phase.

    Phase 1: hobby subreddits only
    Phase 2: hobby + business (professional) subreddits
    Phase 3: hobby + business + all client-assigned subreddits
    """
    phase = avatar.warming_phase

    hobby_subs = []
    raw = avatar.hobby_subreddits or []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name:
                hobby_subs.append(name.lower())

    business_subs = []
    raw_biz = avatar.business_subreddits or []
    if isinstance(raw_biz, list):
        for item in raw_biz:
            if isinstance(item, dict):
                name = item.get("subreddit") or item.get("name") or ""
            else:
                name = str(item)
            name = name.strip().replace("r/", "")
            if name:
                business_subs.append(name.lower())

    if phase == 1:
        return hobby_subs

    if phase == 2:
        return list(set(hobby_subs + business_subs))

    # Phase 3: all client subreddits + hobby + business
    client_sub_names = (
        db.query(Subreddit.subreddit_name)
        .join(
            ClientSubredditAssignment,
            ClientSubredditAssignment.subreddit_id == Subreddit.id,
        )
        .filter(
            ClientSubredditAssignment.client_id == client.id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    client_subs = [row[0].lower() for row in client_sub_names]

    return list(set(hobby_subs + business_subs + client_subs))


def get_candidate_threads(
    db: Session,
    avatar: Avatar,
    client: Client,
    available_subreddit_names: list[str],
    limit: int,
) -> list[RedditThread]:
    """Pull fresh, high-engagement threads from avatar's available subreddits.

    Filters:
    - Not locked
    - Fresh (< MAX_AGE_HOURS)
    - Minimum engagement (ups >= MIN_UPS_THRESHOLD)
    - Not already scored for this client
    - From subreddits the avatar can post to

    Ordered by: ups DESC (best engagement first)
    """
    freshness_cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)

    # Get subreddit IDs matching the available names
    subreddit_ids_query = (
        db.query(Subreddit.id)
        .filter(sa_func.lower(Subreddit.subreddit_name).in_(available_subreddit_names))
    )
    subreddit_ids = [row[0] for row in subreddit_ids_query.all()]

    if not subreddit_ids:
        return []

    # Already scored thread IDs for this client
    scored_thread_ids = (
        db.query(ThreadScore.thread_id)
        .filter(ThreadScore.client_id == client.id)
    )

    # Pull candidates
    # NOTE: Image-only posts (empty post_body) are excluded — LLM cannot
    # see images and would score/generate nonsensical content. Revisit when
    # multimodal LLM support is added.
    threads = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit_id.in_(subreddit_ids),
            RedditThread.is_locked.is_(False),
            RedditThread.scraped_at >= freshness_cutoff,
            RedditThread.ups >= MIN_UPS_THRESHOLD,
            ~RedditThread.id.in_(scored_thread_ids),
            RedditThread.post_body.isnot(None),
            sa_func.length(RedditThread.post_body) > 20,
        )
        .order_by(RedditThread.ups.desc())
        .limit(limit)
        .all()
    )

    return threads


def smart_score_for_avatar(
    db: Session,
    avatar: Avatar,
    client: Client,
    *,
    force: bool = False,
) -> SmartScoreResult:
    """Score threads intelligently for a specific avatar.

    This is the main entry point. It:
    1. Checks if avatar can post (not frozen, not mentor, has budget)
    2. Determines available subreddits based on phase
    3. Pulls candidate threads ranked by engagement
    4. Scores only what's needed (budget × multiplier)
    5. Returns actionable results

    Args:
        db: Database session.
        avatar: The avatar to find threads for.
        client: The client context.
        force: If True, score even if budget is exhausted (for preview).

    Returns:
        SmartScoreResult with scored threads and budget info.
    """
    from app.services.scoring import score_threads_batch

    result = SmartScoreResult(
        avatar_id=avatar.id,
        avatar_username=avatar.reddit_username,
        client_id=client.id,
    )

    # --- Guard checks ---
    if avatar.is_frozen:
        result.status = "frozen"
        result.message = f"Avatar is frozen: {avatar.freeze_reason or 'no reason'}"
        return result

    if avatar.warming_phase == 0:
        result.status = "excluded"
        result.message = "Mentor avatars are excluded from automated pipelines"
        return result

    if getattr(avatar, "pool", "b2b") not in ("b2b", "b2c"):
        result.status = "excluded"
        result.message = f"Avatar pool '{avatar.pool}' excluded from automated pipelines"
        return result

    if avatar.health_status in ("shadowbanned", "suspended"):
        result.status = "excluded"
        result.message = f"Avatar health: {avatar.health_status}"
        return result

    # --- Budget calculation ---
    daily_limit = get_avatar_daily_limit(avatar)
    used_today = get_avatar_used_today(db, avatar)
    remaining = max(0, daily_limit - used_today)

    result.daily_limit = daily_limit
    result.used_today = used_today
    result.remaining_budget = remaining

    if remaining == 0 and not force:
        result.status = "budget_exhausted"
        result.message = f"Daily budget exhausted ({used_today}/{daily_limit})"
        return result

    # --- Determine how many threads to score ---
    budget_for_scoring = remaining if not force else max(remaining, 3)
    threads_to_score = min(budget_for_scoring * BUDGET_MULTIPLIER, HARD_CAP)

    # --- Get available subreddits ---
    available_subs = get_avatar_available_subreddit_names(db, avatar, client)
    if not available_subs:
        result.status = "no_threads"
        result.message = "No subreddits available for this avatar's phase"
        return result

    # --- Pull candidate threads ---
    candidates = get_candidate_threads(
        db, avatar, client, available_subs, limit=threads_to_score
    )
    result.threads_considered = len(candidates)

    if not candidates:
        result.status = "no_threads"
        result.message = (
            f"No fresh threads found in {len(available_subs)} subreddits "
            f"(min {MIN_UPS_THRESHOLD} ups, < {MAX_AGE_HOURS}h old)"
        )
        return result

    # --- Score via LLM (batch) ---
    logger.info(
        "smart_score: avatar=%s, phase=%d, budget=%d/%d, "
        "scoring %d threads from %d available subs",
        avatar.reddit_username,
        avatar.warming_phase,
        remaining,
        daily_limit,
        len(candidates),
        len(available_subs),
    )

    scores = score_threads_batch(db, candidates, client)
    result.threads_scored = len(scores)

    # --- Categorize results ---
    for score in scores:
        if score.tag == "engage":
            result.engage_threads.append(score)
        elif score.tag == "monitor":
            result.monitor_threads.append(score)
        else:
            result.skip_threads.append(score)

    # --- Status ---
    if result.engage_count > 0:
        result.status = "ok"
        result.message = (
            f"Found {result.engage_count} engage threads "
            f"(scored {result.threads_scored} from {result.threads_considered} candidates)"
        )
    else:
        result.status = "no_threads"
        result.message = (
            f"No engage threads found (scored {result.threads_scored}, "
            f"all monitor/skip)"
        )

    logger.info(
        "smart_score result: avatar=%s → %d engage, %d monitor, %d skip "
        "(from %d scored, %d considered)",
        avatar.reddit_username,
        result.engage_count,
        len(result.monitor_threads),
        len(result.skip_threads),
        result.threads_scored,
        result.threads_considered,
    )

    return result
