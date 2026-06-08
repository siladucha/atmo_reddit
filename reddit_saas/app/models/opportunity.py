import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Opportunity(Base):
    __tablename__ = "opportunities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    decision_date: Mapped[date] = mapped_column(Date, nullable=False)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reddit_threads.id"), nullable=True)
    hobby_post_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)
    opportunity_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="comment")

    # Six-dimensional scoring
    visibility_score: Mapped[int] = mapped_column(Integer, nullable=False)
    competition_score: Mapped[int] = mapped_column(Integer, nullable=False)
    trust_potential_score: Mapped[int] = mapped_column(Integer, nullable=False)
    karma_potential_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    strategic_alignment_score: Mapped[int] = mapped_column(Integer, nullable=False)
    composite_score: Mapped[int] = mapped_column(Integer, nullable=False)

    # Expected return (filled by Return Engine)
    expected_return: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="evaluated")
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Outcome tracking (filled by karma feedback loop)
    actual_karma: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_removal: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    outcome_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint("visibility_score BETWEEN 0 AND 100", name="ck_opportunity_visibility_score"),
        CheckConstraint("competition_score BETWEEN 0 AND 100", name="ck_opportunity_competition_score"),
        CheckConstraint("trust_potential_score BETWEEN 0 AND 100", name="ck_opportunity_trust_potential_score"),
        CheckConstraint("karma_potential_score BETWEEN 0 AND 100", name="ck_opportunity_karma_potential_score"),
        CheckConstraint("risk_score BETWEEN 0 AND 100", name="ck_opportunity_risk_score"),
        CheckConstraint("strategic_alignment_score BETWEEN 0 AND 100", name="ck_opportunity_strategic_alignment_score"),
        CheckConstraint("composite_score BETWEEN 0 AND 100", name="ck_opportunity_composite_score"),
        Index("ix_opportunities_avatar_date", "avatar_id", "decision_date"),
        Index("ix_opportunities_status", "status"),
        Index("ix_opportunities_avatar_date_status", "avatar_id", "decision_date", "status"),
    )
