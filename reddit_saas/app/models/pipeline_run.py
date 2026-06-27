"""PipelineRun — tracks each pipeline execution as a first-class entity.

Provides end-to-end observability: which avatar, what stage, when started,
what happened, how long it took. Replaces manual log-digging.

Lifecycle: queued → running → completed / failed / partial
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # What triggered this run
    pipeline_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # epg_build | scoring | generation | hobby_generation | health_check | karma_tracking | scraping
    trigger_source: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="scheduler"
    )  # scheduler | manual | retry | deploy_catchup

    # Context
    avatar_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="running"
    )  # running | completed | failed | partial
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Results
    items_processed: Mapped[int] = mapped_column(Integer, server_default="0")
    items_succeeded: Mapped[int] = mapped_column(Integer, server_default="0")
    items_failed: Mapped[int] = mapped_column(Integer, server_default="0")
    items_skipped: Mapped[int] = mapped_column(Integer, server_default="0")

    # Error info
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Detailed step-level data (optional, for drill-down)
    steps: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Metadata
    meta: Mapped[dict | None] = mapped_column("run_meta", JSONB, nullable=True)

    __table_args__ = (
        Index("ix_pipeline_runs_type_started", "pipeline_type", "started_at"),
        Index("ix_pipeline_runs_avatar_started", "avatar_id", "started_at"),
        Index("ix_pipeline_runs_status", "status"),
    )

    def complete(self, items_succeeded: int = 0, items_failed: int = 0, items_skipped: int = 0):
        """Mark run as completed."""
        from datetime import timezone as tz
        self.status = "completed" if items_failed == 0 else "partial"
        self.completed_at = datetime.now(tz.utc)
        self.items_succeeded = items_succeeded
        self.items_failed = items_failed
        self.items_skipped = items_skipped
        if self.started_at:
            self.duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )

    def fail(self, error_message: str, error_type: str = "unknown"):
        """Mark run as failed."""
        from datetime import timezone as tz
        self.status = "failed"
        self.completed_at = datetime.now(tz.utc)
        self.error_message = error_message[:2000]
        self.error_type = error_type
        if self.started_at:
            self.duration_ms = int(
                (self.completed_at - self.started_at).total_seconds() * 1000
            )
