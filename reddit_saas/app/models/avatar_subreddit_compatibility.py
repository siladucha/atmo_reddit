"""Avatar-Subreddit Compatibility model.

Stores compatibility scores (0-100) between avatars and subreddits
based on emotional profile analysis. Score < 40 = tone mismatch warning.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AvatarSubredditCompatibility(Base):
    __tablename__ = "avatar_subreddit_compatibility"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False
    )
    subreddit_name: Mapped[str] = mapped_column(String(255), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    mismatch_reasons: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("avatar_id", "subreddit_name", name="uq_asc_avatar_subreddit"),
        Index("ix_asc_avatar_subreddit", "avatar_id", "subreddit_name", unique=True),
        Index("ix_asc_subreddit_score", "subreddit_name", "score"),
    )
