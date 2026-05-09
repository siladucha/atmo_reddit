"""Avatar Profile Snapshot model.

Stores cached Reddit profile analytics for an avatar.
Updated on demand via the admin "Fetch Fresh Analytics" button.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, Boolean, Float, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AvatarProfileSnapshot(Base):
    __tablename__ = "avatar_profile_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)

    # Account metadata
    reddit_username: Mapped[str] = mapped_column(String(255), nullable=False)
    comment_karma: Mapped[int] = mapped_column(Integer, default=0)
    post_karma: Mapped[int] = mapped_column(Integer, default=0)
    total_karma: Mapped[int] = mapped_column(Integer, default=0)
    account_age_days: Mapped[int] = mapped_column(Integer, default=0)
    account_created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    has_verified_email: Mapped[bool] = mapped_column(Boolean, default=False)
    is_gold: Mapped[bool] = mapped_column(Boolean, default=False)
    is_mod: Mapped[bool] = mapped_column(Boolean, default=False)
    icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Activity patterns
    total_comments: Mapped[int] = mapped_column(Integer, default=0)
    total_posts: Mapped[int] = mapped_column(Integer, default=0)
    avg_comments_per_week: Mapped[float] = mapped_column(Float, default=0.0)
    avg_posts_per_week: Mapped[float] = mapped_column(Float, default=0.0)
    most_active_hour_utc: Mapped[int | None] = mapped_column(Integer, nullable=True)
    most_active_day: Mapped[str | None] = mapped_column(String(20), nullable=True)
    days_since_last_comment: Mapped[int | None] = mapped_column(Integer, nullable=True)
    days_since_last_post: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content style
    avg_comment_length: Mapped[int] = mapped_column(Integer, default=0)
    avg_post_length: Mapped[int] = mapped_column(Integer, default=0)
    uses_emoji: Mapped[bool] = mapped_column(Boolean, default=False)
    uses_links: Mapped[bool] = mapped_column(Boolean, default=False)
    avg_comment_score: Mapped[float] = mapped_column(Float, default=0.0)
    avg_post_score: Mapped[float] = mapped_column(Float, default=0.0)
    top_comment_score: Mapped[int] = mapped_column(Integer, default=0)
    top_post_score: Mapped[int] = mapped_column(Integer, default=0)

    # Structured data (JSON)
    subreddits_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recent_comments_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    recent_posts_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Fetch metadata
    fetch_duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
