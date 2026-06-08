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

import logging
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

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBREDDIT_MAX_SHARE = 0.40  # No single subreddit > 40% of actions
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
) -> tuple[list[SelectedAction], list[tuple]]:
    """Enforce no single subreddit receives > max_share of actions.

    When a subreddit exceeds the cap, drops the lowest risk-adjusted-return
    actions from that subreddit until the constraint is satisfied.

    Does NOT enforce the cap when there are fewer than 3 selected actions
    (at 2 actions, a single subreddit at 50% could still be the best choice)
    or when the avatar has only one subreddit represented.

    Args:
        selected: List of SelectedAction objects.
        max_share: Maximum fraction of actions for any single subreddit.

    Returns:
        Tuple of (filtered_selected, rejected_with_reasons).
    """
    if len(selected) < 3:
        return selected, []

    # Count subreddits
    subreddit_counts: dict[str, int] = {}
    for action in selected:
        sub = action.opportunity.subreddit
        subreddit_counts[sub] = subreddit_counts.get(sub, 0) + 1

    # If only one subreddit, can't diversify further
    if len(subreddit_counts) <= 1:
        return selected, []

    rejected: list[tuple] = []
    result = list(selected)

    # Iteratively enforce the cap
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
        sub_counts: dict[str, int] = {}
        for action in result:
            sub = action.opportunity.subreddit
            sub_counts[sub] = sub_counts.get(sub, 0) + 1

        for sub, count in sub_counts.items():
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
                        (action_to_drop.opportunity, f"subreddit_cap_exceeded: {sub} > {int(max_share * 100)}%")
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
    """Allocate budget across categories using greedy optimization.

    Algorithm:
    1. Assign each opportunity to its best-matching category
    2. For each category (by allocation %), pick top opportunities
       by risk-adjusted return (composite / risk_score)
    3. Enforce diversification: no single subreddit > 40% of actions
    4. Reallocate empty categories proportionally to others
    5. Apply timing via deterministic spacing across active hours
    6. Compute Shannon entropy diversification metric

    Args:
        opportunities: List of Opportunity objects (already filtered by risk threshold).
        risk_assessments: Dict mapping opportunity.id → RiskAssessment.
        expected_returns: Dict mapping opportunity.id → ExpectedReturn.
        budget: AttentionBudget with max_total_actions, max_comments, max_posts.
        allocation: PortfolioAllocation with categories dict (category → percentage).
        avatar: Avatar for category assignment and timing.

    Returns:
        AllocationResult with selected actions, rejected, budget info,
        diversification score, and reallocation log.
    """
    result = AllocationResult()
    max_total = budget.max_total_actions

    if max_total <= 0 or not opportunities:
        # Nothing to allocate
        for cat in allocation.categories:
            result.budget_consumed[cat] = 0
            result.budget_remaining[cat] = 0
        if not opportunities:
            result.reallocation_log.append("No viable opportunities provided")
        else:
            result.reallocation_log.append("Budget is zero — no actions allowed")
        return result

    # Step 1: Assign opportunities to categories and compute risk-adjusted return
    categorized: dict[str, list[tuple[object, float]]] = {
        cat: [] for cat in allocation.categories
    }

    for opp in opportunities:
        opp_id = opp.id
        risk = risk_assessments.get(opp_id)
        ret = expected_returns.get(opp_id)

        if risk is None or ret is None:
            result.rejected.append((opp, "missing_risk_or_return_data"))
            continue

        category = _assign_category(opp, avatar)

        # If the category isn't in the allocation, assign to the closest match
        if category not in categorized:
            # Default to "primary" as fallback
            category = "primary" if "primary" in categorized else next(iter(categorized))

        risk_adjusted = _compute_risk_adjusted_return(ret, risk)
        categorized[category].append((opp, risk_adjusted))

    # Sort each category by risk-adjusted return descending
    for cat in categorized:
        categorized[cat].sort(key=lambda x: x[1], reverse=True)

    # Step 2: Compute slots per category from budget allocation
    slots_per_category: dict[str, int] = {}
    total_allocated = 0

    for cat, percentage in allocation.categories.items():
        slots = math.floor(max_total * percentage / 100)
        slots_per_category[cat] = slots
        total_allocated += slots

    # Distribute remaining slots (due to floor rounding) to highest-percentage categories
    remaining_from_floor = max_total - total_allocated
    if remaining_from_floor > 0:
        sorted_cats = sorted(allocation.categories.items(), key=lambda x: x[1], reverse=True)
        for i in range(remaining_from_floor):
            cat = sorted_cats[i % len(sorted_cats)][0]
            slots_per_category[cat] += 1

    # Step 3: Identify empty categories and reallocate
    empty_categories: list[str] = []
    slots_to_redistribute = 0

    for cat, slots in slots_per_category.items():
        if not categorized.get(cat):
            # No viable opportunities in this category
            empty_categories.append(cat)
            slots_to_redistribute += slots
            slots_per_category[cat] = 0

    if empty_categories and slots_to_redistribute > 0:
        # Find non-empty categories with viable opportunities
        viable_cats = [
            cat for cat in slots_per_category
            if cat not in empty_categories and categorized.get(cat)
        ]

        if viable_cats:
            # Distribute proportionally based on their original allocation percentages
            viable_total_pct = sum(allocation.categories.get(cat, 0) for cat in viable_cats)

            if viable_total_pct > 0:
                distributed = 0
                for i, cat in enumerate(viable_cats):
                    cat_pct = allocation.categories.get(cat, 0)
                    share = math.floor(slots_to_redistribute * cat_pct / viable_total_pct)
                    slots_per_category[cat] += share
                    distributed += share

                # Remainder goes to first viable category
                remainder = slots_to_redistribute - distributed
                if remainder > 0:
                    slots_per_category[viable_cats[0]] += remainder
            else:
                # Equal distribution
                per_cat = slots_to_redistribute // len(viable_cats)
                remainder = slots_to_redistribute % len(viable_cats)
                for i, cat in enumerate(viable_cats):
                    slots_per_category[cat] += per_cat + (1 if i < remainder else 0)

            result.reallocation_log.append(
                f"Empty categories {empty_categories} had {slots_to_redistribute} slots "
                f"redistributed to {viable_cats}"
            )
        else:
            result.reallocation_log.append(
                f"Empty categories {empty_categories} could not be redistributed — "
                "no viable alternatives"
            )

    # Step 4: Greedy selection within each category
    selected_actions: list[SelectedAction] = []
    all_selected_opp_ids: set[uuid.UUID] = set()

    for cat, max_slots in slots_per_category.items():
        if max_slots <= 0:
            continue

        candidates = categorized.get(cat, [])
        filled = 0

        for opp, risk_adj in candidates:
            if filled >= max_slots:
                break
            if opp.id in all_selected_opp_ids:
                continue  # Already selected in another category

            risk = risk_assessments[opp.id]
            ret = expected_returns[opp.id]
            slot_type = _determine_slot_type(cat, avatar)

            action = SelectedAction(
                opportunity=opp,
                risk_assessment=risk,
                expected_return=ret,
                category=cat,
                scheduled_at=None,
                slot_type=slot_type,
            )
            selected_actions.append(action)
            all_selected_opp_ids.add(opp.id)
            filled += 1

    # Step 5: Enforce budget hard ceiling
    # Enforce max_total_actions
    if len(selected_actions) > max_total:
        # Sort all by risk-adjusted return, keep top N
        selected_actions.sort(
            key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment),
            reverse=True,
        )
        excess = selected_actions[max_total:]
        selected_actions = selected_actions[:max_total]
        for action in excess:
            result.rejected.append(
                (action.opportunity, "budget_ceiling_exceeded")
            )

    # Enforce max_comments and max_posts limits
    comments_count = sum(1 for a in selected_actions if a.opportunity.opportunity_type in ("comment", "reply"))
    posts_count = sum(1 for a in selected_actions if a.opportunity.opportunity_type == "post")

    if comments_count > budget.max_comments:
        # Remove lowest risk-adjusted-return comment actions
        comment_actions = [a for a in selected_actions if a.opportunity.opportunity_type in ("comment", "reply")]
        comment_actions.sort(
            key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment)
        )
        excess_count = comments_count - budget.max_comments
        for i in range(excess_count):
            action_to_drop = comment_actions[i]
            selected_actions.remove(action_to_drop)
            result.rejected.append(
                (action_to_drop.opportunity, "max_comments_exceeded")
            )

    if posts_count > budget.max_posts:
        post_actions = [a for a in selected_actions if a.opportunity.opportunity_type == "post"]
        post_actions.sort(
            key=lambda a: _compute_risk_adjusted_return(a.expected_return, a.risk_assessment)
        )
        excess_count = posts_count - budget.max_posts
        for i in range(excess_count):
            action_to_drop = post_actions[i]
            selected_actions.remove(action_to_drop)
            result.rejected.append(
                (action_to_drop.opportunity, "max_posts_exceeded")
            )

    # Step 6: Enforce diversification (subreddit cap)
    selected_actions, cap_rejected = enforce_subreddit_cap(selected_actions)
    result.rejected.extend(cap_rejected)

    # Step 7: Assign timing
    selected_actions = _assign_timing(selected_actions, avatar)

    # Step 8: Compute diversification score
    result.diversification_score = compute_diversification(selected_actions)

    # Step 9: Build budget consumption/remaining info
    for cat in allocation.categories:
        consumed = sum(1 for a in selected_actions if a.category == cat)
        result.budget_consumed[cat] = consumed
        result.budget_remaining[cat] = max(0, slots_per_category.get(cat, 0) - consumed)

    # Step 10: Mark remaining opportunities as rejected
    for cat, candidates in categorized.items():
        for opp, _ in candidates:
            if opp.id not in all_selected_opp_ids:
                # Check if already in rejected list
                already_rejected = any(r[0].id == opp.id for r in result.rejected if hasattr(r[0], 'id'))
                if not already_rejected:
                    result.rejected.append(
                        (opp, f"not_selected: lower risk-adjusted return in category '{cat}'")
                    )

    result.selected = selected_actions

    logger.info(
        "Portfolio allocation complete: %d selected, %d rejected, "
        "diversification=%.3f, categories=%s",
        len(selected_actions),
        len(result.rejected),
        result.diversification_score,
        {cat: result.budget_consumed.get(cat, 0) for cat in allocation.categories},
    )

    return result
