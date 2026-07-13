"""Client subscription — mirrors Stripe subscription state per client.

Central billing state: counters, grace period, pending downgrades.
One-to-one with Client (every client gets a row at creation).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ClientSubscription(Base):
    __tablename__ = "client_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True, unique=True
    )

    # Stripe identifiers (NULL for trial clients without Stripe)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)

    # Billing state
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="trial", server_default="trial")
    # valid: trial | active | past_due | suspended | canceled | trial_expired | archived

    # Billing period (mirrored from Stripe)
    billing_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    billing_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Action counters (within current billing period)
    monthly_action_counter: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    monthly_post_counter: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_notified_threshold: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # 0=none, 80=warned at 80%, 90=warned at 90%, 100=warned at 100%

    # Grace period fields
    grace_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    grace_period_days: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    previous_grace_ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Pending plan transitions
    pending_downgrade_plan: Mapped[str | None] = mapped_column(String(20), nullable=True)
    pending_downgrade_effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Cancellation
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    client = relationship("Client", backref="subscription", uselist=False)

    def __repr__(self) -> str:
        return f"<ClientSubscription client={self.client_id} status={self.status} counter={self.monthly_action_counter}>"
