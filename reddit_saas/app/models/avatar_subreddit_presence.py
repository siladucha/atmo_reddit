import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AvatarSubredditPresence(Base):
    """Per-avatar, per-subreddit presence record.

    Tracks where an avatar has commented on Reddit, with per-subreddit metrics
    (comment count, total karma, last activity). Populated by scanning the
    avatar's Reddit comment history via PRAW.
    """

    __tablename__ = "avatar_subreddit_presence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False
    )
    subreddit_name: Mapped[str] = mapped_column(String(255), nullable=False)

    comment_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    total_karma: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    avatar = relationship("Avatar", backref="subreddit_presences")

    __table_args__ = (
        UniqueConstraint("avatar_id", "subreddit_name", name="uq_avatar_subreddit_presence"),
        Index("ix_avatar_subreddit_presence_avatar_id", "avatar_id"),
    )
