"""Comment Approach Diversity Service.

Ensures avatars don't repeat the same comment_approach monotonously.
Selects the next approach based on:
1. Recent approach history (least-used gets priority)
2. Avatar's subreddit karma (high karma → bolder approaches, low karma → safer ones)
3. Hard constraint: no more than 2 consecutive uses of the same approach

The avatar's identity (voice, personality) stays constant — only the
engagement *technique* rotates. Think of it as a skilled communicator
choosing different rhetorical tools while staying true to their character.
"""

from app.logging_config import get_logger
from collections import Counter

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft

logger = get_logger(__name__)

# All available approaches (from generation prompt)
ALL_APPROACHES = [
    "reframe_drop",
    "cynical_deconstruction",
    "the_scar",
    "contrarian",
    "drive_by",
]

# Approach risk tiers: how "bold" each approach is.
# High-karma avatars can use bold approaches freely.
# Low-karma avatars should prefer safe approaches to build credibility.
APPROACH_TIERS = {
    "safe": ["reframe_drop", "the_scar"],          # Agreeable, relatable — good for building karma
    "moderate": ["contrarian", "drive_by"],         # Opinionated but brief — needs some credibility
    "bold": ["cynical_deconstruction"],             # Confrontational — needs established presence
}

# Karma thresholds for approach tier access
KARMA_THRESHOLD_MODERATE = 50    # Need 50+ karma in subreddit for moderate approaches
KARMA_THRESHOLD_BOLD = 200       # Need 200+ karma in subreddit for bold approaches


def select_approach_for_avatar(
    db: Session,
    avatar: Avatar,
    subreddit: str,
    subreddit_karma: int = 0,
    max_consecutive: int = 2,
    history_window: int = 20,
) -> str | None:
    """Select the next comment_approach for an avatar, enforcing diversity.

    Returns:
        The approach string to inject as a constraint into the generation prompt,
        or None if no constraint needed (let LLM choose freely — only when
        history is too short to detect patterns).
    """
    # Get recent approach history for this avatar
    recent_approaches = (
        db.query(CommentDraft.comment_approach)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.comment_approach.isnot(None),
            CommentDraft.status.in_(["posted", "approved", "pending"]),
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(history_window)
        .all()
    )
    history = [r[0] for r in recent_approaches if r[0]]

    # If not enough history, don't constrain — let LLM explore
    if len(history) < 3:
        return None

    # Determine which approaches are available based on subreddit karma
    available = _get_available_approaches(subreddit_karma)

    # Count approach frequency in recent history
    counter = Counter(history)

    # Rule 1: Block consecutive repetition (no more than max_consecutive in a row)
    blocked_consecutive = None
    if len(history) >= max_consecutive:
        last_n = history[:max_consecutive]
        if len(set(last_n)) == 1:
            # Last N were all the same approach — block it
            blocked_consecutive = last_n[0]

    # Rule 2: Find least-used approach from available set
    # Score each approach: lower count = higher priority
    candidates = []
    for approach in available:
        if approach == blocked_consecutive:
            continue  # Blocked by consecutive rule
        count = counter.get(approach, 0)
        candidates.append((approach, count))

    if not candidates:
        # All approaches blocked — fallback to any available except the blocked one
        candidates = [(a, counter.get(a, 0)) for a in available if a != blocked_consecutive]

    if not candidates:
        # Extreme edge case — just return None and let LLM decide
        return None

    # Sort by count (ascending) — least used first
    candidates.sort(key=lambda x: x[1])

    # Pick the least-used approach
    selected = candidates[0][0]

    logger.debug(
        "approach_diversity: avatar=%s subreddit=r/%s karma=%d selected=%s "
        "history=%s blocked_consecutive=%s",
        avatar.reddit_username,
        subreddit,
        subreddit_karma,
        selected,
        dict(counter),
        blocked_consecutive,
    )

    return selected


def _get_available_approaches(subreddit_karma: int) -> list[str]:
    """Determine which approaches an avatar can use based on subreddit karma.

    Low karma → only safe approaches (build credibility first).
    Medium karma → safe + moderate.
    High karma → all approaches available.
    """
    available = list(APPROACH_TIERS["safe"])

    if subreddit_karma >= KARMA_THRESHOLD_MODERATE:
        available.extend(APPROACH_TIERS["moderate"])

    if subreddit_karma >= KARMA_THRESHOLD_BOLD:
        available.extend(APPROACH_TIERS["bold"])

    return available


def format_approach_constraint(approach: str) -> str:
    """Format the approach constraint for injection into the generation prompt.

    Returns a string to be appended to the system prompt that forces the LLM
    to use a specific approach.
    """
    return (
        f"\n## MANDATORY APPROACH CONSTRAINT\n"
        f"You MUST use comment_approach: \"{approach}\" for this comment.\n"
        f"This is a hard requirement for diversity — do NOT override.\n"
        f"Your voice and personality stay the same, only the rhetorical technique changes.\n"
    )
