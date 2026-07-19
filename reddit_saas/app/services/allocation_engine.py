"""EPG 2.0 — Allocation Engine.

Constructs the optimal portfolio of actions given budget constraints,
risk tolerance, diversification requirements, and strategic alignment.

The Allocation Engine is the final decision-making stage in the EPG 2.0
pipeline. It receives scored opportunities with risk assessments and
expected returns, then selects the best set of actions that fit within
the avatar's daily attention budget while maintaining diversification.

Algorithm:
1. Assign each opportunity to a category (primary/secondary/experimental/community)
2. Compute risk-adjusted return for each opportunity
3. Fill categories within budget allocation (greedy by risk-adjusted return)
4. Enforce diversification: no single subreddit > 40% of actions
5. Reallocate empty categories proportionally to others with viable opportunities
6. Apply timing: distribute selected actions across active hours (08:00-23:00)
7. Compute Shannon entropy diversification metric

Requirements: 5.1, 5.4, 5.5, 5.6, 5.7
"""

from __future__ import annotations

from app.logging_config import get_logger
import math
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.avatar import Avatar
    from app.models.opportunity import Opportunity
    from app.services.portfolio_manager import AttentionBudget, PortfolioAllocation
    from app.services.return_engine import ExpectedReturn
    from app.services.risk_engine import RiskAssessment

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBREDDIT_MAX_SHARE = 0.40  # No single subreddit > 40% of actions
SUBREDDIT_ABSOLUTE_CAP = 1  # Hard limit: max 1 slot per subreddit per avatar per day
ACTIVE_HOURS_START = 8      # 08:00
ACTIVE_HOURS_END = 23       # 23:00
MIN_INTERVAL_MINUTES = 45


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------


@dataclass
class SelectedAction:
    """A selected opportunity with its assigned time slot.

    Attributes:
        opportunity: The Opportunity DB model instance.
        risk_assessment: The RiskAssessment for this opportunity.
        expected_return: The ExpectedReturn for this opportunity.
        category: The portfolio category this was assigned to.
        scheduled_at: The computed posting time (UTC), or None if not yet assigned.
        slot_type: Either "hobby" or "professional".
    """

    opportunity: object  # Opportunity DB model
    risk_assessment: object  # RiskAssessment
    expected_return: object  # ExpectedReturn
    category: str
    scheduled_at: datetime | None
    slot_type: str  # hobby | professional


@dataclass
class AllocationResult:
    """Result of portfolio allocation.

    Attributes:
        selected: List of selected actions with timing and category info.
        rejected: List of (Opportunity, reason_string) tuples for rejected opportunities.
        budget_consumed: Mapping of category → count of selected actions.
        budget_remaining: Mapping of category → remaining slot count.
        diversification_score: Shannon entropy of subreddit distribution.
        reallocation_log: Explanations of any budget reallocation decisions.
    """

    selected: list[SelectedAction] = field(default_factory=list)
    rejected: list[tuple] = field(default_factory=list)  # (Opportunity, reason_string)
    budget_consumed: dict[str, int] = field(default_factory=dict)
    budget_remaining: dict[str, int] = field(default_factory=dict)
    diversification_score: float = 0.0
    reallocation_log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Category Assignment
# ---------------------------------------------------------------------------


def _assign_category(
    opportunity: "Opportunity",
    avatar: "Avatar",
) -> str:
    """Assign an opportunity to a portfolio category.

    Heuristic based on opportunity dimension scores:
    - "community": highest trust_potential_score → helping/discussion
    - "primary": highest strategic_alignment_score → avatar's primary niche
    - "secondary": opportunity in business_subreddits → professional
    - "experimental": low competition_score indicates new territory

    Falls back to "primary" if no clear signal.

    Args:
        opportunity: Opportunity with dimension scores.
        avatar: Avatar with hobby_subreddits, business_subreddits.

    Returns:
        One of: "primary", "secondary", "experimental", "community".
    """
    trust = opportunity.trust_potential_score or 0
    strategic = opportunity.strategic_alignment_score or 0
    competition = opportunity.competition_score or 0
    visibility = opportunity.visibility_score or 0

    subreddit = (opportunity.subreddit or "").lower()

    # Check if subreddit is in avatar's business_subreddits
    business_subs = set()
    if avatar.business_subreddits:
        if isinstance(avatar.business_subreddits, dict):
            # JSONB format: could be {"subreddits": [...]} or {"name": ...}
            for key, val in avatar.business_subreddits.items():
                if isinstance(val, list):
                    business_subs.update(s.lower() for s in val if isinstance(s, str))
                elif isinstance(val, str):
                    business_subs.add(val.lower())
        elif isinstance(avatar.business_subreddits, list):
            business_subs.update(s.lower() for s in avatar.business_subreddits if isinstance(s, str))

    # Check if subreddit is in avatar's hobby_subreddits
    hobby_subs = set()
    if avatar.hobby_subreddits:
        if isinstance(avatar.hobby_subreddits, dict):
            for key, val in avatar.hobby_subreddits.items():
                if isinstance(val, list):
                    hobby_subs.update(s.lower() for s in val if isinstance(s, str))
                elif isinstance(val, str):
                    hobby_subs.add(val.lower())
        elif isinstance(avatar.hobby_subreddits, list):
            hobby_subs.update(s.lower() for s in avatar.hobby_subreddits if isinstance(s, str))

    # Decision logic: pick based on strongest signal
    scores = {
        "community": trust,
        "primary": strategic,
        "secondary": visibility if subreddit in business_subs else 0,
        "experimental": 100 - competition,  # Low competition → experimental
    }

    # If the subreddit is explicitly in business_subreddits, bias towards secondary
    if subreddit in business_subs:
        scores["secondary"] += 30

    # If subreddit is in hobby_subreddits and trust is high, bias community
    if subreddit in hobby_subs and trust >= 50:
        scores["community"] += 20

    # Pick category with highest score
    best_category = max(scores, key=scores.get)  # type: ignore[arg-type]

    return best_category


