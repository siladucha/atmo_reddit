import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, Integer, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ThreadScore(Base):
    __tablename__ = "thread_scores"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reddit_threads.id"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)

    # Scoring fields (moved from RedditThread)
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    alert: Mapped[bool] = mapped_column(Boolean, default=False)
    relevance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality: Mapped[int | None] = mapped_column(Integer, nullable=True)
    strategic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    composite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scoring_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    thread = relationship("RedditThread", back_populates="scores")
    client = relationship("Client")

    __table_args__ = (
        UniqueConstraint("thread_id", "client_id", name="uq_thread_client_score"),
        Index("ix_thread_scores_client_tag", "client_id", "tag"),
    )
