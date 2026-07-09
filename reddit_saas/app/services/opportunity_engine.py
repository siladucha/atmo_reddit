"""EPG 2.0 — Opportunity Engine.

Scans the attention market and identifies engagement opportunities for each avatar.
Computes six scoring dimensions for each opportunity using deterministic formulas
(no LLM calls).

Scoring dimensions:
- Visibility (0-100): thread freshness, moderate ups, comment room, sub size
- Competition (0-100): fewer comments = higher, no top-comment domination
- Trust_Potential (0-100): topic alignment, expertise opportunity, discussion depth
- Karma_Potential (0-100): historical avg, engagement velocity, position
- Strategic_Alignment (0-100): ThreadScore.strategic, client keywords, niche relevance
"""

from __future__ import annotations

import json
from app.logging_config import get_logger
import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.models.thread import RedditThread
    from app.models.thread_score import ThreadScore

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: int | float) -> int:
    """Clamp a numeric value to [0, 100] integer range."""
    return max(0, min(100, int(round(value))))


def _get_thread_age_hours(thread: "RedditThread") -> float:
    """Compute thread age in hours from reddit_created_at or created_at.

    Falls back to created_at (scrape time) if reddit_created_at is not set.
    """
    ref_time = thread.reddit_created_at or thread.created_at
    if ref_time is None:
        return 24.0  # fallback: treat as old-ish

    now = datetime.now(timezone.utc)
    # Ensure ref_time is timezone-aware
    if ref_time.tzinfo is None:
        ref_time = ref_time.replace(tzinfo=timezone.utc)

    delta = now - ref_time
    return max(0.0, delta.total_seconds() / 3600.0)


