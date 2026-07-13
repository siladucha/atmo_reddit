"""Upsell events — tracks upsell prompt impressions, clicks, and dismissals.

Used for conversion funnel analysis and 72h cooldown enforcement.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UpsellEvent(Base):
    __tablename__ = "upsell_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prompt_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # usage_limit | avatar_limit | subreddit_limit | trial_conversion | trial_first_post
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # impression | click | dismiss
    clicked_plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<UpsellEvent {self.prompt_type}/{self.event_type} client={self.client_id}>"
