"""SubredditRiskProfile model.

Stores per-subreddit risk intelligence: risk score, extracted rules,
moderation profile, dangerous hours, recommendations. One-to-one with Subreddit.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SubredditRiskProfile(Base):
    __tablename__ = "subreddit_risk_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subreddit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subreddits.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )

    # Risk score
    risk_score: Mapped[int] = mapped_column(Integer, default=50, server_default="50")
    risk_score_history: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )

    # Extracted rules
    extracted_rules: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    extraction_status: Mapped[str] = mapped_column(
        String(30), default="pending", server_default="pending"
    )
    last_rule_extraction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Moderation profile
    moderation_profile: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    dangerous_hours: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    confidence_level: Mapped[str] = mapped_column(
        String(30), default="insufficient_data", server_default="insufficient_data"
    )
    last_profile_computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Recommendations
    recommendations: Mapped[list] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    dominant_timezone: Mapped[str] = mapped_column(
        String(50), default="UTC", server_default="UTC"
    )

    # Adaptive refresh scheduling
    next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationship
    subreddit = relationship("Subreddit", back_populates="risk_profile")

    __table_args__ = (
        CheckConstraint(
            "risk_score >= 0 AND risk_score <= 100",
            name="ck_srp_risk_score_range",
        ),
        Index("ix_srp_subreddit_id", "subreddit_id", unique=True),
        Index("ix_srp_risk_score", "risk_score"),
        Index("ix_srp_extraction_status", "extraction_status"),
    )
