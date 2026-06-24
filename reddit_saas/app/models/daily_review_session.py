"""DailyReviewSession — tracks the lifecycle of a daily ops review.

Sections: health, changes, trends, hypotheses, forecast, decisions.
Phase 1 uses: health, changes, decisions only.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DailyReviewSession(Base):
    __tablename__ = "daily_review_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("review_snapshots.id"), nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="in_progress"
    )  # in_progress | completed | abandoned

    review_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    total_duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Current section being worked on
    current_section: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Section states: {"health": "completed", "changes": "pending", ...}
    section_states: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    # Section timestamps: {"health_started_at": "...", "health_completed_at": "..."}
    section_timestamps: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    # User inputs per section (auto-saved)
    user_inputs: Mapped[dict] = mapped_column(JSONB, server_default="{}")

    # LLM cost tracking for this session
    cost_used_usd: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)

    __table_args__ = (
        Index("ix_daily_review_sessions_date", "review_date"),
        Index("ix_daily_review_sessions_user_status", "user_id", "status"),
    )
