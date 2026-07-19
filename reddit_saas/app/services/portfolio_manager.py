"""EPG 2.0 — Attention Portfolio Manager.

Orchestrates daily attention budget allocation for each avatar.
Replaces the thread-selection logic in build_daily_epg() with a
multi-stage investment decision engine.

This module defines configuration dataclasses and the main
build_portfolio() entry point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.models.avatar import Avatar
    from app.models.client import Client
    from app.services.epg import EPGResult


# ---------------------------------------------------------------------------
# Configuration Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AttentionBudget:
    """Daily attention budget for an avatar.

    Defines the maximum number of actions an avatar can take in a day,
    derived from warming phase and optionally capped by client plan limits.

    Attributes:
        max_comments: Maximum comment actions per day.
        max_posts: Maximum post actions per day.
        max_total_actions: Hard ceiling on all actions (comments + posts).
        acceptable_risk_level: Risk score threshold (0-100); opportunities
            with risk above this value are excluded.
    """

    max_comments: int
    max_posts: int
    max_total_actions: int
    acceptable_risk_level: int  # 0-100 threshold

    # Phase budget defaults: (max_comments, max_posts, acceptable_risk_level)
    _PHASE_DEFAULTS: dict[int, tuple[int, int, int]] = field(
        default_factory=lambda: {
            0: (3, 0, 40),   # Mentor — treated like Phase 1
            1: (3, 0, 75),   # Phase 1: credibility building (hobby only, higher risk tolerance)
            2: (7, 2, 60),   # Phase 2: content seeding
            3: (12, 3, 75),  # Phase 3: brand integration
        },
        init=False,
        repr=False,
    )

    @classmethod
    def from_avatar(cls, avatar: "Avatar", client: Optional["Client"] = None) -> "AttentionBudget":
        """Derive budget from avatar warming phase and optional client caps.

        Phase 0 (Mentor) is treated identically to Phase 1 for budget
        purposes — mentors shouldn't normally be in EPG, but we handle
        them gracefully.

        If a client has max_comments_per_month set, the effective daily
        budget is capped via apply_monthly_cap() logic (caller should
        invoke that separately with actual remaining/days values).

        Args:
            avatar: The avatar to compute budget for.
            client: Optional client for plan-level constraints.

        Returns:
            AttentionBudget with phase-appropriate limits.
        """
        # Mentor pool — should never reach EPG, but safety check
        if avatar.pool == "mentor":
            return cls(
                max_comments=0, max_posts=0, max_total_actions=0,
                acceptable_risk_level=0,
            )

        phase = avatar.warming_phase
        # Clamp unknown phases to nearest known boundary
        if phase < 0:
            phase = 0
        elif phase > 3:
            phase = 3

        defaults = {
            0: (1, 0, 40),   # Phase 0 (Incubation): 1 comment/day, no posts
            1: (3, 0, 75),   # Phase 1: hobby only, higher risk tolerance needed
            2: (7, 2, 60),
            3: (12, 3, 75),
        }

        max_comments, max_posts, acceptable_risk = defaults[phase]

        # CQS safety: reduce budget for lowest-quality avatars
        # CQS=lowest means Reddit itself considers this account low quality.
        # Full stop: no EPG slots, no tasks, no emails. Avatar needs organic
        # activity or appeal before re-entering pipeline.
        cqs_level = getattr(avatar, 'cqs_level', None)
        if cqs_level == 'lowest':
            max_comments = 0
            max_posts = 0
        elif cqs_level == 'low' and phase <= 1:
            max_comments = min(max_comments, 2)
            max_posts = 0

        max_total_actions = max_comments + max_posts

        return cls(
            max_comments=max_comments,
            max_posts=max_posts,
            max_total_actions=max_total_actions,
            acceptable_risk_level=acceptable_risk,
        )

    def apply_monthly_cap(self, remaining_monthly: int, days_remaining: int) -> "AttentionBudget":
        """Reduce daily budget if monthly plan cap is approaching.

        Computes effective daily allowance as:
            effective_daily = min(phase_daily, ceil(remaining / days_remaining))

        This prevents burning through the monthly allowance too early.

        Args:
            remaining_monthly: Actions remaining in the monthly billing period.
            days_remaining: Calendar days left in the billing period (>= 1).

        Returns:
            A new AttentionBudget with reduced limits if the monthly cap
            constrains below phase defaults. Original instance is not mutated.
        """
        if days_remaining < 1:
            days_remaining = 1

        if remaining_monthly <= 0:
            # Monthly budget exhausted — zero everything
            return AttentionBudget(
                max_comments=0,
                max_posts=0,
                max_total_actions=0,
                acceptable_risk_level=self.acceptable_risk_level,
            )

        effective_daily = math.ceil(remaining_monthly / days_remaining)

        new_total = min(self.max_total_actions, effective_daily)
        # Proportionally reduce comments and posts while keeping ratio
        if self.max_total_actions > 0:
            ratio_comments = self.max_comments / self.max_total_actions
            ratio_posts = self.max_posts / self.max_total_actions
        else:
            ratio_comments = 1.0
            ratio_posts = 0.0

        new_comments = min(self.max_comments, math.ceil(new_total * ratio_comments))
        new_posts = min(self.max_posts, math.ceil(new_total * ratio_posts))

        # Ensure total doesn't exceed the computed cap
        new_comments = min(new_comments, new_total)
        new_posts = min(new_posts, max(0, new_total - new_comments))

        return AttentionBudget(
            max_comments=new_comments,
            max_posts=new_posts,
            max_total_actions=new_total,
            acceptable_risk_level=self.acceptable_risk_level,
        )


@dataclass
class ReturnWeights:
    """Configurable weights for Expected Return computation.

    Weights are integers that represent relative importance. They are
    normalized to sum to 1.0 when used in composite score computation.

    Default weights: karma=20, trust=25, visibility=20, influence=15,
    strategic_value=20 (total=100).

    Attributes:
        karma: Weight for expected karma gain.
        trust: Weight for trust/credibility contribution.
        visibility: Weight for visibility/reach potential.
        influence: Weight for influence/discussion impact.
        strategic_value: Weight for client strategic goal alignment.
    """

    karma: int = 20
    trust: int = 25
    visibility: int = 20
    influence: int = 15
    strategic_value: int = 20

    @classmethod
    def from_client(cls, client: Optional["Client"]) -> "ReturnWeights":
        """Load custom weights from client config or use defaults.

        Reads from client.return_weights JSONB field. If the client is
        None or the field is empty/invalid, returns default weights.

        Args:
            client: Optional client with return_weights JSONB.

        Returns:
            ReturnWeights instance with client-specific or default values.
        """
        if client is None:
            return cls()

        weights_data = getattr(client, "return_weights", None)
        if not weights_data or not isinstance(weights_data, dict):
            return cls()

        # Extract known fields, falling back to defaults for missing keys
        try:
            return cls(
                karma=int(weights_data.get("karma", 20)),
                trust=int(weights_data.get("trust", 25)),
                visibility=int(weights_data.get("visibility", 20)),
                influence=int(weights_data.get("influence", 15)),
                strategic_value=int(weights_data.get("strategic_value", 20)),
            )
        except (TypeError, ValueError):
            return cls()

    @property
    def normalized(self) -> dict[str, float]:
        """Return weights normalized so they sum to 1.0.

        If all weights are zero, returns equal distribution (0.2 each).

        Returns:
            Dictionary mapping dimension name to its normalized weight.
        """
        total = self.karma + self.trust + self.visibility + self.influence + self.strategic_value

        if total == 0:
            return {
                "karma": 0.2,
                "trust": 0.2,
                "visibility": 0.2,
                "influence": 0.2,
                "strategic_value": 0.2,
            }

        return {
            "karma": self.karma / total,
            "trust": self.trust / total,
            "visibility": self.visibility / total,
            "influence": self.influence / total,
            "strategic_value": self.strategic_value / total,
        }


@dataclass
class PortfolioAllocation:
    """Topic category distribution for the daily budget.

    Defines how the attention budget is spread across content categories.
    Each category receives a percentage of the total budget, and all
    percentages must sum to 100.

    Attributes:
        categories: Mapping of category_name → percentage (integers, sum=100).
        preset: Name of the allocation preset used.
    """

    categories: dict[str, int]
    preset: str = "balanced"  # balanced | aggressive_growth | conservative | custom

    # Preset definitions
    _PRESETS: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            "balanced": {
                "primary": 50,
                "secondary": 30,
                "experimental": 10,
                "community": 10,
            },
            "aggressive_growth": {
                "primary": 40,
                "secondary": 20,
                "experimental": 25,
                "community": 15,
            },
            "conservative": {
                "primary": 60,
                "secondary": 25,
                "experimental": 5,
                "community": 10,
            },
        },
        init=False,
        repr=False,
    )

    @classmethod
    def from_avatar_profile(
        cls, avatar: "Avatar", client: Optional["Client"] = None
    ) -> "PortfolioAllocation":
        """Derive allocation from avatar niche profile and client strategy.

        Selects a preset based on avatar phase:
        - Phase 1: conservative (low-risk, primary-focused)
        - Phase 2: balanced (diversified growth)
        - Phase 3: aggressive_growth (maximize returns)
        - Phase 0 (Mentor): conservative (same as Phase 1)

        If a client has a custom allocation configured, that takes
        precedence (future extension point).

        Args:
            avatar: Avatar to derive allocation for.
            client: Optional client for custom allocation override.

        Returns:
            PortfolioAllocation with appropriate category distribution.
        """
        presets = {
            "balanced": {
                "primary": 50,
                "secondary": 30,
                "experimental": 10,
                "community": 10,
            },
            "aggressive_growth": {
                "primary": 40,
                "secondary": 20,
                "experimental": 25,
                "community": 15,
            },
            "conservative": {
                "primary": 60,
                "secondary": 25,
                "experimental": 5,
                "community": 10,
            },
        }

        phase = avatar.warming_phase

        if phase <= 1:
            preset_name = "conservative"
        elif phase == 2:
            preset_name = "balanced"
        else:
            preset_name = "aggressive_growth"

        return cls(
            categories=dict(presets[preset_name]),
            preset=preset_name,
        )

    def validate(self) -> bool:
        """Ensure all category percentages sum to 100.

        Returns:
            True if categories sum to exactly 100, False otherwise.
        """
        if not self.categories:
            return False
        return sum(self.categories.values()) == 100


@dataclass
class PortfolioConfig:
    """Configuration for a single portfolio allocation run.

    Bundles all inputs needed by the allocation pipeline for one avatar
    on one day.

    Attributes:
        avatar: The avatar being planned for.
        client: Optional client associated with the avatar.
        plan_date: The date this plan covers.
        budget: The computed attention budget.
        allocation: The portfolio allocation strategy.
        return_weights: Weights for return computation.
    """

    avatar: "Avatar"
    client: Optional["Client"]
    plan_date: date
    budget: AttentionBudget
    allocation: PortfolioAllocation
    return_weights: ReturnWeights


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

from app.logging_config import get_logger
import time
import uuid
from datetime import datetime, timedelta, timezone

logger = get_logger(__name__)


def _gather_community_state(
    db: "Session",
    avatar_id: uuid.UUID,
    subreddit: str,
) -> dict:
    """Build community_state dict for a subreddit.

    Returns a dict compatible with risk_engine.assess_risk:
        - subreddit: str
        - removal_count_30d: int
        - activity_24h: int (posts in the subreddit in last 24h)
        - topic_saturation: bool (5+ threads with same topic in 24h)
        - last_mod_action: str | None (date of last removal against avatar)
    """
    from app.models.comment_draft import CommentDraft
    from app.models.thread import RedditThread

    now = datetime.now(timezone.utc)
    cutoff_24h = now - timedelta(hours=24)
    cutoff_30d = now - timedelta(days=30)

    # Count recent activity in this subreddit (posts scraped in last 24h)
    activity_24h = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit == subreddit,
            RedditThread.scraped_at >= cutoff_24h,
        )
        .count()
    )

    # Compute removal count in last 30 days for this avatar in this subreddit
    removal_count = (
        db.query(CommentDraft)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.is_deleted == True,  # noqa: E712
            CommentDraft.posted_at >= cutoff_30d,
            RedditThread.subreddit == subreddit,
        )
        .count()
    )

    # Detect last mod action against avatar in this subreddit
    # (most recent deletion detected)
    last_mod_action = None
    last_deleted = (
        db.query(CommentDraft.deleted_detected_at)
        .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.is_deleted == True,  # noqa: E712
            CommentDraft.deleted_detected_at.isnot(None),
            RedditThread.subreddit == subreddit,
        )
        .order_by(CommentDraft.deleted_detected_at.desc())
        .first()
    )
    if last_deleted and last_deleted[0]:
        last_mod_action = last_deleted[0].isoformat()

    # Topic saturation detection: 5+ threads with same-ish topic in 24h
    # We use post_title word overlap to detect topic clustering
    topic_saturation = _detect_topic_saturation(db, subreddit, cutoff_24h)

    # Removal feedback risk adjustment (Requirement 13.6)
    # Queries historical removal events from Opportunity model for this pair
    from app.services.risk_engine import get_removal_risk_adjustment

    risk_adjustment = get_removal_risk_adjustment(db, avatar_id, subreddit)

    return {
        "subreddit": subreddit,
        "removal_count_30d": removal_count,
        "activity_24h": activity_24h,
        "topic_saturation": topic_saturation,
        "last_mod_action": last_mod_action,
        "risk_adjustment": risk_adjustment,
    }


def _detect_topic_saturation(
    db: "Session",
    subreddit: str,
    cutoff: datetime,
) -> bool:
    """Detect if a subreddit has topic saturation (5+ threads on same topic in 24h).

    Uses a simple word-overlap heuristic on post titles: if 5+ threads share
    3+ significant words (excluding stop words) in their titles, it's saturated.
    """
    from app.models.thread import RedditThread

    # Get recent threads in this subreddit
    recent_threads = (
        db.query(RedditThread.post_title)
        .filter(
            RedditThread.subreddit == subreddit,
            RedditThread.scraped_at >= cutoff,
        )
        .limit(100)
        .all()
    )

    if len(recent_threads) < 5:
        return False

    # Simple stop words to ignore
    stop_words = {
        "the", "a", "an", "is", "it", "in", "on", "at", "to", "for",
        "of", "and", "or", "but", "not", "with", "this", "that", "be",
        "are", "was", "were", "has", "have", "had", "do", "does", "did",
        "can", "could", "will", "would", "should", "i", "me", "my", "you",
        "your", "we", "they", "he", "she", "its", "from", "by", "about",
        "what", "how", "why", "when", "where", "who", "which", "all",
        "just", "so", "if", "any", "no", "more", "some", "than",
    }

    # Extract significant words from each title
    title_word_sets: list[set[str]] = []
    for (title,) in recent_threads:
        if not title:
            continue
        words = set(
            w.lower().strip(".,!?;:'\"()-[]{}") for w in (title or "").split()
            if len(w) > 2
        )
        significant = words - stop_words
        if significant:
            title_word_sets.append(significant)

    if len(title_word_sets) < 5:
        return False

    # Count pairs sharing 3+ significant words — if 5+ threads cluster, saturated
    from collections import Counter

    # Build a frequency map of word combinations (bigrams from titles)
    # Simpler approach: check if any word appears in 5+ titles
    word_freq: Counter = Counter()
    for word_set in title_word_sets:
        for word in word_set:
            word_freq[word] += 1

    # If any significant word appears in 5+ titles, consider saturated
    for word, count in word_freq.most_common(10):
        if count >= 5 and len(word) >= 4:  # Only meaningful words
            return True

    return False


def _build_avatar_state_snapshot(avatar: "Avatar") -> dict:
    """Capture avatar state at decision time."""
    return {
        "karma": getattr(avatar, "karma_comment", 0) or 0,
        "phase": avatar.warming_phase,
        "health": getattr(avatar, "health_status", "healthy"),
        "days_since_post": _days_since_last_post(avatar),
        "posts_today": 0,  # Will be filled by caller if needed
        "risk_tolerance": None,  # Set from budget
    }


def _days_since_last_post(avatar: "Avatar") -> int:
    """Compute days since avatar's last posted comment."""
    last_posted = getattr(avatar, "last_posted_at", None)
    if last_posted is None:
        return 999
    now = datetime.now(timezone.utc)
    if last_posted.tzinfo is None:
        last_posted = last_posted.replace(tzinfo=timezone.utc)
    delta = now - last_posted
    return max(0, delta.days)


