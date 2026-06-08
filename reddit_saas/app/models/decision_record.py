import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DecisionRecord(Base):
    __tablename__ = "decision_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)

    # State snapshots at decision time
    avatar_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    community_states: Mapped[dict] = mapped_column(JSONB, nullable=False)
    market_state: Mapped[dict] = mapped_column(JSONB, nullable=False)
    client_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Allocation details
    portfolio_allocation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    budget_available: Mapped[dict] = mapped_column(JSONB, nullable=False)
    budget_consumed: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Results
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    zero_day: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("avatar_id", "decision_date", name="uq_decision_avatar_date"),
        Index("ix_decision_records_avatar_date", "avatar_id", "decision_date"),
    )