# ---------------------------------------------------------------------------
# Risk-Adjusted Return Computation
# ---------------------------------------------------------------------------


def _compute_risk_adjusted_return(
    expected_return: "ExpectedReturn",
    risk_assessment: "RiskAssessment",
) -> float:
    """Compute risk-adjusted return for an opportunity.

    Formula: composite / max(1, final_score)

    This ensures opportunities with low risk and high return are
    prioritized. Division by max(1, risk) prevents division by zero.

    Args:
        expected_return: ExpectedReturn with composite score.
        risk_assessment: RiskAssessment with final_score.

    Returns:
        Float representing risk-adjusted return value.
    """
    composite = expected_return.composite
    risk_score = risk_assessment.final_score
    return composite / max(1, risk_score)


# ---------------------------------------------------------------------------
# Diversification Enforcement
# ---------------------------------------------------------------------------


def enforce_subreddit_cap(
    selected: list[SelectedAction],
    max_share: float = SUBREDDIT_MAX_SHARE,
    absolute_cap: int = SUBREDDIT_ABSOLUTE_CAP,
) -> tuple[list[SelectedAction], list[tuple]]:
    """Enforce subreddit diversification with both relative and absolute caps.

    Two constraints applied in order:
    1. Absolute cap: no subreddit gets more than absolute_cap slots (default 2).
    2. Relative cap: no subreddit gets more than max_share fraction of total actions.

    When a subreddit exceeds either cap, drops the lowest risk-adjusted-return
    actions from that subreddit until the constraint is satisfied.

    The relative cap is NOT enforced when there are fewer than 3 selected actions
    or when the avatar has only one subreddit represented.

    Args:
        selected: List of SelectedAction objects.
        max_share: Maximum fraction of actions for any single subreddit.
        absolute_cap: Maximum absolute number of slots per subreddit (default 2).

    Returns:
        Tuple of (filtered_selected, rejected_with_reasons).
    """
    rejected: list[tuple] = []
    result = list(selected)

    # --- Phase 1: Enforce absolute per-subreddit cap ---
    changed = True
    while changed:
        changed = False
        sub_counts: dict[str, int] = {}
        for action in result:
            sub = action.opportunity.subreddit
            sub_counts[sub] = sub_counts.get(sub, 0) + 1

        for sub, count in sub_counts.items():
            if count > absolute_cap:
                # Find actions in this subreddit, sort by risk-adjusted return ascending
                sub_actions = [a for a in result if a.opportunity.subreddit == sub]
                sub_actions.sort(
                    key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment)
                )
                # Drop the lowest until within absolute cap
                excess = count - absolute_cap
                for i in range(excess):
                    action_to_drop = sub_actions[i]
                    result.remove(action_to_drop)
                    rejected.append(
                        (action_to_drop.opportunity, f"subreddit_absolute_cap: {sub} > {absolute_cap}/day")
                    )
                    changed = True
                break  # Recount after modification

    # --- Phase 2: Enforce relative share cap ---
    if len(result) < 3:
        return result, rejected

    # Count subreddits
    subreddit_counts: dict[str, int] = {}
    for action in result:
        sub = action.opportunity.subreddit
        subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1

    # If only one subreddit, can't diversify further
    if len(subreddit_counts) <= 1:
        return result, rejected

    changed = True
    while changed:
        changed = False
        total = len(result)
        if total < 3:
            break

        max_allowed = math.floor(total * max_share)
        # At minimum, allow 1 action per subreddit
        max_allowed = max(max_allowed, 1)

        # Find subreddits over the cap
        sub_counts_2: dict[str, int] = {}
        for action in result:
            sub = action.opportunity.subreddit
            sub_counts_2[sub] = sub_counts_2.get(sub, 0) + 1

        for sub, count in sub_counts_2.items():
            if count > max_allowed:
                # Find actions in this subreddit, sort by risk-adjusted return ascending
                sub_actions = [a for a in result if a.opportunity.subreddit == sub]
                sub_actions.sort(
                    key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment)
                )

                # Drop the lowest until within cap
                excess = count - max_allowed
                for i in range(excess):
                    action_to_drop = sub_actions[i]
                    result.remove(action_to_drop)
                    rejected.append(
                        (action_to_drop.opportunity, f"subreddit_share_cap: {sub} > {int(max_share * 100)}%")
                    )
                    changed = True
                break  # Recount after modification

    return result, rejected


