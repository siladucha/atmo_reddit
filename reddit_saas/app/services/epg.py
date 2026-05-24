"""EPG — Daily Avatar Publishing Program.

Generates a daily schedule of comment drafts for an avatar.
Like TV EPG shows what airs and when, avatar EPG shows what to post, where, and when.

Key principles:
- Deduplication: never assign a thread where avatar already has a draft/posted comment
- Phase-aware: Phase 1 = hobby only (no LLM scoring), Phase 2-3 = hobby + business
- Subreddit rotation: round-robin across available subs, not all from one
- Timing slots: randomized intervals throughout the day
- Cost-efficient: hobby threads skip LLM scoring entirely
"""

import logging
import random
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.hobby import HobbySubreddit
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.subreddit import ClientSubredditAssignment, Subreddit
from app.services.phase import (
    MAX_COMMENTS_PER_DAY_PHASE1,
    MAX_COMMENTS_PER_DAY_PHASE2,
    MAX_COMMENTS_PER_DAY_PHASE3,
)
from app.services.sanitize import get_avatar_hobby_subreddits

logger = logging.getLogger(__name__)


# --- Timing ---

# Working hours for posting (Israel time offsets from midnight)
POSTING_WINDOW_START_HOUR = 8   # 08:00
POSTING_WINDOW_END_HOUR = 21    # 21:00
MIN_SLOT_GAP_MINUTES = 45       # Minimum gap between slots
JITTER_MINUTES = 30             # ± randomization per slot


def _generate_time_slots(count: int) -> list[datetime]:
    """Generate randomized posting time slots spread across the day.

    Returns datetime objects for today with randomized times.
    Ensures minimum gap between slots and adds jitter.
    """
    if count <= 0:
        return []

    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Available window in minutes
    window_minutes = (POSTING_WINDOW_END_HOUR - POSTING_WINDOW_START_HOUR) * 60
    # Divide window evenly, then add jitter
    if count == 1:
        base_intervals = [window_minutes // 2]
    else:
        gap = window_minutes // (count + 1)
        gap = max(gap, MIN_SLOT_GAP_MINUTES)
        base_intervals = [gap * (i + 1) for i in range(count)]

    slots = []
    for offset_min in base_intervals:
        jitter = random.randint(-JITTER_MINUTES, JITTER_MINUTES)
        actual_min = POSTING_WINDOW_START_HOUR * 60 + offset_min + jitter
        # Clamp to window
        actual_min = max(POSTING_WINDOW_START_HOUR * 60, min(actual_min, POSTING_WINDOW_END_HOUR * 60))
        slot = today + timedelta(minutes=actual_min)
        slots.append(slot)

    slots.sort()
    return slots


# --- Deduplication ---

def _get_avatar_used_thread_ids(db: Session, avatar: Avatar) -> set[uuid.UUID]:
    """Get all thread IDs where this avatar already has a draft or posted comment."""
    rows = (
        db.query(CommentDraft.thread_id)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.thread_id.isnot(None),
        )
        .all()
    )
    return {row[0] for row in rows if row[0]}


def _get_avatar_used_hobby_post_ids(db: Session, avatar: Avatar) -> set[str]:
    """Get all hobby post IDs where this avatar already has a comment generated."""
    rows = (
        db.query(HobbySubreddit.post_id)
        .filter(
            HobbySubreddit.avatar_username == avatar.reddit_username,
            HobbySubreddit.status.in_(["pending", "approved", "posted"]),
        )
        .all()
    )
    return {row[0] for row in rows if row[0]}


# --- Budget ---

def _get_daily_budget(avatar: Avatar) -> int:
    """Get daily comment budget based on phase."""
    phase = avatar.warming_phase
    if phase == 0:
        return 0
    elif phase == 1:
        if avatar.cqs_level == "lowest":
            return 1
        return MAX_COMMENTS_PER_DAY_PHASE1
    elif phase == 2:
        return MAX_COMMENTS_PER_DAY_PHASE2
    elif phase == 3:
        return MAX_COMMENTS_PER_DAY_PHASE3
    return 0


def _get_used_today(db: Session, avatar: Avatar) -> int:
    """Count drafts already created today for this avatar."""
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        db.query(sa_func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status.in_(["pending", "approved", "posted"]),
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    )
    # Also count hobby comments generated today
    hobby_count = (
        db.query(sa_func.count(HobbySubreddit.id))
        .filter(
            HobbySubreddit.avatar_username == avatar.reddit_username,
            HobbySubreddit.status.in_(["pending", "approved", "posted"]),
            HobbySubreddit.created_at >= today_start,
        )
        .scalar()
    )
    return (count or 0) + (hobby_count or 0)


# --- Thread Selection ---

