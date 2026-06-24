"""ReviewDecision — concrete action decisions from a Daily Ops Review.

Maximum 3 per session. Types: observe, investigate, execute, block.
Tracked across sessions for follow-up accountability.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReviewDecision(Base):
    __tablename__ = "review_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_review_sessions.id"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False)

    # observe | investigate | execute | block
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)

    # References to signals/changes that prompted this decision
    linked_entities: Mapped[list | None] = mapped_column(JSONB, nullable=True)

    # Follow-up tracking
    status: Mapped[str] = mapped_column(
        String(20), default="open"
    )  # open | done | deferred | cancelled
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    defer_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index("ix_review_decisions_status_date", "status", "report_date"),
        Index("ix_review_decisions_session", "session_id"),
    )
