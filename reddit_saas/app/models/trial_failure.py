import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrialFailure(Base):
    __tablename__ = "trial_failures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    failure_category: Mapped[str] = mapped_column(String(30), nullable=False)
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_analysis_status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="pending")
    reactivation_recommended: Mapped[bool] = mapped_column(Boolean, server_default="false")
    win_back_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_best_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    reactivation_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