# ---------------------------------------------------------------------------
# Shannon Entropy Diversification
# ---------------------------------------------------------------------------


def compute_diversification(actions: list[SelectedAction]) -> float:
    """Compute Shannon entropy of subreddit distribution among selected actions.

    Higher entropy indicates better diversification.
    Returns 0.0 for 0-1 actions.
    Maximum entropy occurs when actions are uniformly distributed across subreddits.

    Formula: H = -sum(p_i * log2(p_i)) for each subreddit i
    where p_i = count_i / total

    Args:
        actions: List of selected actions.

    Returns:
        Shannon entropy (float >= 0.0).
    """
    if len(actions) <= 1:
        return 0.0

    # Count per subreddit
    sub_counts: dict[str, int] = {}
    for action in actions:
        sub = action.opportunity.subreddit
        sub_counts[sub] = sub_counts.get(sub, 0) + 1

    total = len(actions)
    entropy = 0.0

    for count in sub_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    return entropy


# ---------------------------------------------------------------------------
# Timing Assignment
# ---------------------------------------------------------------------------


def _assign_timing(
    selected: list[SelectedAction],
    avatar: "Avatar",
) -> list[SelectedAction]:
    """Assign deterministic scheduled_at times to selected actions.

    Distributes actions evenly across the active window (08:00-23:00)
    in the avatar's timezone. Uses deterministic spacing for testability.

    The jitter parameter is NOT applied here — actual jitter is applied
    by the timing_engine when slots are dispatched. This provides base
    scheduling times.

    Args:
        selected: List of selected actions to schedule.
        avatar: Avatar with declared_timezone.

    Returns:
        Same list with scheduled_at populated.
    """
    if not selected:
        return selected

    count = len(selected)

    # Use avatar's declared timezone or default
    tz_str = getattr(avatar, "declared_timezone", None) or "America/New_York"

    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(tz_str)
    except (ImportError, KeyError):
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")

    # Use today's date in the avatar's timezone
    now_local = datetime.now(tz)
    start = now_local.replace(hour=ACTIVE_HOURS_START, minute=0, second=0, microsecond=0)
    end = now_local.replace(hour=ACTIVE_HOURS_END, minute=0, second=0, microsecond=0)

    # Active window in minutes: 15 hours = 900 minutes
    window_minutes = (end - start).total_seconds() / 60.0

    # Minimum interval enforcement
    interval = window_minutes / count

    # Enforce minimum interval of 45 minutes
    if interval < MIN_INTERVAL_MINUTES and count > 1:
        interval = MIN_INTERVAL_MINUTES

    for i, action in enumerate(selected):
        offset_minutes = interval * (i + 0.5)  # Center of each time segment
        # Clamp to window
        if offset_minutes >= window_minutes:
            offset_minutes = window_minutes - 1

        scheduled_time = start + timedelta(minutes=offset_minutes)
        action.scheduled_at = scheduled_time.astimezone(timezone.utc)

    return selected


# ---------------------------------------------------------------------------
# Slot Type Assignment
# ---------------------------------------------------------------------------


def _determine_slot_type(category: str, avatar: "Avatar") -> str:
    """Determine slot_type based on category and avatar phase.

    Phase 1 avatars only get "hobby" slots.
    Phase 2+ can get "professional" for secondary/primary categories.

    Args:
        category: The portfolio category (primary/secondary/experimental/community).
        avatar: Avatar with warming_phase.

    Returns:
        "hobby" or "professional".
    """
    phase = getattr(avatar, "warming_phase", 1)

    if phase <= 1:
        return "hobby"

    # Phase 2+: secondary and primary that are strategic → professional
    if category in ("secondary", "primary"):
        return "professional"

    # Community and experimental → hobby
    return "hobby"


# ---------------------------------------------------------------------------
# Main Allocation Function
# ---------------------------------------------------------------------------