def _select_hobby_threads(
    db: Session,
    avatar: Avatar,
    count: int,
    used_hobby_ids: set[str],
) -> list[HobbySubreddit]:
    """Select hobby threads with subreddit rotation.

    Picks from different subreddits round-robin style,
    sorted by ups within each subreddit.
    """
    # Get available hobby posts grouped by subreddit
    posts = (
        db.query(HobbySubreddit)
        .filter(
            HobbySubreddit.avatar_username == avatar.reddit_username,
            HobbySubreddit.status == "new",
            HobbySubreddit.ai_comment.is_(None),
            ~HobbySubreddit.post_id.in_(used_hobby_ids) if used_hobby_ids else True,
        )
        .order_by(HobbySubreddit.post_ups.desc().nullslast())
        .all()
    )

    if not posts:
        return []

    # Group by subreddit
    by_sub: dict[str, list[HobbySubreddit]] = defaultdict(list)
    for p in posts:
        by_sub[p.subreddit or "unknown"].append(p)

    # Round-robin selection across subreddits
    selected = []
    sub_names = list(by_sub.keys())
    random.shuffle(sub_names)  # Randomize starting subreddit

    idx = 0
    while len(selected) < count and any(by_sub[s] for s in sub_names):
        sub = sub_names[idx % len(sub_names)]
        if by_sub[sub]:
            selected.append(by_sub[sub].pop(0))
        idx += 1
        # Safety: break if we've cycled through all empty
        if idx > count * len(sub_names):
            break

    return selected[:count]


def _select_business_threads(
    db: Session,
    avatar: Avatar,
    client: Client,
    count: int,
    used_thread_ids: set[uuid.UUID],
) -> list[RedditThread]:
    """Select business/client threads with keyword matching.

    For Phase 2-3: picks threads from business/client subreddits
    that match client keywords, sorted by keyword priority × ups.
    """
    # Get available subreddits for this phase
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

    # Phase 3: also include client-assigned subreddits
    client_subs = []
    if avatar.warming_phase >= 3:
        rows = (
            db.query(Subreddit.subreddit_name)
            .join(ClientSubredditAssignment, ClientSubredditAssignment.subreddit_id == Subreddit.id)
            .filter(
                ClientSubredditAssignment.client_id == client.id,
                ClientSubredditAssignment.is_active.is_(True),
            )
            .all()
        )
        client_subs = [r[0].lower() for r in rows]

    all_business_subs = list(set(business_subs + client_subs))
    if not all_business_subs:
        return []

    # Get subreddit IDs
    sub_ids = (
        db.query(Subreddit.id)
        .filter(sa_func.lower(Subreddit.subreddit_name).in_(all_business_subs))
        .all()
    )
    sub_id_list = [r[0] for r in sub_ids]
    if not sub_id_list:
        return []

    # Query threads: not locked, not already used by this avatar
    query = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit_id.in_(sub_id_list),
            RedditThread.is_locked.is_(False),
            RedditThread.ups >= 3,
        )
    )
    if used_thread_ids:
        query = query.filter(~RedditThread.id.in_(used_thread_ids))

    threads = query.order_by(RedditThread.ups.desc()).limit(count * 3).all()

    if not threads:
        return []

    # Keyword scoring
    keywords = client.keywords or {}
    high_kw = [k.lower() for k in keywords.get("high", [])]
    medium_kw = [k.lower() for k in keywords.get("medium", [])]
    low_kw = [k.lower() for k in keywords.get("low", [])]

    def _keyword_score(thread: RedditThread) -> float:
        text = f"{thread.post_title} {thread.post_body or ''}".lower()
        score = 0.0
        for kw in high_kw:
            if kw in text:
                score += 3.0
        for kw in medium_kw:
            if kw in text:
                score += 2.0
        for kw in low_kw:
            if kw in text:
                score += 1.0
        return score

    # Score and sort: keyword_score * log(ups+1) for balanced ranking
    import math
    scored = [(t, _keyword_score(t) * math.log(t.ups + 1, 10)) for t in threads]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Filter: at least some keyword relevance for Phase 2-3
    relevant = [t for t, s in scored if s > 0]

    # If not enough keyword matches, fill with top-ups threads
    if len(relevant) < count:
        remaining = [t for t, s in scored if s == 0]
        relevant.extend(remaining[:count - len(relevant)])

    return relevant[:count]


# --- EPG Builder ---

