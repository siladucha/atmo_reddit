"""Billing period history — archive of completed billing periods.

One row per completed billing period per client. Used for:
- Usage analytics and trends
- Counter reconciliation verification
- Billing dispute resolution
"""

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BillingPeriodHistory(Base):
    __tablename__ = "billing_period_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(20), nullable=False)
    actions_used: Mapped[int] = mapped_column(Integer, nullable=False)
    posts_used: Mapped[int] = mapped_column(Integer, nullable=False)
    actions_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<BillingPeriodHistory client={self.client_id} {self.actions_used}/{self.actions_limit} ({self.plan_type})>"
