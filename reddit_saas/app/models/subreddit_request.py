"""SubredditRequest — tracks client requests to add new subreddits.

Clients cannot directly add/remove subreddits from the portal.
They submit requests which are reviewed by account managers.
Status: pending → approved/rejected.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SubredditRequest(Base):
    __tablename__ = "subreddit_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    subreddit_name: Mapped[str] = mapped_column(String(100), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    client = relationship("Client", backref="subreddit_requests")
    user = relationship("User", backref="subreddit_requests")

    __table_args__ = (
        Index("ix_subreddit_requests_client_status", "client_id", "status"),
    )
