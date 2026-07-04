"""Zone Evaluator — checks graduation and demotion criteria for activation zones.

Runs daily at 06:00 alongside phase evaluation. Determines if an avatar
qualifies to advance from safe→bridge or bridge→target based on karma,
survival rate, and compatibility metrics.

No LLM calls — purely DB-driven. Evaluation < 500ms per avatar.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.logging_config import get_logger

if TYPE_CHECKING:
    from app.models.avatar import Avatar

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Graduation Criteria
# ---------------------------------------------------------------------------

GRADUATION_CRITERIA = {
    "safe_to_bridge": {
        "min_karma": 10,          # total comment karma
        "min_survival_rate": 0.90,
        "min_age_days": 7,        # account age
        "min_posted": 3,          # comments posted in safe zone
        "max_deleted": 0,         # zero deletions allowed
        "cqs_not": "lowest",
    },
    "bridge_to_target": {
        "min_bridge_subs_with_karma": 2,   # karma > 0 in at least 2 bridge subs
        "min_karma_per_bridge_sub": 15,    # minimum karma in qualifying bridge subs
        "min_survival_rate": 0.85,
        "min_total_karma": 50,
        "min_compatibility_score": 60,      # avg compatibility with target subs
    },
}

# Minimum sample size for survival rate calculation (same as phase demotion)
MIN_SAMPLE_SIZE = 5

# Survival rate threshold for zone demotion
DEMOTION_SURVIVAL_THRESHOLD = 0.70


def evaluate_zone_graduation(db: Session, avatar: "Avatar") -> str | None:
    """Check if avatar qualifies for zone graduation.

    Returns: new zone name ("bridge" or "target") if graduating, None otherwise.
    """
    route = avatar.activation_route
    if not route:
        return None

    current_zone = route.get("current_zone", "safe")

    if current_zone == "safe":
        if _meets_safe_to_bridge(db, avatar, route):
            return "bridge"
    elif current_zone == "bridge":
        if _meets_bridge_to_target(db, avatar, route):
            return "target"

    # target zone — no further graduation (Phase 2+ takes over)
    return None


def should_demote_zone(db: Session, avatar: "Avatar") -> str | None:
    """Check if avatar should be demoted within its current zone.

    Returns: reason string if demotion needed, None otherwise.
    """
    route = avatar.activation_route
    if not route:
        return None

    current_zone = route.get("current_zone", "safe")

    # Can't demote from safe zone
    if current_zone == "safe":
        return None

    # Check survival rate in current zone
    zone_subs = route.get(f"{current_zone}_subs", [])
    if not zone_subs:
        return None

    survival = _compute_zone_survival_rate(db, avatar, zone_subs)
    if survival is None:
        return None  # not enough data

    if survival < DEMOTION_SURVIVAL_THRESHOLD:
        return f"survival_rate_{survival:.0%}_below_{DEMOTION_SURVIVAL_THRESHOLD:.0%}"

    return None


# ---------------------------------------------------------------------------
# Private: Safe → Bridge criteria
# ---------------------------------------------------------------------------


def _meets_safe_to_bridge(db: Session, avatar: "Avatar", route: dict) -> bool:
    """Check safe→bridge graduation criteria."""
    criteria = GRADUATION_CRITERIA["safe_to_bridge"]

    # 1. Total karma >= 10
    total_karma = (avatar.karma_comment or 0) + (avatar.reddit_karma_comment or 0)
    if total_karma < criteria["min_karma"]:
        return False

    # 2. CQS not lowest
    if avatar.cqs_level == criteria["cqs_not"]:
        return False

    # 3. Account age >= 7 days
    if avatar.reddit_account_created:
        age_days = (datetime.now(timezone.utc) - avatar.reddit_account_created).days
        if age_days < criteria["min_age_days"]:
            return False
    else:
        # No account creation date — be conservative, require at least 7 days since avatar created
        if avatar.created_at:
            created = avatar.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_days = (datetime.now(timezone.utc) - created).days
            if age_days < criteria["min_age_days"]:
                return False

    # 4. >= 3 posted comments in safe zone subs, 0 deleted
    safe_subs = route.get("safe_subs", [])
    posted, deleted = _count_zone_comments(db, avatar, safe_subs)

    if posted < criteria["min_posted"]:
        return False
    if deleted > criteria["max_deleted"]:
        return False

    # 5. Survival rate >= 90% (with min sample size)
    if posted < MIN_SAMPLE_SIZE:
        return False  # not enough data yet
    survival = (posted - deleted) / posted if posted > 0 else 0
    if survival < criteria["min_survival_rate"]:
        return False

    return True


# ---------------------------------------------------------------------------
# Private: Bridge → Target criteria
# ---------------------------------------------------------------------------


def _meets_bridge_to_target(db: Session, avatar: "Avatar", route: dict) -> bool:
    """Check bridge→target graduation criteria."""
    criteria = GRADUATION_CRITERIA["bridge_to_target"]
    bridge_subs = route.get("bridge_subs", [])
    target_subs = route.get("target_subs", [])

    if not bridge_subs:
        return False

    # 1. Karma >= 15 in at least 2 bridge subs
    from app.models.subreddit_karma import SubredditKarma

    bridge_lower = [s.lower() for s in bridge_subs]
    karma_records = (
        db.query(SubredditKarma)
        .filter(
            SubredditKarma.avatar_id == avatar.id,
            sa_func.lower(SubredditKarma.subreddit_name).in_(bridge_lower),
        )
        .all()
    )

    qualifying_subs = sum(
        1 for kr in karma_records
        if kr.comment_karma >= criteria["min_karma_per_bridge_sub"]
    )
    if qualifying_subs < criteria["min_bridge_subs_with_karma"]:
        return False

    # 2. Total karma >= 50
    total_karma = (avatar.karma_comment or 0) + (avatar.reddit_karma_comment or 0)
    if total_karma < criteria["min_total_karma"]:
        return False

    # 3. Survival rate >= 85% in bridge zone (with min sample size)
    survival = _compute_zone_survival_rate(db, avatar, bridge_subs)
    if survival is None:
        return False  # not enough data
    if survival < criteria["min_survival_rate"]:
        return False

    # 4. Compatibility score >= 60 for target subs (average)
    if target_subs:
        from app.models.avatar_subreddit_compatibility import AvatarSubredditCompatibility

        target_lower = [s.lower() for s in target_subs]
        compat_scores = (
            db.query(AvatarSubredditCompatibility.score)
            .filter(
                AvatarSubredditCompatibility.avatar_id == avatar.id,
                sa_func.lower(AvatarSubredditCompatibility.subreddit_name).in_(target_lower),
            )
            .all()
        )

        if compat_scores:
            avg_compat = sum(row[0] for row in compat_scores) / len(compat_scores)
            if avg_compat < criteria["min_compatibility_score"]:
                return False
        # If no compatibility data exists, skip this check (fail-open for data availability)

    return True


# ---------------------------------------------------------------------------
# Private: Shared helpers
# ---------------------------------------------------------------------------


def _count_zone_comments(
    db: Session, avatar: "Avatar", zone_subs: list[str]
) -> tuple[int, int]:
    """Count posted and deleted comments in the given zone subreddits.

    Returns: (total_posted, total_deleted) in last 14 days.
    """
    from app.models.comment_draft import CommentDraft
    from app.models.hobby import HobbySubreddit

    if not zone_subs:
        return 0, 0

    zone_lower = {s.lower() for s in zone_subs}
    cutoff = datetime.now(timezone.utc) - timedelta(days=14)

    # Professional drafts (have thread → subreddit)
    from app.models.thread import RedditThread
    pro_drafts = (
        db.query(CommentDraft)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id, isouter=True)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.status == "posted",
            CommentDraft.created_at >= cutoff,
        )
        .all()
    )

    posted = 0
    deleted = 0
    for draft in pro_drafts:
        sub_name = ""
        if draft.thread_id and hasattr(draft, "thread") and draft.thread:
            sub_name = (draft.thread.subreddit or "").lower()
        elif draft.hobby_post_id:
            # Resolve via hobby_post relationship
            if hasattr(draft, "hobby_post") and draft.hobby_post:
                sub_name = (draft.hobby_post.subreddit or "").lower()

        if sub_name in zone_lower:
            posted += 1
            if getattr(draft, "is_deleted", False):
                deleted += 1

    return posted, deleted


def _compute_zone_survival_rate(
    db: Session, avatar: "Avatar", zone_subs: list[str]
) -> float | None:
    """Compute survival rate for comments in given zone subs.

    Returns None if insufficient data (< MIN_SAMPLE_SIZE).
    """
    posted, deleted = _count_zone_comments(db, avatar, zone_subs)
    if posted < MIN_SAMPLE_SIZE:
        return None
    return (posted - deleted) / posted


def run_zone_evaluation_for_avatar(db: Session, avatar: "Avatar") -> dict:
    """Run full zone evaluation for a single avatar.

    Returns dict with action taken (graduated/demoted/none).
    """
    from app.services.activation_router import ActivationRouter

    route = avatar.activation_route
    if not route:
        return {"action": "none", "reason": "no_route"}

    router = ActivationRouter()

    # Check demotion first (safety first)
    demotion_reason = should_demote_zone(db, avatar)
    if demotion_reason:
        router.demote_zone(db, avatar, demotion_reason)
        return {"action": "demoted", "reason": demotion_reason}

    # Check graduation
    new_zone = evaluate_zone_graduation(db, avatar)
    if new_zone:
        router.graduate(db, avatar, new_zone)
        return {"action": "graduated", "to_zone": new_zone}

    return {"action": "none", "reason": "criteria_not_met"}