def _estimate_comment_count(thread: "RedditThread") -> int:
    """Estimate the number of comments in a thread.

    Attempts to parse comments_json as a JSON list to get an accurate count.
    Falls back to a size-based heuristic if parsing fails.
    """
    if not thread.comments_json:
        return 0

    try:
        comments = json.loads(thread.comments_json)
        if isinstance(comments, list):
            return len(comments)
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback heuristic: ~300 chars per comment on average
    return max(1, len(thread.comments_json) // 300)


def _get_top_comment_ups(thread: "RedditThread") -> int:
    """Get the upvote count of the top comment in a thread.

    Returns 0 if no comments or parsing fails.
    """
    if not thread.comments_json:
        return 0

    try:
        comments = json.loads(thread.comments_json)
        if isinstance(comments, list) and comments:
            # Comments may be dicts with 'ups' or 'score' field
            max_ups = 0
            for c in comments:
                if isinstance(c, dict):
                    ups = c.get("ups", c.get("score", 0))
                    if isinstance(ups, (int, float)):
                        max_ups = max(max_ups, int(ups))
            return max_ups
    except (json.JSONDecodeError, TypeError):
        pass

    return 0


# ---------------------------------------------------------------------------
# Scoring Functions
# ---------------------------------------------------------------------------


def compute_visibility(thread: "RedditThread", sub_size: int) -> int:
    """Compute visibility score (0-100).

    Higher score = better visibility opportunity for the avatar.

    Factors:
    - Thread age: fresher is better. 100 for <1h, decays ~5/hour, min 10 at 24h+.
    - Moderate upvotes: sweet spot 5-50 ups. 0 or >500 scores lower.
    - Fewer comments: <5 = high room, >50 = crowded.
    - Sub size: larger subs = more visibility potential (log scale).

    Weights: age=35%, ups=25%, comments=25%, sub_size=15%

    Args:
        thread: RedditThread with ups, comments_json, reddit_created_at.
        sub_size: Number of subscribers in the subreddit.

    Returns:
        Integer score clamped to [0, 100].
    """
    # --- Age factor (0-100) ---
    age_hours = _get_thread_age_hours(thread)
    if age_hours < 1.0:
        age_score = 100.0
    elif age_hours >= 24.0:
        age_score = 10.0
    else:
        # Linear decay: 100 at 0h → 10 at 24h
        # Drop ~3.9 per hour
        age_score = 100.0 - (age_hours * (90.0 / 23.0))

    # --- Upvote factor (0-100) ---
    # Sweet spot around 5-50 ups
    ups = thread.ups or 0
    if ups <= 0:
        ups_score = 20.0  # zero or negative: low but not zero
    elif ups <= 5:
        # Ramp up: 0→5 maps to 20→80
        ups_score = 20.0 + (ups / 5.0) * 60.0
    elif ups <= 50:
        # Sweet spot: 5→50 maps to 80→100
        ups_score = 80.0 + ((ups - 5) / 45.0) * 20.0
    elif ups <= 200:
        # Declining: 50→200 maps to 100→60
        ups_score = 100.0 - ((ups - 50) / 150.0) * 40.0
    elif ups <= 500:
        # Further decline: 200→500 maps to 60→30
        ups_score = 60.0 - ((ups - 200) / 300.0) * 30.0
    else:
        # Very high ups: too much competition, low visibility for new comments
        ups_score = 30.0 - min(20.0, (ups - 500) / 500.0 * 20.0)

    # --- Comment count factor (0-100) ---
    # Fewer comments = more room for visibility
    comment_count = _estimate_comment_count(thread)
    if comment_count == 0:
        comment_score = 95.0  # Fresh thread, great visibility
    elif comment_count <= 5:
        comment_score = 90.0 - (comment_count * 2.0)
    elif comment_count <= 20:
        # 5→20 maps to 80→50
        comment_score = 80.0 - ((comment_count - 5) / 15.0) * 30.0
    elif comment_count <= 50:
        # 20→50 maps to 50→20
        comment_score = 50.0 - ((comment_count - 20) / 30.0) * 30.0
    else:
        # >50: very crowded
        comment_score = max(5.0, 20.0 - (comment_count - 50) / 50.0 * 15.0)

    # --- Sub size factor (0-100) ---
    # Larger subs = more eyeballs = more visibility potential (logarithmic)
    if sub_size <= 0:
        sub_score = 10.0
    else:
        # log10(1000) = 3 → ~30, log10(100000) = 5 → ~50, log10(1M) = 6 → ~60
        # Scale: log10(sub_size) * 15, capped at 100
        sub_score = min(100.0, math.log10(max(1, sub_size)) * 15.0)

    # --- Combine with weights ---
    score = (
        age_score * 0.35
        + ups_score * 0.25
        + comment_score * 0.25
        + sub_score * 0.15
    )

    return _clamp(score)


def compute_competition(thread: "RedditThread") -> int:
    """Compute competition score (0-100, higher = LESS competition).

    A high score means the thread has low competition, making it a
    good opportunity for an avatar to stand out.

    Factors:
    - Fewer comments → higher score (inverse relationship)
    - If thread has a top comment with high ups (>50), competition
      is high → lower score

    Weights: comment_count=60%, top_comment_dominance=40%

    Args:
        thread: RedditThread with comments_json.

    Returns:
        Integer score clamped to [0, 100].
    """
    # --- Comment count factor (0-100, inverse) ---
    comment_count = _estimate_comment_count(thread)
    if comment_count == 0:
        count_score = 100.0
    elif comment_count <= 3:
        count_score = 95.0 - (comment_count * 5.0)
    elif comment_count <= 10:
        # 3→10 maps to 80→55
        count_score = 80.0 - ((comment_count - 3) / 7.0) * 25.0
    elif comment_count <= 30:
        # 10→30 maps to 55→25
        count_score = 55.0 - ((comment_count - 10) / 20.0) * 30.0
    elif comment_count <= 100:
        # 30→100 maps to 25→5
        count_score = 25.0 - ((comment_count - 30) / 70.0) * 20.0
    else:
        count_score = 5.0

    # --- Top comment domination factor (0-100) ---
    # If a comment already has many ups, it dominates the thread
    top_ups = _get_top_comment_ups(thread)
    if top_ups <= 5:
        domination_score = 100.0  # No dominant comment
    elif top_ups <= 20:
        # Mild domination: 5→20 maps to 100→70
        domination_score = 100.0 - ((top_ups - 5) / 15.0) * 30.0
    elif top_ups <= 50:
        # Moderate: 20→50 maps to 70→40
        domination_score = 70.0 - ((top_ups - 20) / 30.0) * 30.0
    elif top_ups <= 200:
        # Strong: 50→200 maps to 40→10
        domination_score = 40.0 - ((top_ups - 50) / 150.0) * 30.0
    else:
        domination_score = 10.0

    # --- Combine ---
    score = count_score * 0.60 + domination_score * 0.40

    return _clamp(score)


def compute_trust_potential(
    thread: "RedditThread",
    avatar: "Avatar",
    thread_score: "ThreadScore | None",
) -> int:
    """Compute trust potential score (0-100).

    Measures how well this opportunity allows the avatar to build
    trust and credibility in the community.

    Factors:
    - Topic alignment: check if thread relates to avatar's niche
      (from hobby_subreddits/business_subreddits matching).
    - Expertise opportunity: help_seeking intent scores highest (40 pts).
    - Discussion depth: threads with moderate comments (5-20) have
      good dialogue potential.
    - Intent weighting from ThreadScore (help_seeking, discussion,
      experience_sharing).

    Args:
        thread: RedditThread with post_title, subreddit.
        avatar: Avatar with hobby_subreddits, business_subreddits, warming_phase.
        thread_score: Optional ThreadScore with intent field.

    Returns:
        Integer score clamped to [0, 100].
    """
    score = 0.0

    # --- Topic alignment (0-30 pts) ---
    # Check if thread subreddit matches avatar's assigned subreddits
    subreddit_lower = (thread.subreddit or "").lower()
    avatar_subs = set()

    # Gather avatar's subreddit list
    if avatar.hobby_subreddits:
        if isinstance(avatar.hobby_subreddits, dict):
            for sub_list in avatar.hobby_subreddits.values():
                if isinstance(sub_list, list):
                    avatar_subs.update(s.lower().lstrip("r/") for s in sub_list)
                elif isinstance(sub_list, str):
                    avatar_subs.add(sub_list.lower().lstrip("r/"))
        elif isinstance(avatar.hobby_subreddits, list):
            for item in avatar.hobby_subreddits:
                if isinstance(item, dict):
                    sub_name = item.get("subreddit", "")
                    if sub_name:
                        avatar_subs.add(sub_name.lower().lstrip("r/"))
                elif isinstance(item, str):
                    avatar_subs.add(item.lower().lstrip("r/"))

    if avatar.business_subreddits:
        if isinstance(avatar.business_subreddits, dict):
            for sub_list in avatar.business_subreddits.values():
                if isinstance(sub_list, list):
                    avatar_subs.update(s.lower().lstrip("r/") for s in sub_list)
                elif isinstance(sub_list, str):
                    avatar_subs.add(sub_list.lower().lstrip("r/"))
        elif isinstance(avatar.business_subreddits, list):
            avatar_subs.update(s.lower().lstrip("r/") for s in avatar.business_subreddits)

    if subreddit_lower in avatar_subs:
        score += 30.0
    else:
        # Partial match: at least the thread exists in the system
        score += 10.0

    # --- Expertise opportunity / Intent (0-40 pts) ---
    intent = None
    if thread_score is not None:
        intent = getattr(thread_score, "intent", None)

    if intent:
        intent_lower = intent.lower().strip()
        if "help" in intent_lower or "seeking" in intent_lower:
            # Help-seeking: highest expertise opportunity
            score += 40.0
        elif "discussion" in intent_lower:
            # Discussion: good for building credibility
            score += 30.0
        elif "experience" in intent_lower or "sharing" in intent_lower:
            # Experience sharing: moderate trust building
            score += 25.0
        else:
            # Other intents: some baseline value
            score += 15.0
    else:
        # No intent data — use heuristic from title
        title_lower = (thread.post_title or "").lower()
        if any(kw in title_lower for kw in ["help", "how to", "advice", "question", "?", "recommend"]):
            score += 30.0
        elif any(kw in title_lower for kw in ["discuss", "thoughts", "opinion", "what do you think"]):
            score += 20.0
        else:
            score += 10.0

    # --- Discussion depth potential (0-30 pts) ---
    # Threads with 5-20 comments have the best dialogue potential
    comment_count = _estimate_comment_count(thread)
    if comment_count == 0:
        # Fresh thread: can start the conversation but less back-and-forth
        depth_score = 15.0
    elif comment_count <= 5:
        # Building up: good entry point for dialogue
        depth_score = 20.0 + (comment_count * 2.0)
    elif comment_count <= 20:
        # Sweet spot for dialogue: active but not overwhelming
        depth_score = 30.0
    elif comment_count <= 40:
        # Still okay but getting crowded
        depth_score = 30.0 - ((comment_count - 20) / 20.0) * 15.0
    else:
        # Too many comments — hard to have meaningful dialogue
        depth_score = max(5.0, 15.0 - (comment_count - 40) / 60.0 * 10.0)

    score += depth_score

    return _clamp(score)


def compute_karma_potential(
    thread: "RedditThread",
    avatar: "Avatar",
    subreddit_karma_avg: float,
) -> int:
    """Compute karma potential score (0-100).

    Estimates how much karma an avatar is likely to earn from engaging
    with this thread.

    Factors:
    - Historical avg karma for avatar in this subreddit (subreddit_karma_avg param).
    - Thread engagement velocity: ups/age_hours ratio.
    - Position: early threads (<3h, <10 comments) get bonus for first-mover advantage.

    Args:
        thread: RedditThread with ups, reddit_created_at, comments_json.
        avatar: Avatar (used for phase context).
        subreddit_karma_avg: Average karma per comment for this avatar in this
            subreddit. 0.0 if unknown/no history.

    Returns:
        Integer score clamped to [0, 100].
    """
    # --- Historical performance factor (0-40 pts) ---
    # Scale based on historical karma average
    if subreddit_karma_avg <= 0:
        # No history or negative: neutral baseline
        history_score = 15.0
    elif subreddit_karma_avg <= 2:
        # Low performer: 0→2 maps to 15→25
        history_score = 15.0 + (subreddit_karma_avg / 2.0) * 10.0
    elif subreddit_karma_avg <= 10:
        # Decent: 2→10 maps to 25→35
        history_score = 25.0 + ((subreddit_karma_avg - 2) / 8.0) * 10.0
    elif subreddit_karma_avg <= 50:
        # Good: 10→50 maps to 35→40
        history_score = 35.0 + ((subreddit_karma_avg - 10) / 40.0) * 5.0
    else:
        # Excellent historical performance
        history_score = 40.0

    # --- Engagement velocity (0-30 pts) ---
    # ups / age_hours — indicates a hot thread
    age_hours = _get_thread_age_hours(thread)
    ups = thread.ups or 0

    if age_hours < 0.1:
        age_hours = 0.1  # Avoid division by zero

    velocity = ups / age_hours

    if velocity <= 0:
        velocity_score = 5.0
    elif velocity <= 2:
        # Low velocity
        velocity_score = 5.0 + (velocity / 2.0) * 10.0
    elif velocity <= 10:
        # Moderate: 2→10 maps to 15→25
        velocity_score = 15.0 + ((velocity - 2) / 8.0) * 10.0
    elif velocity <= 50:
        # Good: 10→50 maps to 25→30
        velocity_score = 25.0 + ((velocity - 10) / 40.0) * 5.0
    else:
        # Very high velocity — hot thread
        velocity_score = 30.0

    # --- Position / first-mover advantage (0-30 pts) ---
    # Early threads (fresh + few comments) get bonus
    comment_count = _estimate_comment_count(thread)

    position_score = 0.0
    if age_hours < 1.0 and comment_count < 5:
        # Prime first-mover position
        position_score = 30.0
    elif age_hours < 2.0 and comment_count < 10:
        position_score = 25.0
    elif age_hours < 3.0 and comment_count < 10:
        position_score = 20.0
    elif age_hours < 6.0 and comment_count < 20:
        position_score = 15.0
    elif age_hours < 12.0 and comment_count < 30:
        position_score = 10.0
    else:
        # Late entry — diminished returns
        position_score = 5.0

    score = history_score + velocity_score + position_score

    return _clamp(score)


def compute_strategic_alignment(
    thread: "RedditThread",
    thread_score: "ThreadScore | None",
    client: "Client | None",
    avatar: "Avatar",
) -> int:
    """Compute strategic alignment score (0-100).

    Measures how well this opportunity aligns with the client's
    strategic goals and the avatar's current phase.

    Factors:
    - ThreadScore.strategic field (if available, 0-100, direct use) — 40%
    - Client keyword matching: thread title/body matches client.keywords — 30%
    - Avatar niche relevance / phase appropriateness — 30%

    Args:
        thread: RedditThread with post_title, post_body.
        thread_score: Optional ThreadScore with strategic field.
        client: Optional Client with keywords JSONB.
        avatar: Avatar with warming_phase.

    Returns:
        Integer score clamped to [0, 100].
    """
    # --- ThreadScore.strategic (0-40 pts) ---
    strategic_raw = 0
    if thread_score is not None:
        s = getattr(thread_score, "strategic", None)
        if s is not None and isinstance(s, (int, float)):
            strategic_raw = int(s)

    # Scale strategic (0-100) to contribute up to 40 pts
    strategic_component = (min(100, max(0, strategic_raw)) / 100.0) * 40.0

    # --- Client keyword matching (0-30 pts) ---
    keyword_component = 0.0
    if client is not None and client.keywords:
        keywords_dict = client.keywords
        # keywords is {"high": [...], "medium": [...], "low": [...]}
        text_to_search = (
            (thread.post_title or "") + " " + (thread.post_body or "")
        ).lower()

        high_keywords = []
        medium_keywords = []
        low_keywords = []

        if isinstance(keywords_dict, dict):
            high_keywords = keywords_dict.get("high", []) or []
            medium_keywords = keywords_dict.get("medium", []) or []
            low_keywords = keywords_dict.get("low", []) or []

        # Check for matches with decreasing weight
        high_matches = sum(1 for kw in high_keywords if kw.lower() in text_to_search)
        medium_matches = sum(1 for kw in medium_keywords if kw.lower() in text_to_search)
        low_matches = sum(1 for kw in low_keywords if kw.lower() in text_to_search)

        # Score: high=10pts each (max 30), medium=5pts each (max 20), low=2pts each (max 10)
        keyword_score = min(30.0, high_matches * 10.0) + min(20.0, medium_matches * 5.0) + min(10.0, low_matches * 2.0)
        keyword_component = min(30.0, keyword_score)
    else:
        # No client or no keywords — neutral baseline
        keyword_component = 10.0

    # --- Avatar niche / phase appropriateness (0-30 pts) ---
    phase = avatar.warming_phase
    phase_component = 0.0

    if phase <= 1:
        # Phase 1: hobby content is most appropriate
        # Check if thread is in a hobby subreddit
        subreddit_lower = (thread.subreddit or "").lower()
        hobby_subs = set()
        if avatar.hobby_subreddits:
            if isinstance(avatar.hobby_subreddits, dict):
                for sub_list in avatar.hobby_subreddits.values():
                    if isinstance(sub_list, list):
                        hobby_subs.update(s.lower().lstrip("r/") for s in sub_list)
                    elif isinstance(sub_list, str):
                        hobby_subs.add(sub_list.lower().lstrip("r/"))
            elif isinstance(avatar.hobby_subreddits, list):
                for item in avatar.hobby_subreddits:
                    if isinstance(item, dict):
                        sub_name = item.get("subreddit", "")
                        if sub_name:
                            hobby_subs.add(sub_name.lower().lstrip("r/"))
                    elif isinstance(item, str):
                        hobby_subs.add(item.lower().lstrip("r/"))

        if subreddit_lower in hobby_subs:
            phase_component = 30.0  # Perfect phase alignment
        else:
            phase_component = 10.0  # Not ideal for Phase 1
    elif phase == 2:
        # Phase 2: expertise content, broader subreddits
        # Business subreddits are appropriate now
        subreddit_lower = (thread.subreddit or "").lower()
        business_subs = set()
        if avatar.business_subreddits:
            if isinstance(avatar.business_subreddits, dict):
                for sub_list in avatar.business_subreddits.values():
                    if isinstance(sub_list, list):
                        business_subs.update(s.lower().lstrip("r/") for s in sub_list)
                    elif isinstance(sub_list, str):
                        business_subs.add(sub_list.lower().lstrip("r/"))
            elif isinstance(avatar.business_subreddits, list):
                business_subs.update(s.lower().lstrip("r/") for s in avatar.business_subreddits)

        if subreddit_lower in business_subs:
            phase_component = 30.0
        else:
            phase_component = 20.0  # Still acceptable
    else:
        # Phase 3+: full brand integration, any strategic content works
        phase_component = 25.0  # Baseline good, not penalized

    score = strategic_component + keyword_component + phase_component

    return _clamp(score)

# ---------------------------------------------------------------------------
# Opportunity Scanning
# ---------------------------------------------------------------------------

# Default equal weights for the 5 non-risk scoring dimensions
DEFAULT_DIMENSION_WEIGHTS = {
    "visibility": 0.20,
    "competition": 0.20,
    "trust_potential": 0.20,
    "karma_potential": 0.20,
    "strategic_alignment": 0.20,
}

MAX_OPPORTUNITIES = 50
MIN_OPPORTUNITIES_FOR_SCARCITY = 10


@dataclass
class OpportunityData:
    """Intermediate data holder for a scored opportunity before DB persistence."""

    thread_id: uuid.UUID | None = None
    hobby_post_id: uuid.UUID | None = None
    subreddit: str = ""
    opportunity_type: str = "comment"
    thread_title: str = ""
    thread_ups: int = 0
    thread_age_hours: float = 0.0
    comment_count: int = 0
    visibility: int = 0
    competition: int = 0
    trust_potential: int = 0
    karma_potential: int = 0
    risk: int = 0  # Set to 0 here, filled later by Risk Engine
    strategic_alignment: int = 0
    composite: int = 0
    thread_score_ref: object | None = field(default=None, repr=False)


def _compute_composite(scores: dict[str, int], weights: dict[str, float] | None = None) -> int:
    """Compute weighted average composite score from dimension scores.

    Args:
        scores: Dict mapping dimension name to integer score (0-100).
        weights: Optional custom weights (should sum to ~1.0). Uses defaults if None.

    Returns:
        Integer composite score clamped to [0, 100].
    """
    w = weights or DEFAULT_DIMENSION_WEIGHTS
    total = 0.0
    for dim, weight in w.items():
        total += scores.get(dim, 0) * weight
    return _clamp(total)


def _get_avatar_subreddit_ids(
    db: Session, avatar: "Avatar", client: "Client | None"
) -> list[uuid.UUID]:
    """Get subreddit IDs assigned to the avatar's client(s).

    Uses ClientSubredditAssignment to find active subreddits for the client.
    """
    from app.models.subreddit import ClientSubredditAssignment

    client_id = None
    if client is not None:
        client_id = client.id
    elif avatar.client_ids:
        try:
            client_id = uuid.UUID(avatar.client_ids[0])
        except (ValueError, TypeError, IndexError):
            pass

    if client_id is None:
        return []

    assignments = (
        db.query(ClientSubredditAssignment.subreddit_id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    return [row[0] for row in assignments]


def _get_subreddit_karma_avg(db: Session, avatar_id: uuid.UUID, subreddit_name: str) -> float:
    """Get average karma per comment for avatar in a specific subreddit.

    Returns 0.0 if no history.
    """
    from app.models.subreddit_karma import SubredditKarma

    record = (
        db.query(SubredditKarma)
        .filter(
            SubredditKarma.avatar_id == avatar_id,
            SubredditKarma.subreddit_name == subreddit_name,
        )
        .first()
    )
    if record is None or record.comment_count == 0:
        return 0.0
    return record.comment_karma / record.comment_count


def _get_existing_thread_ids(db: Session, avatar_id: uuid.UUID) -> set[uuid.UUID]:
    """Get thread IDs where the avatar already has a draft or posted comment.

    Used for deduplication — excludes threads the avatar has already engaged with.
    """
    from app.models.comment_draft import CommentDraft

    rows = (
        db.query(CommentDraft.thread_id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.thread_id.isnot(None),
            CommentDraft.status.in_(["pending", "approved", "posted"]),
        )
        .all()
    )
    return {row[0] for row in rows}


def _get_today_slot_thread_ids(
    db: Session, avatar_id: uuid.UUID, plan_date: date
) -> set[uuid.UUID]:
    """Get thread IDs already in today's EPG slots (non-planned status excluded).

    Excludes threads that are already scheduled in today's slots.
    """
    from app.models.epg_slot import EPGSlot

    rows = (
        db.query(EPGSlot.thread_id)
        .filter(
            EPGSlot.avatar_id == avatar_id,
            EPGSlot.plan_date == plan_date,
            EPGSlot.thread_id.isnot(None),
        )
        .all()
    )
    return {row[0] for row in rows}


def _get_existing_hobby_post_ids(db: Session, avatar_id: uuid.UUID) -> set[uuid.UUID]:
    """Get hobby post IDs where the avatar already has a draft or posted comment."""
    from app.models.comment_draft import CommentDraft

    rows = (
        db.query(CommentDraft.hobby_post_id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.hobby_post_id.isnot(None),
            CommentDraft.status.in_(["pending", "approved", "posted"]),
        )
        .all()
    )
    return {row[0] for row in rows}


def scan_opportunities(
    db: Session,
    avatar: "Avatar",
    client: "Client | None",
    plan_date: date,
) -> list["Opportunity"]:
    """Scan all assigned subreddits and produce scored Opportunity records.

    Sources:
    - ThreadScore records tagged "engage" or "monitor" (pre-scored)
    - HobbySubreddit posts (for Phase 1 / hobby allocation)

    Deduplication:
    - Excludes threads where avatar already has a draft/posted comment
    - Excludes threads in today's existing EPG slots

    Scoring:
    - Visibility, Competition, Trust_Potential, Karma_Potential, Strategic_Alignment
    - Risk is set to 0 (filled later by Risk Engine)
    - Composite = weighted average of 5 non-risk dimensions (20% each)

    Returns:
        List of Opportunity DB model instances sorted by composite_score desc.
        Capped at 50 max results. Logs market_scarcity if < 10 scoreable threads.
    """
    from app.models.hobby import HobbySubreddit
    from app.models.opportunity import Opportunity
    from app.models.thread import RedditThread
    from app.models.thread_score import ThreadScore

    # --- Gather deduplication sets ---
    existing_thread_ids = _get_existing_thread_ids(db, avatar.id)
    today_slot_thread_ids = _get_today_slot_thread_ids(db, avatar.id, plan_date)
    existing_hobby_ids = _get_existing_hobby_post_ids(db, avatar.id)
    exclude_thread_ids = existing_thread_ids | today_slot_thread_ids

    # --- Get avatar's assigned subreddit IDs ---
    subreddit_ids = _get_avatar_subreddit_ids(db, avatar, client)

    opportunities: list[OpportunityData] = []

    # --- Source 1: ThreadScore records tagged "engage" or "monitor" ---
    # Phase 1 avatars only use Source 2 (hobby posts) — skip professional threads
    if subreddit_ids and avatar.warming_phase >= 2:
        # Determine client_id for ThreadScore query
        client_id = client.id if client else None
        if client_id is None and avatar.client_ids:
            try:
                client_id = uuid.UUID(avatar.client_ids[0])
            except (ValueError, TypeError, IndexError):
                pass

        if client_id:
            scored_threads = (
                db.query(ThreadScore, RedditThread)
                .join(RedditThread, ThreadScore.thread_id == RedditThread.id)
                .filter(
                    ThreadScore.client_id == client_id,
                    ThreadScore.tag.in_(["engage", "monitor"]),
                    RedditThread.subreddit_id.in_(subreddit_ids),
                    RedditThread.is_locked.is_(False),
                )
                .all()
            )

            for ts, thread in scored_threads:
                # Deduplication check
                if thread.id in exclude_thread_ids:
                    continue

                subreddit_name = thread.subreddit or ""
                karma_avg = _get_subreddit_karma_avg(db, avatar.id, subreddit_name)

                # Compute scores
                vis = compute_visibility(thread, sub_size=0)
                comp = compute_competition(thread)
                trust = compute_trust_potential(thread, avatar, ts)
                karma = compute_karma_potential(thread, avatar, karma_avg)
                strat = compute_strategic_alignment(thread, ts, client, avatar)

                scores_dict = {
                    "visibility": vis,
                    "competition": comp,
                    "trust_potential": trust,
                    "karma_potential": karma,
                    "strategic_alignment": strat,
                }
                composite = _compute_composite(scores_dict)

                opp = OpportunityData(
                    thread_id=thread.id,
                    subreddit=subreddit_name,
                    opportunity_type="comment",
                    thread_title=thread.post_title or "",
                    thread_ups=thread.ups or 0,
                    thread_age_hours=_get_thread_age_hours(thread),
                    comment_count=_estimate_comment_count(thread),
                    visibility=vis,
                    competition=comp,
                    trust_potential=trust,
                    karma_potential=karma,
                    risk=0,
                    strategic_alignment=strat,
                    composite=composite,
                    thread_score_ref=ts,
                )
                opportunities.append(opp)

    # --- Source 2: HobbySubreddit posts (for Phase 0-1 avatars) ---
    if avatar.warming_phase <= 1:
        # Risk-Aware Activation: use zone subs if activation_route exists AND feature enabled
        hobby_sub_names: set[str] = set()
        
        from app.services.settings import get_setting
        _activation_enabled = get_setting(db, "activation_routing_enabled") == "true"
        
        if _activation_enabled and avatar.activation_route:
            from app.services.activation_router import ActivationRouter
            _router = ActivationRouter()
            zone_subs = _router.get_current_zone_subs(avatar)
            hobby_sub_names = {s.lower().removeprefix("r/") for s in zone_subs if s}
        
        # Fallback: get hobby subreddit names from avatar config
        if not hobby_sub_names and avatar.hobby_subreddits:
            if isinstance(avatar.hobby_subreddits, dict):
                for sub_list in avatar.hobby_subreddits.values():
                    if isinstance(sub_list, list):
                        hobby_sub_names.update(s.lower().removeprefix("r/") for s in sub_list)
                    elif isinstance(sub_list, str):
                        hobby_sub_names.add(sub_list.lower().removeprefix("r/"))
            elif isinstance(avatar.hobby_subreddits, list):
                for item in avatar.hobby_subreddits:
                    if isinstance(item, dict):
                        sub_name = item.get("subreddit", "")
                        if sub_name:
                            hobby_sub_names.add(sub_name.lower().removeprefix("r/"))
                    elif isinstance(item, str):
                        hobby_sub_names.add(item.lower().removeprefix("r/"))

        if hobby_sub_names:
            from sqlalchemy import func as sa_func, or_
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            hobby_freshness_cutoff = _dt.now(_tz.utc) - _td(days=7)
            hobby_posts = (
                db.query(HobbySubreddit)
                .filter(
                    HobbySubreddit.avatar_username == avatar.reddit_username,
                    sa_func.lower(HobbySubreddit.subreddit).in_(hobby_sub_names),
                    HobbySubreddit.status == "new",  # fresh posts not yet used
                    HobbySubreddit.ai_comment.is_(None),
                    HobbySubreddit.post_body.isnot(None),
                    # Freshness: only posts from last 7 days
                    HobbySubreddit.created_at >= hobby_freshness_cutoff,
                    # Filter out image/video/link posts - LLM cant see media,
                    # comments on image posts often get locked, and text-only
                    # replies to photo posts look out of place.
                    or_(
                        HobbySubreddit.url.is_(None),
                        HobbySubreddit.url == "",
                        HobbySubreddit.url.like("%reddit.com%"),
                    ),
                )
                .order_by(HobbySubreddit.scraped_at.desc())
                .limit(30)
                .all()
            )

            for hp in hobby_posts:
                if hp.id in existing_hobby_ids:
                    continue

                subreddit_name = hp.subreddit or ""
                karma_avg = _get_subreddit_karma_avg(db, avatar.id, subreddit_name)

                # For hobby posts, use simpler scoring (no ThreadScore)
                # Create a lightweight proxy for thread-like scoring
                vis = _clamp(60)  # Moderate baseline visibility for hobby posts
                comp = _clamp(70)  # Usually less competition in hobby subs
                trust = _clamp(50)  # Moderate trust potential
                karma_score = _clamp(
                    min(100, 15 + (karma_avg / 2.0) * 10 + (hp.post_ups or 0) * 0.5)
                )
                strat = _clamp(30) if avatar.warming_phase <= 1 else _clamp(15)

                scores_dict = {
                    "visibility": vis,
                    "competition": comp,
                    "trust_potential": trust,
                    "karma_potential": karma_score,
                    "strategic_alignment": strat,
                }
                composite = _compute_composite(scores_dict)

                opp = OpportunityData(
                    hobby_post_id=hp.id,
                    subreddit=subreddit_name,
                    opportunity_type="comment",
                    thread_title=hp.post_title or "",
                    thread_ups=hp.post_ups or 0,
                    thread_age_hours=0.0,
                    comment_count=0,
                    visibility=vis,
                    competition=comp,
                    trust_potential=trust,
                    karma_potential=karma_score,
                    risk=0,
                    strategic_alignment=strat,
                    composite=composite,
                    thread_score_ref=None,
                )
                opportunities.append(opp)

    # --- A/B Test: restrict subreddits to configured risk range if avatar in experiment ---
    try:
        from app.services.settings import get_setting

        if get_setting(db, "ab_test_enabled") == "true":
            from app.services.ab_test.control_enforcer import get_allowed_risk_range

            risk_range = get_allowed_risk_range(db, avatar.id)
            if risk_range is not None:
                min_risk, max_risk = risk_range
                from app.models.subreddit_risk_profile import SubredditRiskProfile
                from app.models.subreddit import Subreddit as SubredditModel
                from sqlalchemy import func as _fn

                # Build a set of allowed subreddit names (lowercased) within risk range
                allowed_subs_query = (
                    db.query(_fn.lower(SubredditModel.subreddit_name))
                    .join(
                        SubredditRiskProfile,
                        SubredditRiskProfile.subreddit_id == SubredditModel.id,
                    )
                    .filter(
                        SubredditRiskProfile.risk_score >= min_risk,
                        SubredditRiskProfile.risk_score <= max_risk,
                    )
                    .all()
                )
                allowed_sub_names = {row[0] for row in allowed_subs_query}

                pre_filter_ab = len(opportunities)
                opportunities = [
                    opp for opp in opportunities
                    if (opp.subreddit or "").lower() in allowed_sub_names
                ]
                filtered_ab = pre_filter_ab - len(opportunities)
                if filtered_ab > 0:
                    logger.info(
                        "scan_opportunities: avatar=%s A/B test risk filter removed %d "
                        "opportunities (allowed risk range %d-%d, %d subs allowed)",
                        avatar.reddit_username,
                        filtered_ab,
                        min_risk,
                        max_risk,
                        len(allowed_sub_names),
                    )
    except Exception as e:
        logger.warning(
            "Failed to apply A/B test risk range filter in scan_opportunities: %s",
            str(e)[:200],
        )

    # --- Log market scarcity if fewer than 10 scoreable threads ---

    # --- Filter out banned subreddits ---
    try:
        from app.services.subreddit_ban import get_banned_subreddits
        banned_subs = get_banned_subreddits(db, avatar.id)
        if banned_subs:
            pre_filter = len(opportunities)
            opportunities = [
                opp for opp in opportunities
                if (opp.subreddit or "").lower() not in banned_subs
            ]
            filtered_count = pre_filter - len(opportunities)
            if filtered_count > 0:
                logger.info(
                    "scan_opportunities: avatar=%s filtered %d opportunities from banned subs: %s",
                    avatar.reddit_username, filtered_count, list(banned_subs)[:5],
                )
    except Exception as e:
        logger.warning("Failed to check subreddit bans in scan_opportunities: %s", str(e)[:100])

    # --- Filter out opportunities in dangerous hours ---
    try:
        from app.services.timing_engine import is_safe_posting_time
        from datetime import datetime as _dt_dh, timezone as _tz_dh

        current_hour = _dt_dh.now(_tz_dh.utc).hour
        pre_filter_dh = len(opportunities)
        opportunities = [
            opp for opp in opportunities
            if is_safe_posting_time(opp.subreddit or "", current_hour, db)
        ]
        filtered_dh = pre_filter_dh - len(opportunities)
        if filtered_dh > 0:
            logger.info(
                "scan_opportunities: avatar=%s filtered %d opportunities in dangerous hours (hour=%d)",
                avatar.reddit_username, filtered_dh, current_hour,
            )
    except Exception as e:
        logger.warning("Failed to check dangerous hours in scan_opportunities: %s", str(e)[:100])

    if len(opportunities) < MIN_OPPORTUNITIES_FOR_SCARCITY:
        logger.warning(
            "market_scarcity: avatar=%s found only %d scoreable opportunities (min %d)",
            avatar.reddit_username,
            len(opportunities),
            MIN_OPPORTUNITIES_FOR_SCARCITY,
        )

    # --- Sort by composite descending, cap at MAX_OPPORTUNITIES ---
    opportunities.sort(key=lambda o: o.composite, reverse=True)
    opportunities = opportunities[:MAX_OPPORTUNITIES]

    # --- Persist as Opportunity DB records ---
    result: list[Opportunity] = []
    for opp in opportunities:
        record = Opportunity(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            decision_date=plan_date,
            thread_id=opp.thread_id,
            hobby_post_id=opp.hobby_post_id,
            subreddit=opp.subreddit,
            opportunity_type=opp.opportunity_type,
            visibility_score=opp.visibility,
            competition_score=opp.competition,
            trust_potential_score=opp.trust_potential,
            karma_potential_score=opp.karma_potential,
            risk_score=opp.risk,
            strategic_alignment_score=opp.strategic_alignment,
            composite_score=opp.composite,
            status="evaluated",
        )
        db.add(record)
        result.append(record)

    return result
