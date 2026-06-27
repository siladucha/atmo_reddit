"""EPG Slot — persistent daily publishing plan for avatars.

Each slot represents one planned comment (hobby or professional) for a specific
thread on a specific day. Slots track the full lifecycle:
planned → generated → approved → posted (or skipped/expired).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import Date, Index, String, Text, Integer, DateTime, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EPGSlot(Base):
    __tablename__ = "epg_slots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Slot type and scheduling
    slot_type: Mapped[str] = mapped_column(String(50), nullable=False)  # hobby | professional
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Status lifecycle: planned → generated → approved → posted | skipped | expired
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="planned")

    # Target (what to generate for)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reddit_threads.id"), nullable=True)
    hobby_post_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subreddit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    thread_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    thread_ups: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Result (filled after generation)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("comment_drafts.id"), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Decision transparency — why this thread was selected for this slot
    # Structure: {"reason": "...", "score": N, "factors": [...], "alternatives_considered": N}
    selection_reasoning: Mapped[dict | None] = mapped_column("selection_reasoning", JSONB, nullable=True)

    # Relationships
    avatar = relationship("Avatar", lazy="joined")
    thread = relationship("RedditThread", lazy="joined")
    draft = relationship("CommentDraft", lazy="joined")

    __table_args__ = (
        Index("ix_epg_slots_avatar_date", "avatar_id", "plan_date"),
        Index("ix_epg_slots_avatar_date_status", "avatar_id", "plan_date", "status"),
        Index(
            "ix_epg_slots_status_planned",
            "status",
            postgresql_where=text("status = 'planned'"),
        ),
        Index("ix_epg_slots_draft_id", "draft_id"),
        # Idempotency: prevent duplicate slots for same avatar+date+thread
        Index(
            "uq_epg_slots_avatar_date_thread",
            "avatar_id", "plan_date", "thread_id",
            unique=True,
            postgresql_where=text("thread_id IS NOT NULL"),
        ),
        # Idempotency: prevent duplicate slots for same avatar+date+hobby_post
        Index(
            "uq_epg_slots_avatar_date_hobby",
            "avatar_id", "plan_date", "hobby_post_id",
            unique=True,
            postgresql_where=text("hobby_post_id IS NOT NULL"),
        ),
    )
