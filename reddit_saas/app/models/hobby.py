import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class HobbySubreddit(Base):
    __tablename__ = "hobby_subreddits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)
    post_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    post_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    permalink: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    post_image: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    post_ups: Mapped[int] = mapped_column(Integer, default=0)
    post_downs: Mapped[int] = mapped_column(Integer, default=0)
    ai_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