class EPGResult:
    """Result of EPG generation for an avatar."""

    def __init__(self, avatar: Avatar):
        self.avatar_id = avatar.id
        self.avatar_username = avatar.reddit_username
        self.phase = avatar.warming_phase
        self.daily_budget = 0
        self.used_today = 0
        self.remaining = 0
        self.hobby_slots: list[dict] = []
        self.business_slots: list[dict] = []
        self.status = "ok"
        self.message = ""

    @property
    def total_slots(self) -> int:
        return len(self.hobby_slots) + len(self.business_slots)

    def to_dict(self) -> dict:
        return {
            "avatar_id": str(self.avatar_id),
            "avatar_username": self.avatar_username,
            "phase": self.phase,
            "daily_budget": self.daily_budget,
            "used_today": self.used_today,
            "remaining": self.remaining,
            "total_slots": self.total_slots,
            "hobby_slots": len(self.hobby_slots),
            "business_slots": len(self.business_slots),
            "status": self.status,
            "message": self.message,
        }


def build_daily_epg(
    db: Session,
    avatar: Avatar,
    client: Optional[Client] = None,
) -> EPGResult:
    """Build the daily EPG (publishing program) for an avatar.

    This is the main entry point. It:
    1. Checks budget (daily limit - already used today)
    2. Selects threads based on phase (hobby / business)
    3. Assigns time slots with jitter
    4. Returns the EPG ready for generation

    Does NOT call LLM. That's done separately by generate_epg_comments().

    Args:
        db: Database session
        avatar: The avatar to build EPG for
        client: Client context (required for Phase 2-3 keyword matching)

    Returns:
        EPGResult with selected threads and time slots
    """
    result = EPGResult(avatar)

    # --- Guards ---
    if avatar.is_frozen:
        result.status = "frozen"
        result.message = f"Avatar frozen: {avatar.freeze_reason or 'no reason'}"
        return result

    if avatar.warming_phase == 0:
        result.status = "excluded"
        result.message = "Mentor avatars excluded from EPG"
        return result

    if avatar.health_status in ("shadowbanned", "suspended"):
        result.status = "excluded"
        result.message = f"Avatar health: {avatar.health_status}"
        return result

    if not avatar.active:
        result.status = "excluded"
        result.message = "Avatar is deactivated"
        return result

    # --- Budget ---
    result.daily_budget = _get_daily_budget(avatar)
    result.used_today = _get_used_today(db, avatar)
    result.remaining = max(0, result.daily_budget - result.used_today)

    if result.remaining <= 0:
        result.status = "budget_exhausted"
        result.message = f"Daily budget exhausted ({result.used_today}/{result.daily_budget})"
        return result

    # --- Deduplication sets ---
    used_thread_ids = _get_avatar_used_thread_ids(db, avatar)
    used_hobby_ids = _get_avatar_used_hobby_post_ids(db, avatar)

    # --- Phase-based selection ---
    phase = avatar.warming_phase
    hobby_count = 0
    business_count = 0

    if phase == 1:
        # Phase 1: 100% hobby
        hobby_count = result.remaining
    elif phase == 2:
        # Phase 2: 50% hobby, 50% business (no brand mentions)
        hobby_count = result.remaining // 2 + result.remaining % 2
        business_count = result.remaining // 2
    elif phase == 3:
        # Phase 3: 30% hobby, 70% business (brand allowed)
        hobby_count = max(1, result.remaining * 3 // 10)
        business_count = result.remaining - hobby_count

    # --- Select hobby threads ---
    if hobby_count > 0:
        hobby_posts = _select_hobby_threads(db, avatar, hobby_count, used_hobby_ids)
        time_slots = _generate_time_slots(len(hobby_posts))

        for i, post in enumerate(hobby_posts):
            slot_time = time_slots[i] if i < len(time_slots) else None
            result.hobby_slots.append({
                "hobby_post_id": str(post.id),
                "post_id": post.post_id,
                "subreddit": post.subreddit,
                "title": post.post_title,
                "ups": post.post_ups or 0,
                "scheduled_at": slot_time.isoformat() if slot_time else None,
                "comment_type": "hobby",
            })

    # --- Select business threads (Phase 2-3 only) ---
    if business_count > 0 and client:
        business_threads = _select_business_threads(
            db, avatar, client, business_count, used_thread_ids
        )
        # Offset time slots for business (interleave with hobby)
        biz_slots = _generate_time_slots(len(business_threads))

        for i, thread in enumerate(business_threads):
            slot_time = biz_slots[i] if i < len(biz_slots) else None
            result.business_slots.append({
                "thread_id": str(thread.id),
                "subreddit": thread.subreddit,
                "title": thread.post_title,
                "ups": thread.ups,
                "scheduled_at": slot_time.isoformat() if slot_time else None,
                "comment_type": "professional",
            })

    if result.total_slots == 0:
        result.status = "no_content"
        result.message = "No suitable threads found for EPG"

    logger.info(
        "EPG built: avatar=%s phase=%d budget=%d/%d hobby=%d business=%d",
        avatar.reddit_username, phase, result.remaining, result.daily_budget,
        len(result.hobby_slots), len(result.business_slots),
    )

    return result
