"""Pydantic schemas for Subreddit Emotional Profile.

Validates LLM-produced emotional analysis before DB storage.
Used by: profile_analyzer service, admin UI display, pipeline injection.
"""

from typing import Literal

from pydantic import BaseModel, Field


class ToneDescriptor(BaseModel):
    """A single tone that is rewarded or punished in a subreddit."""

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=300)


class EmotionalProfileSchema(BaseModel):
    """Validates the JSONB content of subreddits.emotional_profile.

    Produced by LLM analysis of top comments in a subreddit.
    """

    rewarded_tones: list[ToneDescriptor] = Field(min_length=1, max_length=5)
    punished_tones: list[ToneDescriptor] = Field(min_length=0, max_length=5)
    community_temperament: str = Field(min_length=1, max_length=500)
    formality_level: Literal["casual", "moderate", "formal"]
    humor_tolerance: Literal["none", "low", "moderate", "high"]
    vulnerability_tolerance: Literal["none", "low", "moderate", "high"]
    confidence: Literal["low", "medium", "high"]


class CompatibilityResult(BaseModel):
    """Result of avatar-subreddit compatibility scoring."""

    score: int = Field(ge=0, le=100)
    mismatch_reasons: list[str] = Field(default_factory=list, max_length=5)
