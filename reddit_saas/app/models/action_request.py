"""ActionRequest — tracks approval-tier actions submitted by client portal users.

Actions classified as 'approval_required' in the permission matrix create
ActionRequest records. Internal staff review and approve/reject.
Status: pending → approved/rejected.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ActionRequest(Base):
    __tablename__ = "action_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    client = relationship("Client", backref="action_requests")
    user = relationship("User", foreign_keys=[user_id], backref="action_requests_created")
    resolver = relationship("User", foreign_keys=[resolved_by])

    __table_args__ = (
        Index("ix_action_requests_client_status", "client_id", "status"),
        Index("ix_action_requests_client_action_status", "client_id", "action_type", "status"),
    )
