"""Audit models — AuditRun, AuditFinding, LLMTaskRecord.

AuditRun: tracks a single audit execution session (all blocks run together).
AuditFinding: individual finding produced by an audit block.
LLMTaskRecord: tracks LLM task lifecycle states for reliability monitoring.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditRun(Base):
    """Tracks a single audit execution session (all blocks run together)."""

    __tablename__ = "audit_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # pending | running | completed | failed
    triggered_by: Mapped[str] = mapped_column(String(100), nullable=False)
    # "manual:{user_id}" | "scheduled" | "api:{user_id}"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    go_no_go: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # True=GO, False=NO-GO, None=not yet calculated
    incident_probability: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 0-100 percentage
    block_statuses: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    # {"data_leakage": "completed", "credit_integrity": "running", ...}
    report_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # e.g. "AUDIT_REPORT_2026-06-20.md"


class AuditFinding(Base):
    """Individual finding produced by an audit block."""

    __tablename__ = "audit_findings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("audit_runs.id"), nullable=False
    )
    block: Mapped[str] = mapped_column(String(50), nullable=False)
    # AuditBlockName value: data_leakage | credit_integrity | rate_limit_coverage | ...
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    # red | yellow | green
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    # reliability | performance | security | product | data_leakage | ...
    risk_description: Mapped[str] = mapped_column(String(500), nullable=False)
    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    effort: Mapped[str] = mapped_column(String(5), nullable=False)
    # S | M | L | XL
    risk_if_unresolved: Mapped[str] = mapped_column(String(200), nullable=False)
    decision: Mapped[str] = mapped_column(String(30), nullable=False, default="fix_before_release")
    # fix_before_release | defer_to_post_release | accept
    requirement_ref: Mapped[str] = mapped_column(String(20), nullable=False)
    # "1.2", "7.3" etc.
    data_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where the violation was found
    eta: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # YYYY-MM-DD or None
    exemption_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Required when decision=accept and severity=red (min 10 chars)
    exemption_granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("ix_audit_findings_run_block", "run_id", "block"),
        Index("ix_audit_findings_severity", "severity"),
        CheckConstraint(
            "NOT (severity = 'red' AND decision != 'fix_before_release' "
            "AND exemption_reason IS NULL)",
            name="ck_red_requires_exemption_or_fix",
        ),
    )


class LLMTaskRecord(Base):
    """Tracks LLM task lifecycle states for reliability monitoring."""

    __tablename__ = "llm_task_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    celery_task_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False
    )
    avatar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True
    )
    operation: Mapped[str] = mapped_column(String(50), nullable=False)
    # scoring | generation | persona_select | editing | hobby_comment
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    # CREATED | QUEUED | SENT | IN_PROGRESS | PARTIAL | COMPLETED | FAILED | RECOVERABLE | LOST
    previous_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    partial_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_history: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # [{"attempt": 1, "reason": "timeout", "at": "..."}, ...]
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_llm_task_records_state", "state"),
        Index("ix_llm_task_records_client_created", "client_id", "created_at"),
    )
