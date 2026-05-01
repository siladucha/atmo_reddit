import uuid
from datetime import datetime

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CommentDraft(Base):
    __tablename__ = "comment_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    thread_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reddit_threads.id"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="professional")  # professional | hobby

    # Content
    ai_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    edited_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Strategy
    comment_approach: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategic_angle: Mapped[str | None] = mapped_column(String(100), nullable=True)
    engagement_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(String(50), default="pending")  # pending | approved | rejected | posted
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    thread = relationship("RedditThread")
    avatar = relationship("Avatar")
