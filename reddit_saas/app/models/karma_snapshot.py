"""KarmaSnapshot — time-series karma tracking per posted comment.

Captures karma_value, reply_count, and deletion status at fixed intervals
(4h, 24h, 48h after posting). This enables:
- Engagement velocity measurement (karma growth curve)
- Thread depth provoked (reply_count under our comment)
- Delayed removal detection
- Outcome feedback for EPG model correction and Discovery hypothesis validation

Retention: 180 days (aligned with PostingEvent retention).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KarmaSnapshot(Base):
    __tablename__ = "karma_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comment_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comment_drafts.id", ondelete="CASCADE"), nullable=False
    )
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False
    )

    # Snapshot data
    karma_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Check window classification (for easy querying)
    check_window: Mapped[str] = mapped_column(
        String(10), nullable=False
    )  # "4h" | "24h" | "48h" | "7d" | "adhoc"

    # Timing
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Delta from previous snapshot (computed at write time)
    karma_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Subreddit context (denormalized for fast analytics queries)
    subreddit: Mapped[str | None] = mapped_column(String(255), nullable=True)

    __table_args__ = (
        Index("ix_karma_snapshots_draft_checked", "comment_draft_id", "checked_at"),
        Index("ix_karma_snapshots_avatar_checked", "avatar_id", "checked_at"),
        Index("ix_karma_snapshots_window", "check_window", "checked_at"),
        Index("ix_karma_snapshots_subreddit_checked", "subreddit", "checked_at"),
    )
