import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RedditThread(Base):
    __tablename__ = "reddit_threads"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="professional")  # professional | hobby

    # Reddit data
    reddit_native_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)
    post_title: Mapped[str] = mapped_column(Text, nullable=False)
    post_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    comments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    ups: Mapped[int] = mapped_column(Integer, default=0)
    downs: Mapped[int] = mapped_column(Integer, default=0)

    # Scoring
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True)  # engage | monitor | skip
    alert: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    composite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scoring_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    scraped_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
