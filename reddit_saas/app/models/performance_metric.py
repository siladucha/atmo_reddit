import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Core metrics
    return_on_attention: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_adjusted_return: Mapped[float | None] = mapped_column(Float, nullable=True)
    portfolio_diversification: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision_accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    opportunity_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    zero_day_rate: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Counts
    actions_taken: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    karma_gained: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("avatar_id", "metric_date", name="uq_metrics_avatar_date"),
        Index("ix_performance_metrics_avatar_date", "avatar_id", "metric_date"),
    )
