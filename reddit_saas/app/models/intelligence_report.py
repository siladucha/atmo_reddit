"""IntelligenceReport — immutable artifact from a completed Daily Ops Review.

Contains structured report_raw (never regenerated) and narrative report_summary.
One per review_date (UNIQUE constraint).
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class IntelligenceReport(Base):
    __tablename__ = "intelligence_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_review_sessions.id"), nullable=False
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Structured immutable report data
    system_state: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # healthy | degraded | critical
    report_raw: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Contains: health_snapshot, top_events, top_anomalies, top_risks,
    #           forecast_table, decisions, overall_confidence

    # Narrative representation (template or LLM-generated)
    report_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    narrative_mode: Mapped[str] = mapped_column(
        String(20), default="template"
    )  # template | llm | offline

    # Forecast accuracy (filled next day when new session starts)
    forecast_accuracy: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Overall confidence (0-100, aggregated from forecast entries)
    overall_confidence: Mapped[int] = mapped_column(Integer, default=50)

    # Cost tracking
    total_llm_cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)

    __table_args__ = (
        Index("ix_intelligence_reports_date", "report_date"),
    )
