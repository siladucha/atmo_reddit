"""Client Portal — API Response Allowlist Schemas.

These Pydantic models define the ONLY fields exposed to client-facing endpoints.
Explicit include list — sensitive fields are never serialized.

NEVER include: reddit_username, proxy_ip, browser_profile_id, raw_karma_score,
ai_cost, confidence_score, survival_rate, phase_eligibility_calculation.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ClientDraftResponse(BaseModel):
    """Fields exposed to client-facing review queue."""

    id: UUID
    avatar_name: str
    avatar_phase: int
    subreddit_name: str
    thread_title: str
    thread_body_excerpt: str = Field(max_length=120)
    comment_text: str
    comment_approach: str | None = None
    created_at: datetime
    status: str

    class Config:
        from_attributes = True


class ClientAvatarResponse(BaseModel):
    """Avatar data safe for client display."""

    id: UUID
    name: str
    bio: str | None = None
    warming_phase: int
    karma_tier: str  # "newcomer" | "building" | "established" | "authority"
    last_active_at: datetime | None = None
    is_shadowbanned: bool = False
    active_subreddits: list[str] = []

    class Config:
        from_attributes = True


class ClientMetricsResponse(BaseModel):
    """Home screen metrics."""

    comments_posted: int = 0
    total_upvotes: int = 0
    active_subreddits: int = 0
    pending_drafts: int = 0


class SafetyBlockResponse(BaseModel):
    """Safety block info returned on 422."""

    rule: str
    avatar_phase: int
    brand_detected: str
    message: str
