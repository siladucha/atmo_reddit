"""LLM Quality Snapshot model — periodic aggregated quality metrics per model×operation."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LLMQualitySnapshot(Base):
    __tablename__ = "llm_quality_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)

    # Counts
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    empty_count: Mapped[int] = mapped_column(Integer, default=0)
    parse_error_count: Mapped[int] = mapped_column(Integer, default=0)
    timeout_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, default=0)

    # Performance
    avg_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    p95_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avg_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Derived
    success_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    avg_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    # Baseline comparison
    baseline_success_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    baseline_avg_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Degradation detection
    degradation_detected: Mapped[bool] = mapped_column(Boolean, default=False)
    degradation_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
