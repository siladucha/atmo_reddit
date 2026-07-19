import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, String, Integer, DateTime, Numeric, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AIUsageLog(Base):
    __tablename__ = "ai_usage_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    avatar_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True)
    thread_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("reddit_threads.id"), nullable=True)
    subreddit_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)  # scoring | persona_select | generation | editing | hobby_comment
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    triggered_by: Mapped[str | None] = mapped_column(String(100), nullable=True)  # scheduler | manual | orchestrator | api | test_run
    # Quality tracking fields (lqm01 migration)
    quality_outcome: Mapped[str | None] = mapped_column(String(30), nullable=True)  # success | empty | parse_error | timeout | error | fallback_used
    retry_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    fallback_model: Mapped[str | None] = mapped_column(String(255), nullable=True)  # which model succeeded after fallback
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_ai_usage_log_client_created", "client_id", "created_at"),
        Index("ix_ai_usage_log_operation", "operation"),
        Index("ix_ai_usage_log_created_at", "created_at"),
    )
