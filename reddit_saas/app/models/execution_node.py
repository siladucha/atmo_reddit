import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExecutionNode(Base):
    """Browser extension execution node — a leased runtime on an executor's machine."""

    __tablename__ = "execution_nodes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    executor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    device_fingerprint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    extension_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    active_reddit_username: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    tasks_in_queue: Mapped[int] = mapped_column(Integer, default=0)

    # --- Health monitoring fields (extension v2) ---
    dom_health: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="ok"
    )  # ok | degraded | broken
    dom_health_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # when dom_health last changed
    last_task_executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reddit_session_valid: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True, default=True
    )
    pending_approvals: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
