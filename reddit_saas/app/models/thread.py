import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, Text, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class RedditThread(Base):
    __tablename__ = "reddit_threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    subreddit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subreddits.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="professional")  # professional | hobby

    # Reddit data
    reddit_native_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)  # denormalized display
    post_title: Mapped[str] = mapped_column(Text, nullable=False)
    post_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    ups: Mapped[int] = mapped_column(Integer, default=0)
    downs: Mapped[int] = mapped_column(Integer, default=0)

    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Thread liveness
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    locked_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Legacy scoring fields (kept for backward compatibility; canonical scores in ThreadScore)
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alert: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    composite: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    subreddit_rel = relationship("Subreddit", back_populates="threads")
    scores = relationship("ThreadScore", back_populates="thread")

    __table_args__ = (
        Index("ix_reddit_threads_client_id", "client_id"),
        Index("ix_reddit_threads_subreddit_id", "subreddit_id"),
        Index("ix_reddit_threads_created_at", "created_at"),
        # Partial: scoring pipeline filters non-locked threads by subreddit
        Index(
            "ix_reddit_threads_subreddit_not_locked",
            "subreddit_id",
            postgresql_where=text("is_locked = false"),
        ),
        # Partial: liveness checks find stale non-locked threads
        Index(
            "ix_reddit_threads_scraped_at",
            "scraped_at",
            postgresql_where=text("is_locked = false"),
        ),
    )
