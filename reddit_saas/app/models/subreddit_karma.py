import uuid
from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, UniqueConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SubredditKarma(Base):
    """Per-avatar, per-subreddit karma snapshot.

    Tracks how much karma an avatar has accumulated in a specific subreddit,
    populated from internally tracked comment performance and (when available)
    Reddit API per-subreddit breakdowns.
    """

    __tablename__ = "subreddit_karma"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False
    )
    subreddit_name: Mapped[str] = mapped_column(String(255), nullable=False)

    comment_karma: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    post_karma: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    # Snapshot of the karma values from the previous update — used to render
    # deltas on the avatar detail page (Req 11).
    previous_comment_karma: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    previous_post_karma: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )

    # Subreddit classification — "professional" | "hobby" | "unknown".
    # Used for color coding in the breakdown widget and for the
    # phase-2-to-3 "≥1 professional sub" gate.
    subreddit_type: Mapped[str] = mapped_column(
        String(50), default="unknown", server_default="unknown", nullable=False
    )

    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    avatar = relationship("Avatar", backref="subreddit_karmas")

    __table_args__ = (
        UniqueConstraint("avatar_id", "subreddit_name", name="uq_subreddit_karma_avatar_sub"),
        Index("ix_subreddit_karma_avatar", "avatar_id"),
        Index("ix_subreddit_karma_avatar_updated", "avatar_id", last_updated_at.desc()),
    )

    @property
    def total_karma(self) -> int:
        return (self.comment_karma or 0) + (self.post_karma or 0)

    @property
    def total_delta(self) -> int:
        prev = (self.previous_comment_karma or 0) + (self.previous_post_karma or 0)
        return self.total_karma - prev
