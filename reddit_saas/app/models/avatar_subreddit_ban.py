"""Avatar-Subreddit Ban model.

Tracks per-subreddit bans (shadowbans/mod bans) for avatars.
Supports both auto-detection (from snapshot_comment_outcomes)
and manual marking (admin UI).

Auto-unban via weekly probe (unauthenticated comment visibility check).
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AvatarSubredditBan(Base):
    __tablename__ = "avatar_subreddit_bans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False
    )
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)

    # Detection
    banned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ban_source: Mapped[str] = mapped_column(String(30), nullable=False)  # "auto_detected" | "manual"
    detection_evidence: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    consecutive_deletions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Unban
    unbanned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    unban_source: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # "probe_check" | "manual"

    # State
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Probe tracking
    last_probe_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_probe_result: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )  # "still_banned" | "accessible"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # Only one active ban per avatar per subreddit
        UniqueConstraint(
            "avatar_id", "subreddit",
            name="uq_avatar_subreddit_ban_active",
        ),
        Index("ix_asb_avatar_active", "avatar_id", "is_active"),
        Index("ix_asb_subreddit", "subreddit"),
    )
