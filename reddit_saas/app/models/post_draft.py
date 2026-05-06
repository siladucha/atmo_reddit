import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, Text, DateTime, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PostDraft(Base):
    __tablename__ = "post_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)

    # Content
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)
    ai_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending | approved | rejected | posted
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Reddit feedback (populated by karma tracking pipeline)
    reddit_native_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reddit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reddit_upvote_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    reddit_num_comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    deleted_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_karma_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    avatar = relationship("Avatar")

    __table_args__ = (
        Index("ix_post_drafts_status", "status"),
        Index("ix_post_drafts_avatar_status", "avatar_id", "status"),
    )
