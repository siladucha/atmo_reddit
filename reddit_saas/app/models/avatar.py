import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Avatar(Base):
    __tablename__ = "avatars"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    reddit_username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Voice & personality
    voice_profile_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone_principles: Mapped[str | None] = mapped_column(Text, nullable=True)
    speech_patterns: Mapped[str | None] = mapped_column(Text, nullable=True)
    hill_i_die_on: Mapped[str | None] = mapped_column(Text, nullable=True)
    helpful_mode_topics: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    vocabulary_lean: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Subreddits
    hobby_subreddits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    business_subreddits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Health & karma
    karma_post: Mapped[int] = mapped_column(Integer, default=0)
    karma_comment: Mapped[int] = mapped_column(Integer, default=0)
    is_shadowbanned: Mapped[bool] = mapped_column(Boolean, default=False)
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
