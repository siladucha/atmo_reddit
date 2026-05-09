"""Pydantic models for avatar behavioral analysis request/response."""

from typing import Self

from pydantic import BaseModel, model_validator


class ProfileAnalyticsInput(BaseModel):
    """Structured input data for an avatar's profile analytics."""

    recent_comments: list[dict]
    recent_posts: list[dict]
    subreddits: list[str]
    account_age_days: int
    total_karma: int


class AvatarAnalysisRequest(BaseModel):
    """Request payload for avatar behavioral analysis."""

    reddit_username: str
    active: bool
    voice_profile_md: str = ""
    profile_analytics: ProfileAnalyticsInput

    @model_validator(mode="after")
    def check_sufficient_data(self) -> Self:
        """Reject if both comments and posts are empty."""
        analytics = self.profile_analytics
        if not analytics.recent_comments and not analytics.recent_posts:
            raise ValueError(
                "Insufficient data: both recent_comments and recent_posts are empty"
            )
        return self


class BasicInfo(BaseModel):
    """Basic avatar identity information."""

    username: str
    account_age_days: int
    total_karma: int
    is_mod: bool


class BehaviorMetrics(BaseModel):
    """Quantitative behavior metrics for the avatar."""

    total_comments: int
    days_since_last_activity: int
    uses_emoji: bool
    avg_comment_length: int


class Topics(BaseModel):
    """Topic and subreddit engagement data."""

    top_subreddits: list[str]
    key_themes: list[str]


class SpeechPatterns(BaseModel):
    """Language and communication patterns."""

    frequent_terms: list[str]
    pattern_description: str


class BehavioralProfile(BaseModel):
    """Structured output of an avatar behavioral analysis."""

    basic: BasicInfo
    behavior: BehaviorMetrics
    topics: Topics
    speech: SpeechPatterns
    mismatches: list[str]
    summary: str  # 30-50 words


class AnalysisErrorResponse(BaseModel):
    """Structured error response when all analysis attempts fail."""

    error: str
    attempts: int
    last_failure_reason: str


class AnalysisEditSubmission(BaseModel):
    """Request payload for submitting a human edit to an LLM analysis."""

    llm_output: dict
    human_edited: dict
