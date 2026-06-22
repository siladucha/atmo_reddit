"""PostingEvent — audit record for every automated posting attempt.

Captures full context: IP used, proxy hash, user-agent, Reddit response,
timing, and outcome. Retained for 180+ days for compliance and debugging.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PostingEvent(Base):
    __tablename__ = "posting_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False
    )
    draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comment_drafts.id"), nullable=True
    )
    epg_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("epg_slots.id"), nullable=True
    )

    # Timing
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Network fingerprint (no credentials stored)
    ip_used: Mapped[str | None] = mapped_column(String(45), nullable=True)
    proxy_url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256 hex
    user_agent_used: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Reddit response
    reddit_comment_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reddit_comment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")

    # Outcome: success | failure | skipped
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)

    # Execution attribution (Audit Patch 4)
    execution_source: Mapped[str | None] = mapped_column(String(50), nullable=True)  # auto | human | marketplace
    execution_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
