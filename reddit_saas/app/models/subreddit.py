import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, Integer, Text, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ClientSubreddit(Base):
    """Legacy model — kept for migration compatibility. Use Subreddit + ClientSubredditAssignment instead."""

    __tablename__ = "client_subreddits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    subreddit_name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="professional")  # professional | hobby
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    client = relationship("Client", back_populates="subreddits")


class Subreddit(Base):
    """Shared subreddit registry — one record per unique subreddit name."""

    __tablename__ = "subreddits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subreddit_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_repurpose_scraped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Failure tracking — auto-disable after consecutive failures
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Risk profile flag
    is_high_risk: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    # Emotional Profile (behavioral/tone intelligence)
    emotional_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    previous_emotional_profile: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    emotional_profile_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    emotional_profile_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    assignments = relationship("ClientSubredditAssignment", back_populates="subreddit")
    threads = relationship("RedditThread", back_populates="subreddit_rel")
    risk_profile = relationship("SubredditRiskProfile", back_populates="subreddit", uselist=False)
    daily_stats = relationship("SubredditDailyStats", back_populates="subreddit")

    __table_args__ = (
        Index("uq_subreddits_name", func.lower(subreddit_name), unique=True),
    )


class ClientSubredditAssignment(Base):
    """Many-to-many link between clients and subreddits."""

    __tablename__ = "client_subreddit_assignments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    subreddit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subreddits.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="professional")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Discovery-sourced priority and engagement approach
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True)
    engagement_approach: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    client = relationship("Client", back_populates="subreddit_assignments")
    subreddit = relationship("Subreddit", back_populates="assignments")

    @property
    def subreddit_name(self) -> str:
        """Convenience property for template compatibility."""
        return self.subreddit.subreddit_name if self.subreddit else ""

    __table_args__ = (
        UniqueConstraint("client_id", "subreddit_id", name="uq_client_subreddit_assignment"),
        # Covering index for scoring pipeline: WHERE client_id=? AND is_active=true → subreddit_id
        Index("ix_csa_client_active_subreddit", "client_id", "is_active", "subreddit_id"),
    )
