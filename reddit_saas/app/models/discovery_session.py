"""Discovery Session model — bounded research session for Reddit ecosystem analysis.

Tracks an iterative hypothesis-research-validation loop for a prospective or existing
client. Each session consists of 3-5 iterations where entities are extracted, hypotheses
formed, Reddit signals collected, and operator decisions recorded.

The final output is a Visibility Report — a structured assessment of Reddit's potential
value for the client over 6-12 months.

Status workflow:
- in_progress: session is active (default on creation)
- completed: all iterations done, report generated
- abandoned: operator chose to stop early (abandon_reason recorded)
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class DiscoverySession(Base):
    __tablename__ = "discovery_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    operator_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    # Client brief — the initial free-text input (max 5000 chars)
    client_brief: Mapped[str] = mapped_column(Text, nullable=False)
    prospect_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Session state
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    current_iteration: Mapped[int] = mapped_column(Integer, default=1)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Abandonment
    abandon_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Flexible metadata (research_progress, etc.)
    session_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Cost tracking
    total_ai_cost_usd: Mapped[float] = mapped_column(Numeric(10, 4), default=0)

    # Relationships
    operator = relationship("User", foreign_keys=[operator_user_id], lazy="joined")
    entities = relationship("DiscoveryEntity", back_populates="session", cascade="all, delete-orphan")
    hypotheses = relationship("DiscoveryHypothesis", back_populates="session", cascade="all, delete-orphan")
    reports = relationship("VisibilityReport", back_populates="session", cascade="all, delete-orphan")
