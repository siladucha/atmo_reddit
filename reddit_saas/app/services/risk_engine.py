"""EPG 2.0 — Risk Engine.

Evaluates risk for each potential engagement opportunity based on avatar state,
community state, and historical patterns. Produces a detailed RiskAssessment
with factor breakdown and flags.

Risk Factors:
- account_age_factor (0-25): younger accounts face higher risk
- karma_factor (0-20): lower karma means less tolerance for mistakes
- frequency_factor (0-20): high posting frequency increases detection risk
- moderation_factor (0-30): subreddit moderation sensitivity / historical removals
- content_type_factor (0-15): brand mentions carry higher risk than neutral content

Modifiers:
- health_modifier: +20 for "warned" or "suspicious" health status
- phase_multiplier: 2.0 for Phase 1 (applied to frequency + moderation factors)
- removal_feedback_adjustment: +5 per removal event for avatar-subreddit pair (capped at 30)

Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 8.3, 13.6
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.models.avatar import Avatar

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------


@dataclass
class RiskAssessment:
    """Detailed risk breakdown for an opportunity.

    Contains individual factor scores, modifiers, and the final composite
    risk score clamped to [0, 100].

    Attributes:
        base_score: Sum of raw factor scores before modifiers (0-100).
        account_age_factor: Risk from young account (0-25).
        karma_factor: Risk from low karma (0-20).
        frequency_factor: Risk from high posting frequency (0-20).
        moderation_factor: Risk from subreddit moderation sensitivity (0-30).
        content_type_factor: Risk from brand/promotional content (0-15).
        health_modifier: +20 if avatar health is warned/suspicious, else 0.
        phase_multiplier: 2.0 for Phase 1, 1.5 for Phase 2, 1.0 for Phase 3.
        final_score: Composite score after all modifiers, clamped [0, 100].
        flags: List of risk flags (e.g., "high_risk", "critical_risk").
    """

    base_score: int
    account_age_factor: int
    karma_factor: int
    frequency_factor: int
    moderation_factor: int
    content_type_factor: int
    health_modifier: int
    phase_multiplier: float
    final_score: int
    flags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Phase Multiplier Mapping
# ---------------------------------------------------------------------------

_PHASE_MULTIPLIERS: dict[int, float] = {
    0: 2.0,  # Mentor — treated like Phase 1
    1: 2.0,  # Phase 1: highest caution
    2: 1.5,  # Phase 2: moderate caution
    3: 1.0,  # Phase 3: established, normal weighting
}


# ---------------------------------------------------------------------------
# Factor Computation Helpers
# ---------------------------------------------------------------------------


def _compute_account_age_factor(avatar: "Avatar") -> int:
    """Compute risk from account age (0-25).

    Newer accounts face higher scrutiny from Reddit's systems.

    Thresholds:
        <30 days: 25 (very risky)
        30-90 days: 15
        90-180 days: 8
        >180 days: 3
    """
    if avatar.reddit_account_created is None:
        # Unknown age — assume moderate risk
        return 15

    now = datetime.now(timezone.utc)
    account_created = avatar.reddit_account_created
    # Ensure timezone-aware comparison
    if account_created.tzinfo is None:
        account_created = account_created.replace(tzinfo=timezone.utc)

    age_days = (now - account_created).days

    if age_days < 30:
        return 25
    elif age_days < 90:
        return 15
    elif age_days < 180:
        return 8
    else:
        return 3


def _compute_karma_factor(avatar: "Avatar") -> int:
    """Compute risk from low karma (0-20).

    Low-karma accounts have less tolerance for mistakes and are
    more likely to be flagged by Reddit's anti-spam systems.

    Uses total karma (post + comment) from the avatar model.

    Thresholds:
        <100 karma: 20
        100-500: 12
        500-2000: 6
        >2000: 2
    """
    # Use reddit_karma_comment + reddit_karma_post if available,
    # fall back to karma_post + karma_comment
    total_karma = (avatar.reddit_karma_comment or 0) + (avatar.reddit_karma_post or 0)
    if total_karma == 0:
        # Fall back to legacy fields
        total_karma = (avatar.karma_comment or 0) + (avatar.karma_post or 0)

    if total_karma < 100:
        return 20
    elif total_karma < 500:
        return 12
    elif total_karma < 2000:
        return 6
    else:
        return 2


def _compute_frequency_factor(activity_24h: int) -> int:
    """Compute risk from posting frequency in last 24h (0-20).

    Higher posting frequency increases the risk of detection by
    Reddit's anti-spam systems.

    Uses the activity_24h value from community_state.

    Thresholds:
        0 posts: 0
        1-3 posts: 5
        4-7 posts: 12
        >7 posts: 20
    """
    if activity_24h <= 0:
        return 0
    elif activity_24h <= 3:
        return 5
    elif activity_24h <= 7:
        return 12
    else:
        return 20


def _compute_moderation_factor(community_state: dict) -> int:
    """Compute risk from subreddit moderation sensitivity (0-30).

    If the avatar has 3+ removals in the last 30 days for this
    avatar-subreddit pair, the factor is maxed at 30.

    Otherwise, it's proportional to the removal rate.

    Additionally applies removal_feedback_adjustment from historical
    removal events tracked via the Opportunity model (requirement 13.6).
    Each past removal adds +5 risk points (capped at 30 total adjustment).

    Args:
        community_state: Dict with keys including:
            - removal_count_30d: int (removals in last 30 days)
            - risk_adjustment: int (accumulated removal feedback, 0-30)

    Returns:
        Integer risk factor clamped to [0, 30].
    """
    removal_count = community_state.get("removal_count_30d", 0)
    risk_adjustment = community_state.get("risk_adjustment", 0)

    if removal_count >= 3:
        base = 30
    else:
        # Proportional: each removal contributes 10 points (capped at 30)
        # For 0-2 removals: 0, 10, 20
        base = min(30, removal_count * 10)

    # Add removal feedback adjustment (5% per historical removal event, capped at 30)
    total = base + risk_adjustment
    return min(30, total)


def _compute_content_type_factor(opportunity) -> int:
    """Compute risk from content type (0-15).

    Brand mentions carry the highest risk, professional/expertise
    content is moderate, and hobby/neutral content is lowest.

    Determines content type from the opportunity's attributes:
    - If opportunity has strategic_alignment score > 70 and is in a
      business subreddit context, treat as brand_mention
    - If opportunity_type involves professional content, treat as expertise
    - Otherwise, treat as hobby/neutral

    Args:
        opportunity: An opportunity object with score and type information.

    Returns:
        Integer risk factor: 15 (brand), 8 (professional), 3 (hobby/neutral).
    """
    # Detect brand/professional content from opportunity attributes
    opp_type = getattr(opportunity, "opportunity_type", "comment")
    score = getattr(opportunity, "score", None)

    # Check if this is brand-related content
    # High strategic alignment (>70) + specific type patterns suggest brand content
    if score is not None:
        strategic = getattr(score, "strategic_alignment", 0)
        if strategic > 70:
            return 15  # brand_mention content

    # Check opportunity_type or other signals for professional content
    # "post" type is typically more professional/branded
    if opp_type == "post":
        return 8  # professional/expertise

    # Default: hobby/neutral content (comments, replies)
    return 3


# ---------------------------------------------------------------------------
# Health Modifier
# ---------------------------------------------------------------------------


def _compute_health_modifier(avatar: "Avatar") -> int:
    """Compute health modifier (+20 for warned/suspicious, else 0).

    When an avatar's health status indicates it's under scrutiny,
    all opportunities carry additional risk.

    Args:
        avatar: Avatar with health_status field.

    Returns:
        20 if health_status is "warned" or "suspicious", else 0.
    """
    health_status = getattr(avatar, "health_status", "unknown")
    if health_status in ("warned", "suspicious"):
        return 20
    return 0


# ---------------------------------------------------------------------------
# Phase Multiplier
# ---------------------------------------------------------------------------


def _get_phase_multiplier(avatar: "Avatar") -> float:
    """Get phase multiplier for risk weight adjustment.

    Phase 1 (and Mentor/Phase 0) avatars have risk factors weighted 2x
    for frequency and moderation dimensions. Phase 2 uses 1.5x, Phase 3
    uses 1.0x (no adjustment).

    Args:
        avatar: Avatar with warming_phase field.

    Returns:
        Float multiplier (2.0, 1.5, or 1.0).
    """
    phase = getattr(avatar, "warming_phase", 1)
    # Clamp to known range
    if phase < 0:
        phase = 0
    elif phase > 3:
        phase = 3
    return _PHASE_MULTIPLIERS.get(phase, 1.0)


# ---------------------------------------------------------------------------
# Main Risk Assessment Function
# ---------------------------------------------------------------------------


def assess_risk(
    opportunity,
    avatar: "Avatar",
    community_state: dict,
) -> RiskAssessment:
    """Compute risk score for an opportunity.

    Evaluates multiple risk dimensions and applies modifiers based on
    avatar health and warming phase.

    Score computation:
    1. Compute individual factors: account_age, karma, frequency,
       moderation, content_type
    2. Apply phase_multiplier to frequency and moderation factors
    3. Sum all factors to get base_score
    4. Add health_modifier
    5. Clamp final_score to [0, 100]
    6. Set flags based on final_score thresholds

    Args:
        opportunity: An opportunity object (from opportunity_engine).
        avatar: The avatar being evaluated.
        community_state: Dict with subreddit context:
            - subreddit: str
            - removal_count_30d: int
            - activity_24h: int
            - topic_saturation: bool
            - last_mod_action: str | None

    Returns:
        RiskAssessment with full factor breakdown and flags.
    """
    # Compute individual factors
    account_age_factor = _compute_account_age_factor(avatar)
    karma_factor = _compute_karma_factor(avatar)

    # Frequency factor uses activity_24h from community_state
    activity_24h = community_state.get("activity_24h", 0)
    frequency_factor = _compute_frequency_factor(activity_24h)

    # Moderation factor from community state
    moderation_factor = _compute_moderation_factor(community_state)

    # Content type factor from opportunity
    content_type_factor = _compute_content_type_factor(opportunity)

    # Get phase multiplier
    phase_multiplier = _get_phase_multiplier(avatar)

    # Apply phase multiplier ONLY to frequency and moderation factors
    adjusted_frequency = int(round(frequency_factor * phase_multiplier))
    adjusted_moderation = int(round(moderation_factor * phase_multiplier))

    # Clamp adjusted factors to their original max ranges scaled by multiplier
    # frequency max is 20, moderation max is 30 — after multiplier they can exceed
    # but we let them exceed for base_score calculation (final is clamped to 100)
    adjusted_frequency = min(adjusted_frequency, 40)  # 20 * 2.0 max
    adjusted_moderation = min(adjusted_moderation, 60)  # 30 * 2.0 max

    # Compute base score (sum of all factors including adjusted ones)
    base_score = (
        account_age_factor
        + karma_factor
        + adjusted_frequency
        + adjusted_moderation
        + content_type_factor
    )

    # Clamp base_score to [0, 100]
    base_score = max(0, min(100, base_score))

    # Compute health modifier
    health_modifier = _compute_health_modifier(avatar)

    # Final score = base + health modifier, clamped to [0, 100]
    final_score = min(100, base_score + health_modifier)
    final_score = max(0, final_score)

    # Determine flags
    flags: list[str] = []
    if final_score > 90:
        flags.append("critical_risk")
    if final_score > 70:
        flags.append("high_risk")

    return RiskAssessment(
        base_score=base_score,
        account_age_factor=account_age_factor,
        karma_factor=karma_factor,
        frequency_factor=frequency_factor,
        moderation_factor=moderation_factor,
        content_type_factor=content_type_factor,
        health_modifier=health_modifier,
        phase_multiplier=phase_multiplier,
        final_score=final_score,
        flags=flags,
    )


# ---------------------------------------------------------------------------
# Historical Removal Rate (Requirement 2.4)
# ---------------------------------------------------------------------------


def compute_historical_removal_rate(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
    window_days: int = 90,
) -> float:
    """Compute ratio of removed posts to total posts for avatar-subreddit pair.

    Queries CommentDraft records that have been posted (status='posted') for the
    given avatar in the specified subreddit within the lookback window. Uses the
    `is_deleted` flag to determine removals.

    Args:
        db: SQLAlchemy database session.
        avatar_id: The avatar's UUID.
        subreddit: Subreddit name (e.g., "python", "cybersecurity").
        window_days: Number of days to look back (default 90).

    Returns:
        Float between 0.0 and 1.0 representing the removal rate.
        Returns 0.0 if no posted drafts exist in the window.

    Requirements: 2.4
    """
    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread

    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Query posted drafts for this avatar-subreddit pair within the time window.
    # Join through RedditThread to filter by subreddit (denormalized field).
    base_query = (
        db.query(CommentDraft)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= cutoff,
            RedditThread.subreddit == subreddit,
        )
    )

    total_count = base_query.count()

    if total_count == 0:
        return 0.0

    removed_count = base_query.filter(CommentDraft.is_deleted == True).count()  # noqa: E712

    return removed_count / total_count


# ---------------------------------------------------------------------------
# Risk Filtering (Requirement 2.5)
# ---------------------------------------------------------------------------


def filter_by_risk(
    opportunities: list,
    risk_assessments: dict[uuid.UUID, "RiskAssessment"],
    acceptable_risk_level: int,
) -> tuple[list, list[tuple]]:
    """Partition opportunities into viable and rejected based on risk threshold.

    An opportunity is viable if its risk score is <= the acceptable_risk_level
    threshold. An opportunity is rejected if its risk score exceeds the threshold.

    For rejected opportunities, a reason string is included explaining why.

    Args:
        opportunities: List of opportunity objects (with `.id` UUID attribute).
        risk_assessments: Dict mapping opportunity UUID → RiskAssessment.
        acceptable_risk_level: Integer threshold (0-100). Scores at exactly
            the threshold are considered viable (not rejected).

    Returns:
        Tuple of (viable_opportunities, rejected_with_reasons) where:
        - viable_opportunities: list of opportunities with risk_score <= threshold
        - rejected_with_reasons: list of (opportunity, reason_string) tuples

    Requirements: 2.5
    """
    viable: list = []
    rejected: list[tuple] = []

    for opportunity in opportunities:
        opp_id = opportunity.id
        assessment = risk_assessments.get(opp_id)

        if assessment is None:
            # No risk assessment available — treat as viable (conservative default:
            # don't reject without evaluation). Log a warning.
            logger.warning(
                "No risk assessment found for opportunity %s — including as viable",
                opp_id,
            )
            viable.append(opportunity)
            continue

        score = assessment.final_score

        if score <= acceptable_risk_level:
            viable.append(opportunity)
        else:
            reason = (
                f"risk_score {score} exceeds threshold {acceptable_risk_level}"
            )
            rejected.append((opportunity, reason))

    return viable, rejected


# ---------------------------------------------------------------------------
# Removal Feedback — Risk Weight Adjustment (Requirement 13.6)
# ---------------------------------------------------------------------------

# Maximum accumulated risk adjustment from removal feedback (cap)
_MAX_REMOVAL_RISK_ADJUSTMENT = 30

# Points added per removal event
_REMOVAL_RISK_ADJUSTMENT_PER_EVENT = 5


def get_removal_risk_adjustment(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
) -> int:
    """Get accumulated risk weight adjustment for an avatar-subreddit pair.

    Queries the Opportunity model for records where actual_removal=True
    for this avatar-subreddit pair. Each removal adds 5 risk points,
    capped at 30 total.

    This implements requirement 13.6: when a removal is detected, the
    moderation_sensitivity risk weight increases by 5% for future
    evaluations of that avatar-subreddit pair.

    Args:
        db: SQLAlchemy database session.
        avatar_id: The avatar's UUID.
        subreddit: Subreddit name (e.g., "python").

    Returns:
        Integer risk adjustment (0-30), representing accumulated
        removal feedback for this avatar-subreddit pair.
    """
    from app.models.opportunity import Opportunity as OpportunityModel

    removal_count = (
        db.query(OpportunityModel)
        .filter(
            OpportunityModel.avatar_id == avatar_id,
            OpportunityModel.subreddit == subreddit,
            OpportunityModel.actual_removal == True,  # noqa: E712
        )
        .count()
    )

    adjustment = removal_count * _REMOVAL_RISK_ADJUSTMENT_PER_EVENT
    return min(_MAX_REMOVAL_RISK_ADJUSTMENT, adjustment)


def apply_removal_feedback(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
    opportunity_id: uuid.UUID,
) -> int:
    """Record a removal event and return the new risk adjustment.

    Called when actual_removal=True is detected on an opportunity.
    Sets the actual_removal flag on the opportunity record (if not
    already set) and returns the updated accumulated adjustment.

    This is the write-side of the removal feedback loop. The read-side
    is get_removal_risk_adjustment(), which is called during risk
    assessment via _gather_community_state.

    Args:
        db: SQLAlchemy database session.
        avatar_id: The avatar's UUID.
        subreddit: Subreddit name.
        opportunity_id: The opportunity UUID that was removed.

    Returns:
        The updated accumulated risk adjustment (0-30) for this
        avatar-subreddit pair after recording the removal.

    Requirements: 13.6
    """
    from app.models.opportunity import Opportunity as OpportunityModel

    # Mark the opportunity as removed (if not already)
    opp = (
        db.query(OpportunityModel)
        .filter(OpportunityModel.id == opportunity_id)
        .first()
    )
    if opp and not opp.actual_removal:
        opp.actual_removal = True
        db.flush()
        logger.info(
            "Removal feedback recorded: avatar=%s subreddit=%s opportunity=%s",
            avatar_id,
            subreddit,
            opportunity_id,
        )

    # Return the new accumulated adjustment
    return get_removal_risk_adjustment(db, avatar_id, subreddit)
