"""ReviewSnapshot — immutable data snapshot for a Daily Ops Review session.

Frozen at session start. Never modified after creation.
Two users opening the same review see identical data.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ReviewSnapshot(Base):
    __tablename__ = "review_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Immutable data captured at collection time
    health_snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    signals_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    trends_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    cost_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    forecast_inputs_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_availability_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    __table_args__ = (
        Index("ix_review_snapshots_created_at", "created_at"),
    )
