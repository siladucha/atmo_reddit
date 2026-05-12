"""Pydantic models for validating structured LLM JSON responses."""

from typing import Literal

from pydantic import BaseModel, Field


class ScoringOutput(BaseModel):
    """Schema for thread scoring LLM response."""

    alert: bool
    tag: Literal["engage", "monitor", "skip"]
    relevance: int = Field(ge=0, le=3)
    quality: int = Field(ge=0, le=3)
    strategic: int = Field(ge=0, le=3)
    composite: int = Field(ge=0, le=9)
    intent: str
    reason: str


class BatchScoringItem(BaseModel):
    """Single thread result within a batch scoring response."""

    thread_index: int = Field(ge=0, description="0-based index matching input order")
    alert: bool
    tag: Literal["engage", "monitor", "skip"]
    relevance: int = Field(ge=0, le=3)
    quality: int = Field(ge=0, le=3)
    strategic: int = Field(ge=0, le=3)
    composite: int = Field(ge=0, le=9)
    intent: str
    reason: str


class BatchScoringOutput(BaseModel):
    """Schema for batch thread scoring LLM response."""

    results: list[BatchScoringItem]


class CommentOutput(BaseModel):
    """Schema for comment generation LLM response."""

    comment: str
    comment_to: str
    location_depth: int = Field(ge=0)
    location_reasoning: str
    comment_approach: str
    strategic_angle: str


# --- Post Generation Schemas ---


class TitleDirection(BaseModel):
    """Title direction from the brief generator."""

    archetype: str
    info_density: str
    emotional_register: str
    subreddit_tone: str


class PostBriefOutput(BaseModel):
    """Schema for post brief generator LLM response."""

    input_treatment: Literal["original", "discussion_catalyst", "inspiration"]
    post_type: Literal[
        "personal_narrative", "career_frustration", "hot_take",
        "discussion_prompt", "research_analysis", "tool_showcase",
        "leadership_question",
    ]
    strategic_tier: Literal["worldview", "problem_awareness", "community_value"]
    body_architecture: Literal["narrative_arc", "evidence_stack", "rant_with_structure"]
    title_direction: TitleDirection
    hook: str
    angle: str
    worldview_note: str | None = None
    quality_concern: str | None = None


class PostWriterOutput(BaseModel):
    """Schema for post writer LLM response."""

    title: str = Field(min_length=10, max_length=300)
    body: str = Field(min_length=50)
    subreddit: str
    post_type: str
    input_treatment: str
    strategic_tier: str
    worldview_seed: str | None = None
    body_architecture: str
