"""Report Generation Job & Event models — lifecycle tracking for landscape report generation.

ReportGenerationJob tracks the full lifecycle of a single report generation attempt:
pending → processing → completed | failed

ReportJobEvent is an append-only audit log of state transitions for a job.
"""

import uuid
from datetime import datetime

from sqlalchemy import Float, Index, Integer, String, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ReportGenerationJob(Base):
    __tablename__ = "report_generation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    onboarding_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Status lifecycle: pending → processing → completed | failed
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Error tracking
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_step: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # AI cost tracking (for future sample_drafts LLM calls)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Report data (immutable after completion)
    report_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Metadata
    triggered_by: Mapped[str] = mapped_column(String(50), nullable=False, default="portal")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    events = relationship("ReportJobEvent", back_populates="job", lazy="dynamic")

    __table_args__ = (
        Index("ix_report_gen_jobs_client_status", "client_id", "status"),
        Index("ix_report_gen_jobs_created", "created_at"),
    )


class ReportJobEvent(Base):
    __tablename__ = "report_job_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("report_generation_jobs.id", ondelete="CASCADE"), nullable=False)

    # Event classification
    # Types: REPORT_STARTED, STEP_COMPLETED, REPORT_COMPLETED, REPORT_FAILED,
    #        JSON_VALIDATION_FAILED, DEDUP_BLOCKED
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Structured payload
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    job = relationship("ReportGenerationJob", back_populates="events")

    __table_args__ = (
        Index("ix_report_job_events_job_id", "job_id"),
        Index("ix_report_job_events_type_created", "event_type", "created_at"),
    )
