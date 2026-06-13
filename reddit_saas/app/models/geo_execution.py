"""GEO Execution models — batch tracking, query results, and frequency metrics."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, Index, Integer, Numeric, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoExecutionBatch(Base):
    """Tracks a group of query executions for a client."""

    __tablename__ = "geo_execution_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(50), nullable=False)  # scheduler | manual | onboarding
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="running")  # running | completed | partial | failed
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    total_queries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    successful_queries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    failed_queries: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_geo_batches_client_id", "client_id"),
        Index("ix_geo_batches_client_started", "client_id", "started_at"),
    )


class GeoQueryResult(Base):
    """Individual query result — one prompt x one run."""

    __tablename__ = "geo_query_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prompt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("geo_prompts.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    execution_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("geo_execution_batches.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)  # perplexity
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    competitors_mentioned: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reddit_urls_found: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    citation_sources: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="success")  # success | failed | timeout
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_geo_results_batch_id", "execution_batch_id"),
        Index("ix_geo_results_prompt_id", "prompt_id"),
        Index("ix_geo_results_client_executed", "client_id", "executed_at"),
    )


class GeoFrequencyMetric(Base):
    """Aggregated frequency metrics per prompt-provider combination within a batch."""

    __tablename__ = "geo_frequency_metrics"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    execution_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("geo_execution_batches.id", ondelete="CASCADE"), nullable=False)
    prompt_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("geo_prompts.id", ondelete="CASCADE"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    total_runs: Mapped[int] = mapped_column(Integer, default=0)
    brand_appearances: Mapped[int] = mapped_column(Integer, default=0)
    brand_appearance_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    competitor_appearances: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reddit_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_geo_metrics_batch_id", "execution_batch_id"),
        Index("ix_geo_metrics_prompt_batch", "prompt_id", "execution_batch_id"),
    )
