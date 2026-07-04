"""ObservedSnapshot — immutable point-in-time collection of all observed metrics.

Layer 1 of the Forecast & Reporting architecture: ground-truth measurements
collected from GEO batches, KarmaSnapshots, CommentDrafts, and other validated sources.

One snapshot per client per day (UNIQUE constraint on client_id + date).
Used as input to the forecasting engine and stored for historical comparison.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ObservedSnapshot(Base):
    """Immutable snapshot of all observed (measured) metrics for a client.

    metrics_json: array of ObservedMetric dicts, each containing:
      - metric_id (str): e.g. "geo.brand_rate.perplexity"
      - value (float): measured value
      - measured_at (str): ISO datetime
      - time_window (str): "batch" | "24h" | "7d" | "30d"
      - validation (str): "platform_confirmed" | "api_measured" | "system_counted"
      - staleness_threshold_hours (int)
      - is_stale (bool)
      - source_table (str)
      - sample_size (int)
      - confidence (str): "high" | "medium" | "low"

    data_gaps: array of strings describing missing/stale sources.
    source_availability: dict mapping source names to availability status.
    """

    __tablename__ = "observed_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Observed metrics array
    metrics_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Data quality indicators
    data_gaps: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    source_availability: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        Index("ix_obs_client_collected", "client_id", "collected_at"),
    )
