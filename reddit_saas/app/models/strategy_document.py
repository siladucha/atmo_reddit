"""Strategy Document model — per-avatar strategy with versioning.

Stores LLM-generated strategy documents containing goals, subreddit priorities,
tone guidelines, cadence rules, and hook inventory. Each generation creates a
new version; only one version is marked `is_current` per avatar.

Approval workflow:
- Generated strategies start as `is_approved=False`
- Admin approves a strategy to mark it ready for pipeline use
- Only one strategy per avatar can be `is_current` (active for display)
- Only approved + current strategies are used by the pipeline
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class StrategyDocument(Base):
    __tablename__ = "strategy_documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)

    # Content sections (structured JSONB)
    goals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    subreddit_priorities: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    tone_guidelines: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    cadence_rules: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    hook_inventory: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    forecast: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Full markdown version (for prompt injection and display)
    document_md: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Versioning
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Approval workflow
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Manual edits
    edited_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    edit_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # LLM metadata
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(nullable=True)
    generation_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    avatar = relationship("Avatar", lazy="joined")

    __table_args__ = (
        Index("ix_strategy_docs_avatar_current", "avatar_id", "is_current"),
        Index("ix_strategy_docs_avatar_version", "avatar_id", "version"),
    )
