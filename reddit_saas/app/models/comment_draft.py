import uuid
from datetime import datetime

from sqlalchemy import Index, String, Text, Boolean, Integer, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CommentDraft(Base):
    __tablename__ = "comment_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reddit_threads.id"), nullable=True)
    hobby_post_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hobby_subreddits.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="professional")  # professional | hobby

    # Content
    ai_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_ai_draft: Mapped[str | None] = mapped_column(Text, nullable=True)  # preserved before AI Editor
    edited_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Strategy
    comment_approach: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategic_angle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    engagement_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    perspective_push: Mapped[str | None] = mapped_column(String(50), nullable=True)  # hard | medium | low | undetected

    # Status
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending | approved | rejected | posted
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Updated when status transitions (e.g., pending → approved)
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )

    # Reddit feedback (populated by health check / status sync)
    reddit_comment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    reddit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_karma_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Learning loop provenance (self-learning-loop feature)
    # Structure: {"edit_record_ids": [str, ...], "correction_patterns": [str, ...], "learning_token_count": int}
    learning_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    thread = relationship("RedditThread", lazy="joined")
    hobby_post = relationship("HobbySubreddit", lazy="joined", foreign_keys=[hobby_post_id])
    avatar = relationship("Avatar", lazy="joined")

    __table_args__ = (
        Index("ix_comment_drafts_status", "status"),
        Index("ix_comment_drafts_client_status", "client_id", "status"),
        Index("ix_comment_drafts_created_at", "created_at"),
        # Partial: liveness join — only pending drafts need thread_id lookup
        Index(
            "ix_comment_drafts_thread_pending",
            "thread_id",
            postgresql_where=text("status = 'pending'"),
        ),
        # Avatar performance tracking
        Index("ix_comment_drafts_avatar_status", "avatar_id", "status"),
    )
