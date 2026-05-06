import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
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

    # Relationships
    assignments = relationship("ClientSubredditAssignment", back_populates="subreddit")
    threads = relationship("RedditThread", back_populates="subreddit_rel")

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

    # Relationships
    client = relationship("Client", back_populates="subreddit_assignments")
    subreddit = relationship("Subreddit", back_populates="assignments")

    @property
    def subreddit_name(self) -> str:
        """Convenience property for template compatibility."""
        return self.subreddit.subreddit_name if self.subreddit else ""

    __table_args__ = (
        UniqueConstraint("client_id", "subreddit_id", name="uq_client_subreddit_assignment"),
    )