def allocate_portfolio(
    opportunities: list,
    risk_assessments: dict[uuid.UUID, "RiskAssessment"],
    expected_returns: dict[uuid.UUID, "ExpectedReturn"],
    budget: "AttentionBudget",
    allocation: "PortfolioAllocation",
    avatar: "Avatar",
) -> AllocationResult:
    """Allocate budget across opportunities using simple top-N selection.

    Algorithm (simplified from over-engineered category-based):
    1. Sort all opportunities by composite_score descending
    2. Select top N (= max_total_actions), respecting max_comments/max_posts
    3. Enforce subreddit diversification (no single sub > 40% or absolute cap 2)
    4. Assign timing across active hours
    5. Compute diversification metric

    The category-based allocation was causing 89-96% rejection rates because
    opportunities clustered in one category with minimal budget allocation.
    Simple top-N by quality fills budget correctly.

    Args:
        opportunities: List of Opportunity objects (already filtered by risk).
        risk_assessments: Dict mapping opportunity.id → RiskAssessment.
        expected_returns: Dict mapping opportunity.id → ExpectedReturn.
        budget: AttentionBudget with max_total_actions, max_comments, max_posts.
        allocation: PortfolioAllocation (preserved for interface compat, categories stored in decision_record).
        avatar: Avatar for timing and slot_type determination.

    Returns:
        AllocationResult with selected actions, rejected, and diversification info.
    """
    result = AllocationResult()
    max_total = budget.max_total_actions

    if max_total <= 0 or not opportunities:
        if not opportunities:
            result.reallocation_log.append("No viable opportunities provided")
        else:
            result.reallocation_log.append("Budget is zero — no actions allowed")
        return result

    # Step 1: Sort by composite_score descending (best opportunities first)
    scored_opps = []
    for opp in opportunities:
        opp_id = opp.id
        risk = risk_assessments.get(opp_id)
        ret = expected_returns.get(opp_id)
        if risk is None or ret is None:
            result.rejected.append((opp, "missing_risk_or_return_data"))
            continue
        scored_opps.append((opp, risk, ret))

    # Sort by composite_score (opportunity's own score), falling back to risk-adjusted return
    scored_opps.sort(
        key=lambda x: (x[0].composite_score or 0, _compute_risk_adjusted_return(x[2], x[1])),
        reverse=True,
    )

    # Step 2: Select top-N respecting comment/post limits
    selected_actions: list[SelectedAction] = []
    comments_count = 0
    posts_count = 0

    for opp, risk, ret in scored_opps:
        if len(selected_actions) >= max_total:
            break

        # Determine slot type based on source
        is_hobby = opp.hobby_post_id is not None
        is_post = getattr(opp, 'opportunity_type', 'comment') == 'post'

        if is_post:
            if posts_count >= budget.max_posts:
                result.rejected.append((opp, "max_posts_exceeded"))
                continue
            posts_count += 1
            slot_type = "post"
        else:
            if comments_count >= budget.max_comments:
                result.rejected.append((opp, "max_comments_exceeded"))
                continue
            comments_count += 1
            slot_type = "hobby" if is_hobby or avatar.warming_phase <= 1 else "professional"

        # Determine category for record-keeping (cosmetic, doesn't affect selection)
        category = "primary"
        if is_hobby:
            category = "community"
        elif slot_type == "professional":
            category = "secondary"

        action = SelectedAction(
            opportunity=opp,
            risk_assessment=risk,
            expected_return=ret,
            category=category,
            scheduled_at=None,
            slot_type=slot_type,
        )
        selected_actions.append(action)

    # Mark remaining as rejected
    selected_ids = {a.opportunity.id for a in selected_actions}
    for opp, risk, ret in scored_opps:
        if opp.id not in selected_ids:
            already_rejected = any(r[0].id == opp.id for r in result.rejected if hasattr(r[0], 'id'))
            if not already_rejected:
                result.rejected.append((opp, "below_budget_cutoff"))

    # Step 3: Enforce diversification (subreddit cap)
    selected_actions, cap_rejected = enforce_subreddit_cap(selected_actions)
    result.rejected.extend(cap_rejected)

    # Step 4: Assign timing
    selected_actions = _assign_timing(selected_actions, avatar)

    # Step 5: Compute diversification score
    result.diversification_score = compute_diversification(selected_actions)

    # Step 6: Build budget info (simplified — no per-category breakdown)
    for cat in allocation.categories:
        consumed = sum(1 for a in selected_actions if a.category == cat)
        result.budget_consumed[cat] = consumed
        result.budget_remaining[cat] = 0

    result.selected = selected_actions

    logger.info(
        "Portfolio allocation complete: %d selected (comments=%d, posts=%d), "
        "%d rejected, diversification=%.3f, budget=%d",
        len(selected_actions), comments_count, posts_count,
        len(result.rejected),
        result.diversification_score,
        max_total,
    )

    return result
