"""ForecastAccuracyLog — tracks predicted vs actual values for forecast validation.

Each row represents a single metric prediction from a ClientIntelligenceReport.
When actuals arrive (e.g., new GEO batch), error_pp and within_bounds are computed.
Feeds back into model parameter adjustment (narrow/widen confidence intervals).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ForecastAccuracyLog(Base):
    """Comparison of predicted vs actual at each measurement point.

    Lifecycle:
      1. Report generated → row created (actual_value=NULL)
      2. Actual measured (next GEO batch / karma snapshot) → actual_value, error_pp, within_bounds filled
      3. Accuracy stats aggregated → inform model parameter updates
    """

    __tablename__ = "forecast_accuracy_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    report_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("client_intelligence_reports.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    # What was predicted
    metric_id: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "geo.brand_rate.perplexity"
    predicted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    scenario: Mapped[str] = mapped_column(String(20), nullable=False)  # conservative | expected | optimistic
    predicted_value: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)

    # Actuals (filled when measurement arrives)
    actual_value: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    error_pp: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)  # absolute error in pp
    within_bounds: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # actual within conservative-optimistic?
    measured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    report = relationship("ClientIntelligenceReport")

    __table_args__ = (
        UniqueConstraint("report_id", "metric_id", "target_date", "scenario", name="uq_accuracy_report_metric_target"),
        Index("ix_fal_client_metric", "client_id", "metric_id"),
    )
