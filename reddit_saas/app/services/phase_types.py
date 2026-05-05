"""Phase types and enums for the avatar warming phase system.

Defines the core data structures used across PhasePolicy, PhaseEvaluator,
and PhaseTransitionManager components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BrandMentionLevel(str, Enum):
    """Classification tier of brand-related content.

    Priority order (highest to lowest severity):
        explicit_brand_link > explicit_brand_name > inferred_brand
    """

    explicit_brand_link = "explicit_brand_link"
    explicit_brand_name = "explicit_brand_name"
    inferred_brand = "inferred_brand"


class PolicyStatus(str, Enum):
    """Result status from PhasePolicy content restriction checks."""

    allowed = "allowed"
    blocked = "blocked"
    requires_review = "requires_review"


class RampUpStage(str, Enum):
    """Ramp-up stage for Phase 3 brand mention allowances.

    - early: 0-72 hours after Phase 3 promotion (max 1 brand mention)
    - mid: 72 hours to 7 days (10% brand ratio cap)
    - complete: >7 days (standard 30% brand ratio)
    """

    early = "early"
    mid = "mid"
    complete = "complete"


@dataclass
class PolicyResult:
    """Result from PhasePolicy.check_comment_allowed().

    Attributes:
        status: Whether the comment is allowed, blocked, or requires review.
        reason: Human-readable explanation of the policy decision.
        brand_mention_level: The highest-severity brand mention detected, if any.
    """

    status: PolicyStatus
    reason: str
    brand_mention_level: BrandMentionLevel | None = None


@dataclass
class EvaluationResult:
    """Result from PhaseEvaluator.evaluate().

    Attributes:
        action: The recommended action — "promote", "demote", or "none".
        target_phase: The phase to transition to (for promote/demote), or None.
        criteria_values: Dictionary of current metric values vs thresholds.
        trigger_reason: Explanation of why a demotion was triggered, if applicable.
    """

    action: str  # "promote" | "demote" | "none"
    target_phase: int | None = None
    criteria_values: dict | None = None
    trigger_reason: str | None = None
