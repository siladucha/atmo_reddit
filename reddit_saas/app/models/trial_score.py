import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrialScore(Base):
    __tablename__ = "trial_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    conversion_score: Mapped[int] = mapped_column(Integer, nullable=False)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False)
    opportunity_value_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    score_explanation: Mapped[dict] = mapped_column(JSONB, nullable=False)
    signal_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(20), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("conversion_score >= 0 AND conversion_score <= 100", name="ck_trial_scores_conversion_range"),
        CheckConstraint("priority_score >= 0 AND priority_score <= 100", name="ck_trial_scores_priority_range"),
        CheckConstraint("opportunity_value_cents >= 0", name="ck_trial_scores_value_non_negative"),
        Index("ix_trial_scores_client_scored", "client_id", scored_at.desc()),
    )
