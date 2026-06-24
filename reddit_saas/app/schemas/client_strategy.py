"""Pydantic schemas for Client Strategy validation.

Used to validate LLM-generated Client Strategy output before persisting.
The LLM receives the agent instructions (docs/agents/client_strategy_agent.md)
and must produce JSON conforming to ClientStrategyOutput.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Positioning(BaseModel):
    """Client positioning — how RAMP represents the client in Reddit communities."""

    audience: str = Field(..., min_length=10, max_length=500)
    problem: str = Field(..., min_length=10, max_length=500)
    value_mechanism: str = Field(..., min_length=10, max_length=500)
    differentiation: str = Field(..., min_length=10, max_length=500)
    confidence: float = Field(..., ge=0.0, le=0.9)
    evidence_refs: list[str] = Field(default_factory=list)


class SubredditPriority(BaseModel):
    """Ranked subreddit with engagement strategy."""

    subreddit: str = Field(..., min_length=2, max_length=50)
    priority: int = Field(..., ge=1, le=10)
    engagement_approach: str = Field(..., min_length=5, max_length=200)
    reason: str = Field(..., min_length=10, max_length=300)


class ContentPillar(BaseModel):
    """Reusable content theme (30+ day lifespan)."""

    name: str = Field(..., min_length=3, max_length=100)
    goal: str = Field(..., min_length=10, max_length=300)
    confidence: float = Field(..., ge=0.0, le=0.9)


class ForbiddenZone(BaseModel):
    """Explicit exclusion — overrides all generation behavior."""

    type: Literal["claim", "topic", "tone", "community_risk", "competitive_trap"]
    description: str = Field(..., min_length=10, max_length=300)
    severity: Literal["hard_block", "soft_avoid"]


class AeoTarget(BaseModel):
    """AI search intent to capture via content optimization."""

    intent: str = Field(..., min_length=10, max_length=200)
    user_question: str = Field(..., min_length=10, max_length=300)
    expected_visibility_outcome: str = Field(..., min_length=10, max_length=300)


class PhaseEntry(BaseModel):
    """A capability progression phase (not time-fixed)."""

    id: str = Field(..., min_length=1, max_length=50)
    goal: str = Field(..., min_length=10, max_length=300)
    entry_conditions: list[str] = Field(..., min_length=1)
    activities: list[str] = Field(..., min_length=1)
    exit_conditions: list[str] = Field(..., min_length=1)


class PhaseRoadmap(BaseModel):
    """Capability progression roadmap (2-5 phases)."""

    phases: list[PhaseEntry] = Field(..., min_length=2, max_length=5)


class ClientStrategyOutput(BaseModel):
    """Full Client Strategy — validated after LLM generation.

    Metadata is NOT part of LLM output — attached by the service after validation.
    """

    positioning: Positioning
    subreddit_priorities: list[SubredditPriority] = Field(..., min_length=1, max_length=10)
    content_pillars: list[ContentPillar] = Field(..., min_length=3, max_length=5)
    forbidden_zones: list[ForbiddenZone] = Field(..., min_length=1)
    aeo_targets: list[AeoTarget] = Field(default_factory=list, max_length=10)
    phase_roadmap: PhaseRoadmap
