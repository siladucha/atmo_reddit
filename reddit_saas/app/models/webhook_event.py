"""Webhook events — audit log for all Stripe webhook events.

Every webhook received is logged here regardless of processing outcome.
Provides: idempotency check (stripe_event_id unique), out-of-order detection,
debugging, and billing audit trail.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stripe_event_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    stripe_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_result: Mapped[str] = mapped_column(String(50), nullable=False)
    # processed | skipped_duplicate | skipped_out_of_order | skipped_unhandled | error
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<WebhookEvent {self.event_type} [{self.processing_result}] {self.stripe_event_id[:20]}>"
