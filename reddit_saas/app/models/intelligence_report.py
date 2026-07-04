"""IntelligenceReport — immutable artifact from a completed Daily Ops Review.

Contains structured report_raw (never regenerated) and narrative report_summary.
One per review_date (UNIQUE constraint).

ClientIntelligenceReport — Forecast & Reporting Layer weekly client report.
5-layer truth-separated architecture: observed, planned, forecasted, risks, business impact.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

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


class ClientIntelligenceReport(Base):
    """Weekly client intelligence report with 5-layer truth separation.

    Layers stored as independent JSONB columns:
      - observed_json   (📍 Layer 1: validated measurements)
      - planned_json    (📋 Layer 2: execution intent)
      - forecasted_json (📈 Layer 3: S-curve projections with scenarios)
      - risks_json      (⚠️ Layer 4: platform risk + sensitivities)
      - business_impact_json (💰 Layer 5: category rank, gap-to-leader, ROI)

    Key invariant (P12): observed ≠ projected — NEVER conflated in any output.
    """

    __tablename__ = "client_intelligence_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    # Report identification
    report_period: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "2026-W27"
    report_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 5-layer structured data (each independently queryable)
    observed_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    planned_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    forecasted_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    risks_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    business_impact_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Metadata
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)  # e.g. "scurve_v1"
    data_freshness_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    generation_cost_usd: Mapped[Decimal] = mapped_column(Numeric(8, 4), default=0)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )  # draft | published | superseded
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    client = relationship("Client", lazy="joined")

    __table_args__ = (
        UniqueConstraint("client_id", "report_period", "report_version", name="uq_report_client_period_version"),
        Index("ix_cir_client_period", "client_id", "report_period"),
    )
