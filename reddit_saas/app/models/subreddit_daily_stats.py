"""SubredditDailyStats model.

Stores daily posting statistics per subreddit: comments posted, survived,
and removal rate. UNIQUE constraint on (subreddit_id, date).
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SubredditDailyStats(Base):
    __tablename__ = "subreddit_daily_stats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    subreddit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("subreddits.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    comments_posted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    comments_survived: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    removal_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    computed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationship
    subreddit = relationship("Subreddit", back_populates="daily_stats")

    __table_args__ = (
        UniqueConstraint("subreddit_id", "date", name="uq_sds_subreddit_date"),
        Index("ix_sds_subreddit_date", "subreddit_id", "date"),
    )
