"""EPG 2.0 — Return Engine.

Estimates multi-dimensional expected returns for each opportunity that
passes risk assessment. Returns are computed across five dimensions:
karma, trust, visibility, influence, and strategic_value.

The Return Engine sits between the Risk Engine and the Allocation Engine
in the portfolio pipeline. It consumes Opportunity DB model instances
(with scores already computed by the Opportunity Engine) and produces
ExpectedReturn dataclass instances used by the Allocation Engine to
select the highest-value actions.

Scoring dimensions:
- Karma (int >= 0): predicted karma gain from engagement
- Trust (0-100): contribution to avatar trust/credibility
- Visibility (0-100): how much the action increases avatar visibility
- Influence (0-100): potential to provoke discussion or be referenced
- Strategic_Value (0-100): contribution to client strategic goals
- Composite (0-100): normalized weighted sum of all 5 dimensions
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from app.models.opportunity import Opportunity as OpportunityModel

if TYPE_CHECKING:
    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.models.opportunity import Opportunity
    from app.services.portfolio_manager import ReturnWeights

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp(value: int | float, low: int = 0, high: int = 100) -> int:
    """Clamp a numeric value to [low, high] integer range."""
    return max(low, min(high, int(round(value))))


# ---------------------------------------------------------------------------
# Karma Multiplier (Model Correction)
# ---------------------------------------------------------------------------


def get_subreddit_karma_multiplier(
    db: Session,
    avatar_id: uuid.UUID,
    subreddit: str,
) -> float:
    """Get karma prediction multiplier adjusted by correction events.

    Queries historical opportunities for this avatar-subreddit pair where
    outcome data is available, then adjusts a base multiplier of 1.0 based
    on consistent over/under-performance patterns.

    Starts at 1.0. Increases by 10% for consistent over-performance
    (5+ actions where actual karma > 150% of predicted). Decreases by 10%
    for consistent under-performance (5+ actions where actual karma < 50%
    of predicted). Both adjustments can apply simultaneously.

    Clamped to [0.5, 2.0].

    Args:
        db: SQLAlchemy database session.
        avatar_id: UUID of the avatar.
        subreddit: Subreddit name to check performance history for.

    Returns:
        Float multiplier in range [0.5, 2.0]. Returns 1.0 if no data available.
    """
    # Query opportunities with outcome data for this avatar-subreddit pair
    opportunities = (
        db.query(OpportunityModel)
        .filter(
            OpportunityModel.avatar_id == avatar_id,
            OpportunityModel.subreddit == subreddit,
            OpportunityModel.actual_karma.isnot(None),
            OpportunityModel.expected_return.isnot(None),
        )
        .all()
    )

    if not opportunities:
        return 1.0

    over_performance_count = 0
    under_performance_count = 0

    for opp in opportunities:
        # Extract expected karma from the JSONB field
        expected_return = opp.expected_return
        if not isinstance(expected_return, dict):
            continue

        expected_karma = expected_return.get("karma")
        if expected_karma is None:
            continue

        # Coerce to numeric, skip if invalid
        try:
            expected_karma = int(expected_karma)
        except (TypeError, ValueError):
            continue

        # Avoid division by zero: treat expected_karma of 0 as 1
        if expected_karma <= 0:
            expected_karma = 1

        actual_karma = opp.actual_karma  # Already confirmed not None by filter

        # Check for over-performance: actual > 150% of predicted
        if actual_karma > expected_karma * 1.5:
            over_performance_count += 1

        # Check for under-performance: actual < 50% of predicted
        if actual_karma < expected_karma * 0.5:
            under_performance_count += 1

    # Start at 1.0 and apply adjustments
    multiplier = 1.0

    if over_performance_count >= 5:
        multiplier *= 1.1

    if under_performance_count >= 5:
        multiplier *= 0.9

    # Clamp to [0.5, 2.0]
    return max(0.5, min(2.0, multiplier))


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class ExpectedReturn:
    """Multi-dimensional return estimate for an opportunity.

    Attributes:
        karma: Expected karma gain (integer >= 0).
        trust: Trust/credibility contribution (0-100).
        visibility: Visibility increase potential (0-100).
        influence: Discussion provocation / authority impact (0-100).
        strategic_value: Client strategic goal alignment (0-100).
        composite: Weighted sum of all dimensions (0-100).
    """

    karma: int
    trust: int
    visibility: int
    influence: int
    strategic_value: int
    composite: int

    def to_dict(self) -> dict:
        """Serialize to dictionary for JSONB storage."""
        return {
            "karma": self.karma,
            "trust": self.trust,
            "visibility": self.visibility,
            "influence": self.influence,
            "strategic_value": self.strategic_value,
            "composite": self.composite,
        }


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------


def compute_expected_karma(
    opportunity: "Opportunity",
    avatar: "Avatar",
    subreddit_avg_karma: float,
    karma_multiplier: float,
) -> int:
    """Predict karma gain using a simple regression model.

    The model uses:
    - Historical average karma in subreddit as base
    - Position bonus for fresh threads (< 3h, < 10 comments)
    - Velocity bonus for high-engagement threads
    - Phase adjustment (Phase 3 avatars have reputation effect)
    - Karma multiplier from model correction feedback loop

    Args:
        opportunity: Opportunity DB model instance with score attributes.
        avatar: Avatar with warming_phase, karma_comment.
        subreddit_avg_karma: Historical average karma per comment for
            this avatar in this subreddit. 0.0 if unknown.
        karma_multiplier: Correction multiplier from feedback loop
            (default 1.0, range [0.5, 2.0]).

    Returns:
        Non-negative integer representing expected karma gain.
    """
    # Use subreddit average or a default baseline of 3.0
    base = subreddit_avg_karma if subreddit_avg_karma > 0 else 3.0

    # Apply the karma multiplier from model correction
    base = base * karma_multiplier

    # --- Position bonus: fresh threads with few comments ---
    # Infer freshness from opportunity scores:
    # karma_potential_score > 70 implies fresh + low comments (from opportunity_engine logic)
    # We use thread metadata indirectly via the opportunity's composite data
    # The opportunity model stores karma_potential_score which factors in position.
    karma_potential = opportunity.karma_potential_score or 0
    if karma_potential >= 70:
        # Strong first-mover advantage → +50% base
        base *= 1.50
    elif karma_potential >= 50:
        # Moderate position advantage → +25% base
        base *= 1.25

    # --- Velocity bonus: high engagement thread ---
    # visibility_score > 70 typically indicates a hot, fresh thread
    visibility = opportunity.visibility_score or 0
    if visibility >= 75:
        # High visibility / hot thread → +30% base
        base *= 1.30
    elif visibility >= 55:
        # Moderate visibility → +15% base
        base *= 1.15

    # --- Phase adjustment: Phase 3 avatars have reputation effect ---
    phase = avatar.warming_phase
    if phase >= 3:
        # Established reputation → +20% karma (community trusts them)
        base *= 1.20
    elif phase == 2:
        # Building reputation → +10%
        base *= 1.10

    # Floor at 0 (can't expect negative karma from a good opportunity)
    result = max(0, int(round(base)))

    return result


def _compute_trust_score(opportunity: "Opportunity", avatar: "Avatar") -> int:
    """Compute expected trust contribution (0-100).

    Based on:
    - Expertise demonstration potential (from trust_potential_score)
    - Helping opportunity (trust_potential_score high → helping context)
    - Dialogue potential (competition_score → room for engagement)

    The opportunity's trust_potential_score already captures topic
    alignment and expertise opportunity. We enhance it with additional
    factors for the return dimension.

    Args:
        opportunity: Opportunity with trust_potential_score, competition_score.
        avatar: Avatar with warming_phase.

    Returns:
        Integer score clamped to [0, 100].
    """
    # Base from opportunity's trust_potential_score (0-100)
    trust_base = opportunity.trust_potential_score or 0

    # Dialogue potential bonus: lower competition = more room for engagement
    competition = opportunity.competition_score or 0
    # High competition score means LOW competition (inverse in opportunity_engine)
    # So high competition_score → good for trust building (fewer voices, more visibility)
    if competition >= 70:
        dialogue_bonus = 15
    elif competition >= 50:
        dialogue_bonus = 10
    elif competition >= 30:
        dialogue_bonus = 5
    else:
        dialogue_bonus = 0

    # Phase factor: Phase 1 avatars build trust faster from hobby engagement
    phase = avatar.warming_phase
    if phase <= 1:
        phase_bonus = 5  # Hobby engagement builds initial trust
    elif phase >= 3:
        phase_bonus = -5  # Phase 3 has established trust; marginal gains are smaller
    else:
        phase_bonus = 0

    score = trust_base * 0.75 + dialogue_bonus + phase_bonus

    return _clamp(score)


def _compute_visibility_score(opportunity: "Opportunity") -> int:
    """Compute expected visibility contribution (0-100).

    Based on:
    - Sub size factor (from visibility_score)
    - Thread position (from karma_potential_score → early = visible)
    - Cross-post potential (from strategic_alignment_score → broader appeal)

    Args:
        opportunity: Opportunity with visibility_score, karma_potential_score,
            strategic_alignment_score.

    Returns:
        Integer score clamped to [0, 100].
    """
    # Primary factor: opportunity's visibility_score captures sub size + freshness
    vis_base = opportunity.visibility_score or 0

    # Thread position bonus: high karma_potential implies early entry
    karma_potential = opportunity.karma_potential_score or 0
    if karma_potential >= 70:
        position_bonus = 10
    elif karma_potential >= 50:
        position_bonus = 5
    else:
        position_bonus = 0

    # Cross-post potential: high strategic alignment suggests broader relevance
    strategic = opportunity.strategic_alignment_score or 0
    if strategic >= 70:
        cross_post_bonus = 10
    elif strategic >= 50:
        cross_post_bonus = 5
    else:
        cross_post_bonus = 0

    score = vis_base * 0.70 + position_bonus + cross_post_bonus

    return _clamp(score)


def _compute_influence_score(opportunity: "Opportunity") -> int:
    """Compute expected influence contribution (0-100).

    Based on:
    - Discussion provocation potential (trust_potential_score → discussion intent)
    - Authority proximity (strategic_alignment_score → near influential topics)
    - Thread engagement level (competition inverse → room for impact)

    Args:
        opportunity: Opportunity with trust_potential_score,
            strategic_alignment_score, competition_score.

    Returns:
        Integer score clamped to [0, 100].
    """
    # Discussion provocation: trust_potential captures dialogue depth potential
    trust = opportunity.trust_potential_score or 0

    # Authority proximity: strategic alignment indicates nearness to authority topics
    strategic = opportunity.strategic_alignment_score or 0

    # Room for impact: high competition_score = low competition = more room
    competition = opportunity.competition_score or 0

    # Weighted combination
    # Discussion provocation: 40%, Authority proximity: 35%, Room for impact: 25%
    score = trust * 0.40 + strategic * 0.35 + competition * 0.25

    return _clamp(score)


def _compute_strategic_value_score(
    opportunity: "Opportunity", avatar: "Avatar", client: "Client | None"
) -> int:
    """Compute expected strategic value contribution (0-100).

    Based on:
    - Entity linking support (strategic_alignment_score → client goal proximity)
    - Phase strategy fit (how well this aligns with current phase goals)

    Args:
        opportunity: Opportunity with strategic_alignment_score.
        avatar: Avatar with warming_phase.
        client: Optional client for strategy context.

    Returns:
        Integer score clamped to [0, 100].
    """
    # Primary: opportunity's strategic_alignment_score already captures
    # client keyword matching, niche relevance, and phase appropriateness
    strategic_base = opportunity.strategic_alignment_score or 0

    # Phase strategy fit adjustment
    phase = avatar.warming_phase

    if phase <= 1:
        # Phase 1: strategic value comes from community building, not brand
        # Reduce raw strategic score (which may factor in brand keywords)
        # but boost if trust_potential is high (community engagement)
        trust = opportunity.trust_potential_score or 0
        score = strategic_base * 0.50 + trust * 0.30
    elif phase == 2:
        # Phase 2: expertise seeding — strategic value from topic authority
        score = strategic_base * 0.80
    else:
        # Phase 3+: full strategic value from brand integration
        score = strategic_base * 1.0

    # Client context bonus: if client exists, strategic actions are more valuable
    if client is not None:
        score += 5

    return _clamp(score)


def _compute_composite(
    karma: int,
    trust: int,
    visibility: int,
    influence: int,
    strategic_value: int,
    weights: "ReturnWeights",
) -> int:
    """Compute composite score as normalized weighted sum.

    Maps karma to a 0-100 scale for weighting purposes, then computes
    the weighted sum using normalized weights.

    Args:
        karma: Expected karma (integer >= 0).
        trust: Trust score (0-100).
        visibility: Visibility score (0-100).
        influence: Influence score (0-100).
        strategic_value: Strategic value score (0-100).
        weights: ReturnWeights with normalized property.

    Returns:
        Integer composite score clamped to [0, 100].
    """
    normalized = weights.normalized

    # Normalize karma to 0-100 scale for composite computation
    # Use a logarithmic scale: karma of 1→20, 5→50, 10→70, 20→85, 50+→100
    if karma <= 0:
        karma_normalized = 0
    elif karma <= 1:
        karma_normalized = 20
    elif karma <= 5:
        karma_normalized = 20 + (karma - 1) / 4.0 * 30  # 1→5 maps to 20→50
    elif karma <= 10:
        karma_normalized = 50 + (karma - 5) / 5.0 * 20  # 5→10 maps to 50→70
    elif karma <= 20:
        karma_normalized = 70 + (karma - 10) / 10.0 * 15  # 10→20 maps to 70→85
    elif karma <= 50:
        karma_normalized = 85 + (karma - 20) / 30.0 * 15  # 20→50 maps to 85→100
    else:
        karma_normalized = 100

    composite = (
        karma_normalized * normalized["karma"]
        + trust * normalized["trust"]
        + visibility * normalized["visibility"]
        + influence * normalized["influence"]
        + strategic_value * normalized["strategic_value"]
    )

    return _clamp(composite)


def estimate_returns(
    opportunity: "Opportunity",
    avatar: "Avatar",
    client: "Client | None",
    weights: "ReturnWeights",
    subreddit_karma_multiplier: float = 1.0,
) -> ExpectedReturn:
    """Estimate expected multi-dimensional return for an opportunity.

    Computes five return dimensions plus a weighted composite score.
    This is the main entry point called by the portfolio manager for
    each opportunity that passes risk assessment.

    Args:
        opportunity: Opportunity DB model instance with all score fields populated.
        avatar: Avatar with warming_phase, karma data.
        client: Optional Client for strategy context.
        weights: ReturnWeights for composite computation.
        subreddit_karma_multiplier: Model correction multiplier for karma
            predictions (default 1.0, range [0.5, 2.0]).

    Returns:
        ExpectedReturn with all dimensions computed and composite score.
    """
    # Get subreddit average karma from the opportunity's karma_potential_score
    # The karma_potential_score already factors in historical average,
    # but we need a raw average for the karma regression model.
    # Use a heuristic: map karma_potential_score to an estimated average.
    # Score 0-30 → avg ~1-2, 30-60 → avg ~3-5, 60-80 → avg ~5-10, 80-100 → avg ~10-20
    karma_score = opportunity.karma_potential_score or 0
    if karma_score <= 30:
        subreddit_avg = 1.0 + (karma_score / 30.0) * 1.0
    elif karma_score <= 60:
        subreddit_avg = 2.0 + ((karma_score - 30) / 30.0) * 3.0
    elif karma_score <= 80:
        subreddit_avg = 5.0 + ((karma_score - 60) / 20.0) * 5.0
    else:
        subreddit_avg = 10.0 + ((karma_score - 80) / 20.0) * 10.0

    # 1. Karma estimation
    karma = compute_expected_karma(
        opportunity, avatar, subreddit_avg, subreddit_karma_multiplier
    )

    # 2. Trust estimation
    trust = _compute_trust_score(opportunity, avatar)

    # 3. Visibility estimation
    visibility = _compute_visibility_score(opportunity)

    # 4. Influence estimation
    influence = _compute_influence_score(opportunity)

    # 5. Strategic value estimation
    strategic_value = _compute_strategic_value_score(opportunity, avatar, client)

    # 6. Composite score
    composite = _compute_composite(
        karma, trust, visibility, influence, strategic_value, weights
    )

    return ExpectedReturn(
        karma=karma,
        trust=trust,
        visibility=visibility,
        influence=influence,
        strategic_value=strategic_value,
        composite=composite,
    )
