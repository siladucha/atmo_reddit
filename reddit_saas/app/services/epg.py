"""EPG — Daily Avatar Publishing Program.

Generates a daily schedule of comment drafts for an avatar.
Like TV EPG shows what airs and when, avatar EPG shows what to post, where, and when.

Key principles:
- Persistent: plan is saved to epg_slots table (single source of truth)
- Deduplication: never assign a thread where avatar already has a draft/posted comment
- Phase-aware: Phase 1 = hobby only (no LLM scoring), Phase 2-3 = hobby + business
- Subreddit rotation: round-robin across available subs, not all from one
- Timing slots: randomized intervals throughout the day
- Cost-efficient: hobby threads skip LLM scoring entirely
- Scored-first: professional slots prefer threads already scored as "engage"
"""

from app.logging_config import get_logger
import random
import uuid
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
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

logger = get_logger(__name__)


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

    NOTE: Image-only posts (empty post_body) are excluded because
    the LLM cannot see images and will generate nonsensical comments.
    This will be revisited when multimodal LLM support is added.
    """
    # Get available hobby posts grouped by subreddit
    # Exclude image-only posts: post_body must have meaningful text (>20 chars)
    posts = (
        db.query(HobbySubreddit)
        .filter(
            HobbySubreddit.avatar_username == avatar.reddit_username,
            HobbySubreddit.status == "new",
            HobbySubreddit.ai_comment.is_(None),
            HobbySubreddit.post_body.isnot(None),
            sa_func.length(HobbySubreddit.post_body) > 20,
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
    """Select business/client threads — scored "engage" first, keyword fallback.

    Priority order:
    1. Threads scored as "engage" for this client (already validated by LLM)
    2. If not enough engage threads: fallback to keyword matching (unscored)

    This fixes the disconnect where EPG showed threads that generation
    couldn't find (because they weren't scored as "engage").
    """
    # --- Priority 1: Scored "engage" threads ---
    engage_query = (
        db.query(RedditThread)
        .join(ThreadScore, ThreadScore.thread_id == RedditThread.id)
        .filter(
            ThreadScore.client_id == client.id,
            ThreadScore.tag == "engage",
            RedditThread.is_locked.is_(False),
        )
    )
    if used_thread_ids:
        engage_query = engage_query.filter(~RedditThread.id.in_(used_thread_ids))

    engage_threads = (
        engage_query
        .order_by(
            ThreadScore.alert.desc(),
            ThreadScore.composite.desc(),
            RedditThread.ups.desc(),
        )
        .limit(count)
        .all()
    )

    if len(engage_threads) >= count:
        return engage_threads[:count]

    # --- Priority 2: Keyword fallback for remaining slots ---
    already_selected = {t.id for t in engage_threads}
    remaining_count = count - len(engage_threads)

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
        return engage_threads

    # Get subreddit IDs
    sub_ids = (
        db.query(Subreddit.id)
        .filter(sa_func.lower(Subreddit.subreddit_name).in_(all_business_subs))
        .all()
    )
    sub_id_list = [r[0] for r in sub_ids]
    if not sub_id_list:
        return engage_threads

    # Query threads: not locked, not already used, not already selected
    # NOTE: Image-only posts (empty post_body) are excluded — LLM cannot
    # see images and would generate nonsensical comments.
    excluded_ids = used_thread_ids | already_selected
    query = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit_id.in_(sub_id_list),
            RedditThread.is_locked.is_(False),
            RedditThread.ups >= 3,
            RedditThread.post_body.isnot(None),
            sa_func.length(RedditThread.post_body) > 20,
        )
    )
    if excluded_ids:
        query = query.filter(~RedditThread.id.in_(excluded_ids))

    threads = query.order_by(RedditThread.ups.desc()).limit(remaining_count * 3).all()

    if not threads:
        return engage_threads

    # Keyword scoring
    keywords = client.keywords or {}
    high_kw = [k.lower() for k in keywords.get("high", [])]
    medium_kw = [k.lower() for k in keywords.get("medium", [])]
    low_kw = [k.lower() for k in keywords.get("low", [])]
    competitor_kw = [k.lower() for k in keywords.get("competitor", [])]

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
        for kw in competitor_kw:
            if kw in text:
                score += 2.5  # Competitor mentions are high-value engagement targets
        return score

    # Score and sort (with outcome-based subreddit adjustments from feedback loop)
    import math
    from app.services.feedback_loop import get_all_epg_adjustments

    # Load feedback adjustments: {subreddit: delta (-1.0 to +1.0)}
    try:
        epg_adjustments = get_all_epg_adjustments(db, avatar.id)
    except Exception:
        epg_adjustments = {}  # Non-critical: proceed without adjustments

    def _feedback_multiplier(subreddit_name: str) -> float:
        """Convert feedback adjustment to scoring multiplier.

        delta = 0.0 → multiplier = 1.0 (no change)
        delta = 0.3 → multiplier = 1.3 (boost 30%)
        delta = -0.3 → multiplier = 0.7 (reduce 30%)
        delta = -0.8 → multiplier = 0.2 (heavily penalize)
        """
        delta = epg_adjustments.get(subreddit_name.lower(), 0.0)
        return max(0.1, 1.0 + delta)

    scored = [
        (t, _keyword_score(t) * math.log(t.ups + 1, 10) * _feedback_multiplier(t.subreddit or ""))
        for t in threads
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Take top keyword-matched threads
    fallback = [t for t, s in scored[:remaining_count]]

    return engage_threads + fallback


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
        self.built_at: str | None = None  # When the EPG was last built (latest slot created_at)

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
    2. Reads existing slots for today (preserves generated/approved/posted)
    3. Selects threads based on phase (hobby / business) for remaining budget
    4. Assigns time slots with jitter
    5. Persists new planned slots to epg_slots table
    6. Returns the EPG ready for generation

    Does NOT call LLM. That's done separately by generate_epg_slot().

    Args:
        db: Database session
        avatar: The avatar to build EPG for
        client: Client context (required for Phase 2-3 keyword matching)

    Returns:
        EPGResult with selected threads and time slots
    """
    result = EPGResult(avatar)
    today = date.today()

    # --- Guards ---
    if avatar.is_frozen:
        result.status = "frozen"
        result.message = f"Avatar frozen: {avatar.freeze_reason or 'no reason'}"
        return result

    if avatar.warming_phase == 0:
        result.status = "excluded"
        result.message = "Mentor avatars excluded from EPG"
        return result

    if getattr(avatar, "pool", "b2b") not in ("b2b", "b2c", "warm"):
        result.status = "excluded"
        result.message = f"Avatar pool '{avatar.pool}' excluded from EPG"
        return result

    if avatar.health_status in ("shadowbanned", "suspended"):
        result.status = "excluded"
        result.message = f"Avatar health: {avatar.health_status}"
        return result

    if not avatar.active:
        result.status = "excluded"
        result.message = "Avatar is deactivated"
        return result

    # --- Budget (from EPG slots) ---
    from app.services.epg_executor import get_budget_used_today

    result.daily_budget = _get_daily_budget(avatar)
    result.used_today = get_budget_used_today(db, avatar.id, today)
    result.remaining = max(0, result.daily_budget - result.used_today)

    # --- Load existing slots for today (generated/approved/posted stay) ---
    existing_slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date == today,
        )
        .order_by(EPGSlot.scheduled_at.asc().nullslast())
        .all()
    )

    # Populate result from existing non-planned slots
    for slot in existing_slots:
        if slot.status in ("generated", "approved", "posted", "skipped"):
            slot_dict = {
                "slot_id": str(slot.id),
                "subreddit": slot.subreddit,
                "title": slot.thread_title,
                "ups": slot.thread_ups or 0,
                "scheduled_at": slot.scheduled_at.isoformat() if slot.scheduled_at else None,
                "created_at": slot.created_at.isoformat() if slot.created_at else None,
                "status": slot.status,
                "draft_id": str(slot.draft_id) if slot.draft_id else None,
                "skip_reason": slot.skip_reason,
            }
            if slot.slot_type == "hobby":
                slot_dict["hobby_post_id"] = str(slot.hobby_post_id) if slot.hobby_post_id else None
                slot_dict["post_id"] = None
                slot_dict["comment_type"] = "hobby"
                result.hobby_slots.append(slot_dict)
            else:
                slot_dict["thread_id"] = str(slot.thread_id) if slot.thread_id else None
                slot_dict["comment_type"] = "professional"
                result.business_slots.append(slot_dict)

    # Set built_at from latest slot created_at
    if existing_slots:
        latest_created = max(
            (s.created_at for s in existing_slots if s.created_at), default=None
        )
        if latest_created:
            result.built_at = latest_created.strftime("%H:%M")

    # --- Delete old "planned" slots (rebuild replaces them) ---
    (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == avatar.id,
            EPGSlot.plan_date == today,
            EPGSlot.status == "planned",
        )
        .delete(synchronize_session="fetch")
    )

    if result.remaining <= 0:
        result.status = "budget_exhausted"
        result.message = f"Daily budget exhausted ({result.used_today}/{result.daily_budget})"
        db.commit()
        return result

    # --- Deduplication sets ---
    used_thread_ids = _get_avatar_used_thread_ids(db, avatar)
    used_hobby_ids = _get_avatar_used_hobby_post_ids(db, avatar)

    # Also exclude threads already in today's non-planned slots
    for slot in existing_slots:
        if slot.status != "planned":
            if slot.thread_id:
                used_thread_ids.add(slot.thread_id)

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

    # --- Select and persist hobby slots ---
    if hobby_count > 0:
        hobby_posts = _select_hobby_threads(db, avatar, hobby_count, used_hobby_ids)
        time_slots = _generate_time_slots(len(hobby_posts))

        for i, post in enumerate(hobby_posts):
            slot_time = time_slots[i] if i < len(time_slots) else None

            # Persist to DB with decision reasoning
            epg_slot = EPGSlot(
                id=uuid.uuid4(),
                avatar_id=avatar.id,
                client_id=uuid.UUID(avatar.client_ids[0]) if avatar.client_ids else None,
                plan_date=today,
                slot_type="hobby",
                scheduled_at=slot_time,
                status="planned",
                hobby_post_id=post.id,
                subreddit=post.subreddit,
                thread_title=post.post_title,
                thread_ups=post.post_ups or 0,
                selection_reasoning={
                    "reason": f"Hobby rotation: r/{post.subreddit} selected for credibility building",
                    "selection_method": "round_robin_hobby",
                    "phase": phase,
                    "factors": [
                        f"Phase {phase}: {'100%' if phase == 1 else '50%' if phase == 2 else '30%'} hobby allocation",
                        f"Subreddit r/{post.subreddit}: part of avatar's hobby interests",
                        f"Post engagement: {post.post_ups or 0} upvotes",
                    ],
                    "budget": f"{i+1}/{hobby_count} hobby slots",
                    "alternatives_considered": len(hobby_posts),
                },
            )
            db.add(epg_slot)

            result.hobby_slots.append({
                "slot_id": str(epg_slot.id),
                "hobby_post_id": str(post.id),
                "post_id": post.post_id,
                "subreddit": post.subreddit,
                "title": post.post_title,
                "ups": post.post_ups or 0,
                "scheduled_at": slot_time.isoformat() if slot_time else None,
                "comment_type": "hobby",
                "status": "planned",
                "draft_id": None,
                "reasoning": epg_slot.selection_reasoning,
            })

    # --- Select and persist business slots (Phase 2-3 only) ---
    if business_count > 0 and client:
        business_threads = _select_business_threads(
            db, avatar, client, business_count, used_thread_ids
        )
        biz_slots = _generate_time_slots(len(business_threads))

        # Load feedback adjustments for reasoning display
        try:
            from app.services.feedback_loop import get_all_epg_adjustments as _get_adj
            _feedback_adj = _get_adj(db, avatar.id)
        except Exception:
            _feedback_adj = {}

        for i, thread in enumerate(business_threads):
            slot_time = biz_slots[i] if i < len(biz_slots) else None

            # Determine selection method (engage-scored vs keyword fallback)
            from app.models.thread_score import ThreadScore
            thread_score = db.query(ThreadScore).filter(
                ThreadScore.thread_id == thread.id,
                ThreadScore.client_id == client.id,
            ).first()

            if thread_score and thread_score.tag == "engage":
                method = "ai_scored_engage"
                reason = f"AI scored as 'engage' (composite={thread_score.composite}) for {client.client_name}"
            else:
                method = "keyword_fallback"
                reason = f"Keyword match in r/{thread.subreddit} ({thread.ups} upvotes)"

            # Check if feedback adjustment was applied
            sub_adj = _feedback_adj.get((thread.subreddit or "").lower(), 0)
            factors = [
                f"Phase {phase}: {int((1 - hobby_count/result.remaining)*100)}% professional allocation",
                f"Thread: {thread.ups} upvotes in r/{thread.subreddit}",
            ]
            if sub_adj > 0:
                factors.append(f"Feedback boost: +{sub_adj:.0%} from positive outcomes in r/{thread.subreddit}")
            elif sub_adj < 0:
                factors.append(f"Feedback penalty: {sub_adj:.0%} from poor outcomes in r/{thread.subreddit}")

            # Persist to DB
            epg_slot = EPGSlot(
                id=uuid.uuid4(),
                avatar_id=avatar.id,
                client_id=client.id,
                plan_date=today,
                slot_type="professional",
                scheduled_at=slot_time,
                status="planned",
                thread_id=thread.id,
                subreddit=thread.subreddit,
                thread_title=thread.post_title,
                thread_ups=thread.ups,
                selection_reasoning={
                    "reason": reason,
                    "selection_method": method,
                    "phase": phase,
                    "factors": factors,
                    "score": thread_score.composite if thread_score else None,
                    "feedback_adjustment": sub_adj if sub_adj != 0 else None,
                    "budget": f"{i+1}/{business_count} professional slots",
                    "alternatives_considered": len(business_threads),
                    "client": client.client_name,
                },
            )
            db.add(epg_slot)

            result.business_slots.append({
                "slot_id": str(epg_slot.id),
                "thread_id": str(thread.id),
                "subreddit": thread.subreddit,
                "title": thread.post_title,
                "ups": thread.ups,
                "scheduled_at": slot_time.isoformat() if slot_time else None,
                "comment_type": "professional",
                "status": "planned",
                "draft_id": None,
                "reasoning": epg_slot.selection_reasoning,
            })

    db.commit()

    if result.total_slots == 0:
        result.status = "no_content"
        result.message = "No suitable threads found for EPG"

    logger.info(
        "EPG built: avatar=%s phase=%d budget=%d/%d hobby=%d business=%d",
        avatar.reddit_username, phase, result.remaining, result.daily_budget,
        len(result.hobby_slots), len(result.business_slots),
    )

    return result