def _count_brand_mentions_this_month(
    db: "Session",
    avatar: "Avatar",
    client: "Client",
) -> int:
    """Count brand-related comments posted this month for an avatar.

    Detects brand mentions by checking if any of the client's high-priority
    keywords appear in the posted comment text (ai_draft or edited_draft).
    """
    from app.models.comment_draft import CommentDraft

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Get client keywords (high priority = brand terms)
    keywords = getattr(client, "keywords", None) or {}
    brand_terms: list[str] = []
    if isinstance(keywords, dict):
        # "high" keywords are typically brand-related terms
        high_kw = keywords.get("high", [])
        if isinstance(high_kw, list):
            brand_terms = [k.lower() for k in high_kw if k]
    if not brand_terms:
        # Also check brand field on client
        brand = getattr(client, "brand", None) or ""
        if brand:
            brand_terms = [brand.lower()]

    if not brand_terms:
        return 0

    # Query posted comments this month for this avatar + client
    posted_drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.client_id == client.id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= month_start,
        )
        .all()
    )

    brand_count = 0
    for draft in posted_drafts:
        text = (draft.edited_draft or draft.ai_draft or "").lower()
        if any(term in text for term in brand_terms):
            brand_count += 1

    return brand_count


def _build_market_state(opportunities: list, risk_assessments: dict) -> dict:
    """Build market state snapshot from opportunities."""
    if not opportunities:
        return {
            "trending_topics": [],
            "avg_competition": 0,
            "temperature": "cold",
        }

    # Top 5 subreddits as "trending topics"
    sub_counts: dict[str, int] = {}
    total_competition = 0
    for opp in opportunities:
        sub = opp.subreddit or "unknown"
        sub_counts[sub] = sub_counts.get(sub, 0) + 1
        total_competition += opp.competition_score or 0

    trending = sorted(sub_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    avg_comp = total_competition / len(opportunities) if opportunities else 0

    # Temperature based on opportunity density
    count = len(opportunities)
    if count >= 30:
        temperature = "hot"
    elif count >= 15:
        temperature = "warm"
    else:
        temperature = "cold"

    return {
        "trending_topics": [t[0] for t in trending],
        "avg_competition": int(avg_comp),
        "temperature": temperature,
    }


def _build_community_states_snapshot(community_states: dict) -> dict:
    """Aggregate community states for the decision record."""
    result = {}
    for sub, state in community_states.items():
        result[sub] = {
            "activity_24h": state.get("activity_24h", 0),
            "topic_saturation": state.get("topic_saturation", False),
            "last_mod_action": state.get("last_mod_action"),
            "removal_count_30d": state.get("removal_count_30d", 0),
            "risk_adjustment": state.get("risk_adjustment", 0),
        }
    return result


def _generate_zero_day_report(
    db: "Session",
    avatar: "Avatar",
    plan_date: date,
    opportunities: list,
    risk_assessments: dict,
    expected_returns: dict,
    rejected: list,
) -> None:
    """Generate and persist a Zero-Day Report.

    Determines the reason code and builds recommendations.
    """
    from app.models.zero_day_report import ZeroDayReport

    # Determine reason code
    opp_count = len(opportunities)
    if opp_count < 10:
        reason_code = "market_scarcity"
    elif not opportunities:
        reason_code = "market_cold"
    else:
        # Check if all were rejected for risk
        risk_rejections = [r for r in rejected if "risk" in str(r[1]).lower()]
        if len(risk_rejections) > len(rejected) * 0.7:
            reason_code = "risk_too_high"
        else:
            # Check average return
            avg_return = 0
            if expected_returns:
                composites = [er.composite for er in expected_returns.values()]
                avg_return = sum(composites) / len(composites) if composites else 0
            if avg_return < 20:
                reason_code = "return_too_low"
            else:
                reason_code = "avatar_state_unfavorable"

    # Compute stats
    avg_risk = 0
    if risk_assessments:
        scores = [ra.final_score for ra in risk_assessments.values()]
        avg_risk = int(sum(scores) / len(scores)) if scores else 0

    highest_return = 0
    if expected_returns:
        highest_return = max(er.composite for er in expected_returns.values())

    # Top rejections (up to 5)
    top_rejections = []
    for opp, reason in rejected[:5]:
        top_rejections.append({
            "subreddit": opp.subreddit,
            "composite_score": opp.composite_score,
            "reason": reason,
        })

    report_content = {
        "summary": f"Zero-day for {avatar.reddit_username}: {reason_code}",
        "opportunities_scanned": opp_count,
        "avg_risk": avg_risk,
        "highest_return": highest_return,
        "top_rejections": top_rejections,
    }

    # Build recommendations (2-5 suggestions)
    recommendations = []
    if reason_code == "market_scarcity":
        recommendations.append({
            "type": "add_new_subreddits",
            "description": "Add more subreddits to increase opportunity pool",
        })
        recommendations.append({
            "type": "wait_for_better_timing",
            "description": "Market may recover; check thread freshness timing",
        })
    elif reason_code == "risk_too_high":
        recommendations.append({
            "type": "adjust_risk_threshold",
            "description": "Consider increasing acceptable risk level",
            "suggested_value": min(100, avg_risk + 10),
        })
        recommendations.append({
            "type": "review_avatar_health",
            "description": "Check avatar health status and recent mod actions",
        })
    elif reason_code == "return_too_low":
        recommendations.append({
            "type": "change_strategy_focus",
            "description": "Current strategy yields low returns; consider adjusting niche focus",
        })
        recommendations.append({
            "type": "add_new_subreddits",
            "description": "Explore higher-engagement communities",
        })
    elif reason_code == "avatar_state_unfavorable":
        recommendations.append({
            "type": "review_avatar_health",
            "description": "Avatar may need attention — check health and history",
        })
        recommendations.append({
            "type": "wait_for_better_timing",
            "description": "Consider waiting for improved conditions",
        })
    else:
        recommendations.append({
            "type": "wait_for_better_timing",
            "description": "Market conditions are unfavorable; check again later",
        })
        recommendations.append({
            "type": "add_new_subreddits",
            "description": "Broaden opportunity pool with new subreddits",
        })

    report = ZeroDayReport(
        id=uuid.uuid4(),
        avatar_id=avatar.id,
        report_date=plan_date,
        reason_code=reason_code,
        report_content=report_content,
        recommendations=recommendations,
    )
    db.add(report)


def _persist_decision_record(
    db: "Session",
    avatar: "Avatar",
    client: Optional["Client"],
    plan_date: date,
    budget: "AttentionBudget",
    allocation: "PortfolioAllocation",
    allocation_result,
    opportunities: list,
    risk_assessments: dict,
    community_states: dict,
    is_zero_day: bool,
) -> None:
    """Create and persist an immutable Decision Record.

    Handles idempotent re-runs by updating existing records for the same day.
    """
    from app.models.decision_record import DecisionRecord

    avatar_state = _build_avatar_state_snapshot(avatar)
    avatar_state["risk_tolerance"] = budget.acceptable_risk_level

    market_state = _build_market_state(opportunities, risk_assessments)
    community_snapshot = _build_community_states_snapshot(community_states)

    client_state = None
    if client:
        client_state = {
            "goals": getattr(client, "keywords", {}),
            "phase_focus": f"phase_{avatar.warming_phase}",
            "brand_mentions_remaining": getattr(client, "brand_mention_cap", None),
            "target_niches": [],
        }

    budget_available = {
        "max_comments": budget.max_comments,
        "max_posts": budget.max_posts,
        "max_total": budget.max_total_actions,
        "risk_level": budget.acceptable_risk_level,
    }

    budget_consumed = {}
    if allocation_result:
        budget_consumed = dict(allocation_result.budget_consumed)
    else:
        budget_consumed = {"total": 0}

    metrics = {
        "diversification": allocation_result.diversification_score if allocation_result else 0.0,
        "risk_adjusted_return": 0.0,  # Computed post-hoc by metrics task
        "opportunities_scanned": len(opportunities),
    }

    # Check for existing record (idempotent re-run handling)
    existing = (
        db.query(DecisionRecord)
        .filter(
            DecisionRecord.avatar_id == avatar.id,
            DecisionRecord.decision_date == plan_date,
        )
        .first()
    )

    if existing:
        # Update existing record
        existing.avatar_state = avatar_state
        existing.community_states = community_snapshot
        existing.market_state = market_state
        existing.client_state = client_state
        existing.portfolio_allocation = {"categories": allocation.categories, "preset": allocation.preset}
        existing.budget_available = budget_available
        existing.budget_consumed = budget_consumed
        existing.metrics = metrics
        existing.zero_day = is_zero_day
    else:
        record = DecisionRecord(
            id=uuid.uuid4(),
            avatar_id=avatar.id,
            decision_date=plan_date,
            avatar_state=avatar_state,
            community_states=community_snapshot,
            market_state=market_state,
            client_state=client_state,
            portfolio_allocation={"categories": allocation.categories, "preset": allocation.preset},
            budget_available=budget_available,
            budget_consumed=budget_consumed,
            metrics=metrics,
            zero_day=is_zero_day,
        )
        db.add(record)


# ---------------------------------------------------------------------------
# Main Entry Point
# ---------------------------------------------------------------------------


def build_portfolio(
    db: "Session",
    avatar: "Avatar",
    client: Optional["Client"] = None,
    topup_remaining: Optional[int] = None,
) -> "EPGResult":
    """Build the daily attention portfolio for an avatar.

    Replaces build_daily_epg() thread selection. Produces the same
    output interface (EPGResult with EPGSlot records).

    Pipeline:
    1. Compute AttentionBudget (phase + health + client plan)
    2. Run Opportunity Engine (scan + score)
    3. Run Risk Engine (filter by risk threshold)
    4. Run Return Engine (estimate returns)
    5. Run Allocation Engine (portfolio optimization)
    6. Persist: Opportunities, Decision Record, EPGSlots
    7. If zero actions: generate Zero-Day Report

    Args:
        db: SQLAlchemy session.
        avatar: The avatar to build a portfolio for.
        client: Optional client for strategy/weights configuration.

    Returns:
        EPGResult compatible with existing consumers.
    """
    from app.models.epg_slot import EPGSlot
    from app.services.allocation_engine import allocate_portfolio, AllocationResult
    from app.services.epg import EPGResult, build_daily_epg
    from app.services.opportunity_engine import scan_opportunities
    from app.services.return_engine import (
        estimate_returns,
        get_subreddit_karma_multiplier,
        ExpectedReturn,
    )
    from app.services.risk_engine import assess_risk, filter_by_risk

    start_time = time.time()
    plan_date = date.today()
    result = EPGResult(avatar)

    # --- Early guards (same as legacy EPG) ---
    if avatar.is_frozen:
        result.status = "frozen"
        result.message = f"Avatar frozen: {avatar.freeze_reason or 'no reason'}"
        return result

    # Mentor pool is excluded (not a phase — pool-based classification)
    # Phase 0 (Incubation) IS allowed with budget=1 comment/day (safe subs only)

    if getattr(avatar, "pool", "b2b") not in ("b2b", "b2c", "warm"):
        result.status = "excluded"
        result.message = f"Avatar pool '{avatar.pool}' excluded from EPG"
        return result

    if getattr(avatar, "health_status", "healthy") in ("shadowbanned", "suspended"):
        result.status = "excluded"
        result.message = f"Avatar health: {avatar.health_status}"
        return result

    if not getattr(avatar, "active", True):
        result.status = "excluded"
        result.message = "Avatar is deactivated"
        return result

    # --- Timing enforcement: defer if last_posted_at within 45 minutes ---
    last_posted = getattr(avatar, "last_posted_at", None)
    if last_posted is not None:
        if last_posted.tzinfo is None:
            last_posted = last_posted.replace(tzinfo=timezone.utc)
        minutes_since_last = (datetime.now(timezone.utc) - last_posted).total_seconds() / 60.0
        if minutes_since_last < 45:
            result.status = "deferred"
            result.message = (
                f"Timing constraint: {minutes_since_last:.0f} min since last post "
                f"(minimum 45 min interval)"
            )
            return result

    # --- Dedup guard: prevent duplicate EPG builds per avatar per day ---
    # Single daily EPG build. Rules:
    # 1. If any non-skipped slots exist (generated/approved/posted) -> skip (successful build done)
    # 2. If only skipped slots exist -> allow ONE retry (e.g. manual trigger or recovery)
    # 3. Max 2 build attempts per day (prevents infinite loops from manual triggers)
    # Exception: topup_remaining is set -> skip dedup (afternoon top-up for underfilled budget)
    from sqlalchemy import func as _sa_func

    _MAX_BUILD_ATTEMPTS_PER_DAY = 2
    _is_topup = topup_remaining is not None

    if not _is_topup:
        existing_active_count = (
            db.query(_sa_func.count(EPGSlot.id))
            .filter(
                EPGSlot.avatar_id == avatar.id,
                EPGSlot.plan_date == plan_date,
                EPGSlot.status.notin_(["skipped"]),
            )
            .scalar() or 0
        )

        if existing_active_count > 0:
            # Successful build exists - no rebuild needed
            result.status = "already_planned"
            result.message = (
                f"EPG already built today: {existing_active_count} active slots exist. "
                f"Skipping duplicate build."
            )
            logger.info(
                "build_portfolio SKIPPED (dedup): avatar=%s plan_date=%s existing_slots=%d",
                avatar.reddit_username, plan_date, existing_active_count,
            )
            return result

        # Check build attempt count (all slots including skipped)
        build_attempts = (
            db.query(_sa_func.count(_sa_func.distinct(EPGSlot.created_at)))
            .filter(
                EPGSlot.avatar_id == avatar.id,
                EPGSlot.plan_date == plan_date,
            )
            .scalar() or 0
        )

        if build_attempts >= _MAX_BUILD_ATTEMPTS_PER_DAY:
            # Already attempted twice (morning + afternoon) - stop
            result.status = "already_planned"
            result.message = (
                f"EPG build attempted {build_attempts} times today (max {_MAX_BUILD_ATTEMPTS_PER_DAY}). "
                f"All previous slots skipped. No more retries."
            )
            logger.info(
                "build_portfolio SKIPPED (max attempts): avatar=%s plan_date=%s attempts=%d",
                avatar.reddit_username, plan_date, build_attempts,
            )
            return result

        # Allow rebuild: previous attempt(s) all failed (skipped), retry permitted
        if build_attempts > 0:
            logger.info(
                "build_portfolio RETRY: avatar=%s plan_date=%s previous_attempts=%d (all skipped)",
                avatar.reddit_username, plan_date, build_attempts,
            )

    try:
        # ---------------------------------------------------------------
        # Step 0: A/B Test Budget Override
        # If avatar is in an active experiment, override budget to the
        # experiment's daily_volume. Only check when ab_test_enabled=true
        # (performance optimization — no extra DB queries otherwise).
        # ---------------------------------------------------------------
        _ab_experiment_active = False

        from app.services.settings import get_setting
        _ab_test_enabled = get_setting(db, "ab_test_enabled") == "true"

        if _ab_test_enabled:
            from app.services.ab_test.control_enforcer import get_experiment_budget

            _experiment_daily_volume = get_experiment_budget(db, avatar.id)
            if _experiment_daily_volume is not None:
                _ab_experiment_active = True
                # Count how many slots already exist today for this avatar
                # (generated/approved/posted count as consumed budget)
                from app.models.epg_slot import EPGSlot as _EPGSlotAB
                from sqlalchemy import func as _sa_func_ab

                _ab_used_today = (
                    db.query(_sa_func_ab.count(_EPGSlotAB.id))
                    .filter(
                        _EPGSlotAB.avatar_id == avatar.id,
                        _EPGSlotAB.plan_date == plan_date,
                        _EPGSlotAB.status.in_(["generated", "approved", "posted"]),
                    )
                    .scalar() or 0
                )
                _ab_remaining = max(0, _experiment_daily_volume - _ab_used_today)

                if _ab_remaining <= 0:
                    result.status = "experiment_budget_exhausted"
                    result.message = (
                        f"A/B experiment budget exhausted: "
                        f"{_ab_used_today}/{_experiment_daily_volume} slots used today"
                    )
                    result.daily_budget = _experiment_daily_volume
                    result.remaining = 0
                    logger.info(
                        "build_portfolio A/B budget exhausted: avatar=%s "
                        "daily_volume=%d used=%d",
                        avatar.reddit_username,
                        _experiment_daily_volume,
                        _ab_used_today,
                    )
                    return result

                # Override budget with experiment constraints
                budget = AttentionBudget(
                    max_comments=_ab_remaining,
                    max_posts=0,
                    max_total_actions=_ab_remaining,
                    acceptable_risk_level=40,  # Conservative risk for experiments
                )
                result.daily_budget = _ab_remaining
                logger.info(
                    "build_portfolio A/B budget override: avatar=%s "
                    "daily_volume=%d used=%d remaining=%d",
                    avatar.reddit_username,
                    _experiment_daily_volume,
                    _ab_used_today,
                    _ab_remaining,
                )

        # ---------------------------------------------------------------
        # Step 1: Compute AttentionBudget (skipped if A/B override active)
        # ---------------------------------------------------------------
        if not _ab_experiment_active:
            budget = AttentionBudget.from_avatar(avatar, client)

        # Apply monthly cap if client has one configured (skip for A/B experiment avatars)
        if not _ab_experiment_active and client and getattr(client, "max_comments_per_month", None):
            from app.services.epg_executor import get_budget_used_today
            # Estimate remaining monthly actions and days
            now = datetime.now(timezone.utc)
            days_in_month = 30
            day_of_month = now.day
            days_remaining = max(1, days_in_month - day_of_month + 1)

            # Rough monthly usage estimate (used_today * days elapsed)
            from app.models.epg_slot import EPGSlot as EPGSlotModel
            from sqlalchemy import func as sa_func

            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            monthly_used = (
                db.query(sa_func.count(EPGSlotModel.id))
                .filter(
                    EPGSlotModel.avatar_id == avatar.id,
                    EPGSlotModel.status.in_(["generated", "approved", "posted"]),
                    EPGSlotModel.created_at >= month_start,
                )
                .scalar() or 0
            )
            remaining_monthly = max(0, client.max_comments_per_month - monthly_used)
            budget = budget.apply_monthly_cap(remaining_monthly, days_remaining)

        # Check if budget is zero
        if budget.max_total_actions <= 0:
            result.status = "budget_exhausted"
            result.message = "Budget exhausted (monthly cap or zero phase budget)"
            result.daily_budget = 0
            result.remaining = 0
            return result

        # --- Top-up override: cap budget to remaining unfilled portion ---
        if _is_topup:
            budget = AttentionBudget(
                max_comments=min(budget.max_comments, topup_remaining),
                max_posts=min(budget.max_posts, max(0, topup_remaining - budget.max_comments)),
                max_total_actions=topup_remaining,
                acceptable_risk_level=budget.acceptable_risk_level,
            )
            logger.info(
                "build_portfolio TOPUP mode: avatar=%s topup_remaining=%d",
                avatar.reddit_username, topup_remaining,
            )

        # --- ABSOLUTE DAILY CAP (safety net) ---
        # Regardless of topup_remaining or build path, the total number of
        # generated+approved+posted slots today MUST NOT exceed the avatar's
        # base budget. This prevents accumulation bugs from multiple EPG paths.
        _base_budget = AttentionBudget.from_avatar(avatar, client)
        _absolute_max = _base_budget.max_total_actions

        from app.services.epg_executor import get_budget_used_today as _get_used_cap
        _already_consumed = _get_used_cap(db, avatar.id, plan_date)

        if _already_consumed >= _absolute_max:
            result.status = "budget_exhausted"
            result.message = (
                f"Absolute daily cap reached: {_already_consumed}/{_absolute_max} "
                f"slots already generated/approved/posted today."
            )
            result.daily_budget = _absolute_max
            result.remaining = 0
            logger.info(
                "build_portfolio BLOCKED (absolute cap): avatar=%s "
                "consumed=%d >= max=%d",
                avatar.reddit_username, _already_consumed, _absolute_max,
            )
            return result

        # Further cap budget to what's actually remaining
        _truly_remaining = _absolute_max - _already_consumed
        if budget.max_total_actions > _truly_remaining:
            budget = AttentionBudget(
                max_comments=min(budget.max_comments, _truly_remaining),
                max_posts=min(budget.max_posts, max(0, _truly_remaining - min(budget.max_comments, _truly_remaining))),
                max_total_actions=_truly_remaining,
                acceptable_risk_level=budget.acceptable_risk_level,
            )
            logger.info(
                "build_portfolio budget capped by absolute daily limit: avatar=%s "
                "requested=%d capped_to=%d (consumed=%d max=%d)",
                avatar.reddit_username, budget.max_total_actions + (_already_consumed - _already_consumed),
                _truly_remaining, _already_consumed, _absolute_max,
            )

        result.daily_budget = budget.max_total_actions

        # ---------------------------------------------------------------
        # Step 2: Compute ReturnWeights and PortfolioAllocation
        # ---------------------------------------------------------------
        weights = ReturnWeights.from_client(client)
        allocation = PortfolioAllocation.from_avatar_profile(avatar, client)

        # ---------------------------------------------------------------
        # Step 3: Run Opportunity Engine
        # ---------------------------------------------------------------
        opportunities = scan_opportunities(db, avatar, client, plan_date)

        # ---------------------------------------------------------------
        # Step 3a: Enforce Phase 1 restriction — hobby subreddits only
        # ---------------------------------------------------------------
        if avatar.warming_phase == 1:
            # Gather hobby subreddit names for this avatar
            hobby_sub_names: set[str] = set()
            hobby_subs_raw = getattr(avatar, "hobby_subreddits", None)
            if hobby_subs_raw:
                if isinstance(hobby_subs_raw, dict):
                    for sub_list in hobby_subs_raw.values():
                        if isinstance(sub_list, list):
                            hobby_sub_names.update(
                                s.lower().lstrip("r/") for s in sub_list
                            )
                        elif isinstance(sub_list, str):
                            hobby_sub_names.add(sub_list.lower().lstrip("r/"))
                elif isinstance(hobby_subs_raw, list):
                    for item in hobby_subs_raw:
                        if isinstance(item, dict):
                            sub_name = item.get("subreddit", "")
                            if sub_name:
                                hobby_sub_names.add(sub_name.lower().lstrip("r/"))
                        elif isinstance(item, str):
                            hobby_sub_names.add(item.lower().lstrip("r/"))

            if hobby_sub_names:
                # Filter: keep only opportunities in hobby subreddits
                opportunities = [
                    opp for opp in opportunities
                    if (opp.subreddit or "").lower() in hobby_sub_names
                    or opp.hobby_post_id is not None
                ]
            else:
                # If no hobby subs configured, only keep hobby_post opportunities
                opportunities = [
                    opp for opp in opportunities
                    if opp.hobby_post_id is not None
                ]

            logger.info(
                "Phase 1 filter: avatar=%s remaining_opportunities=%d",
                avatar.reddit_username,
                len(opportunities),
            )

        # ---------------------------------------------------------------
        # Step 3b: Enforce brand budget exhaustion
        # ---------------------------------------------------------------
        if client and getattr(client, "brand_mention_cap", None):
            brand_mentions_used = _count_brand_mentions_this_month(
                db, avatar, client
            )
            if brand_mentions_used >= client.brand_mention_cap:
                # Exclude opportunities that would involve brand content
                # Brand content: high strategic_alignment (>70) = likely brand-adjacent
                pre_filter_count = len(opportunities)
                opportunities = [
                    opp for opp in opportunities
                    if opp.strategic_alignment_score <= 70
                ]
                excluded_count = pre_filter_count - len(opportunities)
                if excluded_count > 0:
                    logger.info(
                        "Brand budget exhausted: avatar=%s "
                        "brand_mentions=%d/%d, excluded=%d brand opportunities",
                        avatar.reddit_username,
                        brand_mentions_used,
                        client.brand_mention_cap,
                        excluded_count,
                    )

        # ---------------------------------------------------------------
        # Step 3c: Apply topic saturation visibility penalty
        # ---------------------------------------------------------------
        # Gather community states early (for topic saturation check)
        _community_state_cache: dict[str, dict] = {}
        for opp in opportunities:
            sub = opp.subreddit or ""
            if sub and sub not in _community_state_cache:
                _community_state_cache[sub] = _gather_community_state(
                    db, avatar.id, sub
                )

        # Apply -30 visibility for saturated subreddits
        for opp in opportunities:
            sub = opp.subreddit or ""
            state = _community_state_cache.get(sub, {})
            if state.get("topic_saturation", False):
                new_vis = max(0, (opp.visibility_score or 0) - 30)
                opp.visibility_score = new_vis
                # Recompute composite (equal weights across 5 non-risk dimensions)
                opp.composite_score = min(100, max(0, (
                    new_vis
                    + (opp.competition_score or 0)
                    + (opp.trust_potential_score or 0)
                    + (opp.karma_potential_score or 0)
                    + (opp.strategic_alignment_score or 0)
                ) // 5))

        # ---------------------------------------------------------------
        # Step 3d: Apply client strategy subreddit_priorities boost
        # ---------------------------------------------------------------
        # Higher priority subreddits get a composite_score bonus so they're
        # more likely to be selected by the allocation engine.
        # Priority 1 = +15, priority 2 = +12, ..., priority 10 = +0
        try:
            if client and client.strategy_context:
                _sub_priorities = client.strategy_context.get("subreddit_priorities", [])
                if _sub_priorities:
                    _priority_map: dict[str, int] = {}
                    for sp in _sub_priorities:
                        _sp_name = (sp.get("subreddit", "") or "").lower().replace("r/", "").strip()
                        _sp_priority = sp.get("priority", 10)
                        if _sp_name:
                            _priority_map[_sp_name] = _sp_priority

                    if _priority_map:
                        _boosted = 0
                        for opp in opportunities:
                            _opp_sub = (opp.subreddit or "").lower()
                            if _opp_sub in _priority_map:
                                # Priority 1 → +15 bonus, priority 10 → +0 bonus
                                _bonus = max(0, 15 - (_priority_map[_opp_sub] - 1) * 2)
                                opp.composite_score = min(100, (opp.composite_score or 0) + _bonus)
                                _boosted += 1

                        if _boosted > 0:
                            logger.info(
                                "Strategy priority boost: avatar=%s boosted=%d opportunities from %d priority subs",
                                avatar.reddit_username, _boosted, len(_priority_map),
                            )
        except Exception:
            logger.warning(
                "Failed to apply strategy priority boost for avatar %s — proceeding without",
                avatar.reddit_username,
            )

        if not opportunities:
            # Zero-day: no opportunities found
            _generate_zero_day_report(
                db, avatar, plan_date,
                opportunities=[], risk_assessments={},
                expected_returns={}, rejected=[],
            )
            _persist_decision_record(
                db, avatar, client, plan_date, budget, allocation,
                allocation_result=None, opportunities=[],
                risk_assessments={}, community_states=_community_state_cache,
                is_zero_day=True,
            )
            db.commit()
            result.status = "zero_day"
            result.message = "No opportunities found (market_scarcity)"
            result.remaining = budget.max_total_actions
            return result

        # ---------------------------------------------------------------
        # Step 4: Run Risk Engine
        # ---------------------------------------------------------------
        risk_assessments: dict[uuid.UUID, object] = {}
        # Reuse community states gathered in Step 3c
        community_states = _community_state_cache

        for opp in opportunities:
            sub = opp.subreddit or ""
            # Cache community state per subreddit (gather if not already cached)
            if sub and sub not in community_states:
                community_states[sub] = _gather_community_state(db, avatar.id, sub)

            risk = assess_risk(opp, avatar, community_states.get(sub, {}))
            risk_assessments[opp.id] = risk

            # Update the opportunity's risk_score in DB
            opp.risk_score = risk.final_score

        # Filter by risk threshold
        viable, rejected = filter_by_risk(
            opportunities, risk_assessments, budget.acceptable_risk_level
        )

        # ---------------------------------------------------------------
        # Step 5: Run Return Engine
        # ---------------------------------------------------------------
        expected_returns: dict[uuid.UUID, ExpectedReturn] = {}

        for opp in viable:
            sub = opp.subreddit or ""
            multiplier = get_subreddit_karma_multiplier(db, avatar.id, sub)
            ret = estimate_returns(opp, avatar, client, weights, multiplier)
            expected_returns[opp.id] = ret

            # Store expected return in opportunity record
            opp.expected_return = ret.to_dict()

        # ---------------------------------------------------------------
        # Step 6: Run Allocation Engine
        # ---------------------------------------------------------------
        allocation_result: AllocationResult = allocate_portfolio(
            viable, risk_assessments, expected_returns,
            budget, allocation, avatar,
        )

        # Combine rejected from risk filtering + allocation rejection
        all_rejected = rejected + allocation_result.rejected

        # ---------------------------------------------------------------
        # Step 7: Persist results
        # ---------------------------------------------------------------
        selected_actions = allocation_result.selected
        is_zero_day = len(selected_actions) == 0

        # Update opportunity statuses
        selected_ids = {a.opportunity.id for a in selected_actions}
        for opp in opportunities:
            if opp.id in selected_ids:
                opp.status = "selected"
            elif opp.status != "selected":
                opp.status = "rejected"
                # Find rejection reason if available
                for rej_opp, reason in all_rejected:
                    if hasattr(rej_opp, "id") and rej_opp.id == opp.id:
                        opp.rejection_reason = reason
                        break

        if is_zero_day:
            # Generate Zero-Day Report
            _generate_zero_day_report(
                db, avatar, plan_date,
                opportunities, risk_assessments,
                expected_returns, all_rejected,
            )
            _persist_decision_record(
                db, avatar, client, plan_date, budget, allocation,
                allocation_result, opportunities,
                risk_assessments, community_states,
                is_zero_day=True,
            )
            db.commit()
            result.status = "zero_day"
            result.message = "All opportunities rejected or below threshold"
            result.remaining = budget.max_total_actions
            return result

        # Create EPGSlot records for selected actions
        client_id = client.id if client else None
        if client_id is None and avatar.client_ids:
            try:
                client_id = uuid.UUID(avatar.client_ids[0])
            except (ValueError, TypeError, IndexError):
                pass

        for action in selected_actions:
            opp = action.opportunity
            
            # Get thread title from the related thread if available
            thread_title = opp.subreddit or ""
            thread_ups = 0
            if opp.thread_id:
                from app.models.thread import RedditThread
                thread = db.query(RedditThread).filter(
                    RedditThread.id == opp.thread_id
                ).first()
                if thread:
                    thread_title = thread.post_title or opp.subreddit or ""
                    thread_ups = thread.ups or 0
            elif opp.hobby_post_id:
                from app.models.hobby import HobbySubreddit
                hobby = db.query(HobbySubreddit).filter(
                    HobbySubreddit.id == opp.hobby_post_id
                ).first()
                if hobby:
                    thread_title = hobby.post_title or opp.subreddit or ""
                    thread_ups = hobby.post_ups or 0

            slot = EPGSlot(
                id=uuid.uuid4(),
                avatar_id=avatar.id,
                client_id=client_id,
                plan_date=plan_date,
                slot_type=action.slot_type,
                scheduled_at=action.scheduled_at,
                status="planned",
                thread_id=opp.thread_id,
                hobby_post_id=opp.hobby_post_id,
                subreddit=opp.subreddit,
                thread_title=thread_title,
                thread_ups=thread_ups,
            )
            db.add(slot)

            # Populate result slots
            slot_dict = {
                "slot_id": str(slot.id),
                "subreddit": opp.subreddit,
                "title": thread_title,
                "ups": thread_ups,
                "scheduled_at": action.scheduled_at.isoformat() if action.scheduled_at else None,
                "status": "planned",
                "draft_id": None,
            }
            if action.slot_type == "hobby":
                slot_dict["hobby_post_id"] = str(opp.hobby_post_id) if opp.hobby_post_id else None
                slot_dict["post_id"] = None
                slot_dict["comment_type"] = "hobby"
                result.hobby_slots.append(slot_dict)
            elif action.slot_type == "post":
                slot_dict["thread_id"] = str(opp.thread_id) if opp.thread_id else None
                slot_dict["comment_type"] = "post"
                result.business_slots.append(slot_dict)
            else:
                slot_dict["thread_id"] = str(opp.thread_id) if opp.thread_id else None
                slot_dict["comment_type"] = "professional"
                result.business_slots.append(slot_dict)

        # Persist Decision Record
        _persist_decision_record(
            db, avatar, client, plan_date, budget, allocation,
            allocation_result, opportunities,
            risk_assessments, community_states,
            is_zero_day=False,
        )

        db.commit()

        # Populate result summary
        result.used_today = 0  # Will be recalculated by consumers
        result.remaining = max(0, budget.max_total_actions - len(selected_actions))
        result.status = "ok"
        result.message = (
            f"Portfolio built: {len(selected_actions)} actions selected, "
            f"diversification={allocation_result.diversification_score:.2f}"
        )

        elapsed = time.time() - start_time
        logger.info(
            "build_portfolio complete: avatar=%s phase=%d selected=%d "
            "rejected=%d zero_day=False elapsed=%.1fs",
            avatar.reddit_username,
            avatar.warming_phase,
            len(selected_actions),
            len(all_rejected),
            elapsed,
        )

        # Performance warning
        if elapsed > 60:
            logger.warning(
                "build_portfolio exceeded 60s target: avatar=%s elapsed=%.1fs",
                avatar.reddit_username,
                elapsed,
            )

        return result

    except Exception as e:
        # Full fallback to legacy build_daily_epg()
        logger.error(
            "build_portfolio FAILED for avatar=%s: %s — falling back to legacy EPG",
            avatar.reddit_username,
            str(e),
            exc_info=True,
        )
        db.rollback()
        try:
            return build_daily_epg(db, avatar, client)
        except Exception as fallback_err:
            logger.error(
                "Legacy build_daily_epg also FAILED for avatar=%s: %s",
                avatar.reddit_username,
                str(fallback_err),
                exc_info=True,
            )
            result = EPGResult(avatar)
            result.status = "error"
            result.message = f"Both EPG 2.0 and legacy failed: {str(e)}"
            return result
