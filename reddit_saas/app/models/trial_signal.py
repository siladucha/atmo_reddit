import uuid
from datetime import datetime

from sqlalchemy import Index, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrialSignal(Base):
    __tablename__ = "trial_signals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    signal_category: Mapped[str] = mapped_column(String(30), nullable=False)
    signal_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_trial_signals_client_created", "client_id", "created_at"),
        Index("ix_trial_signals_client_category", "client_id", "signal_category"),
    )
