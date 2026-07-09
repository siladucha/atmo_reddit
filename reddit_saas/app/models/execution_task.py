"""ExecutionTask — channel-agnostic task delivery for EPG slots and CQS checks.

Represents a single actionable item generated from an approved EPG slot or
a CQS check task, delivered to a human executor via email (MVP), Telegram, or
portal push (future).

Lifecycle: generated -> emailed -> accepted -> submitted -> url_verified -> content_verified -> verified
Terminal states: verified, failed, expired, cancelled

Design: Decoupled from EPG/CommentDraft. ExecutionTask is the execution layer;
CommentDraft is the content layer. Linked but independent.
CQS check tasks have epg_slot_id=NULL (no linked EPG slot).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Float, Index, Integer, Numeric, String, Text,
    ForeignKey, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ExecutionTask(Base):
    __tablename__ = "execution_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)  # TASK-20260619-001
    executor_token: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), unique=True, nullable=False, default=uuid.uuid4
    )

    # --- Source references (immutable after creation) ---
    epg_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("epg_slots.id", ondelete="CASCADE"),
        nullable=True, index=True,  # Nullable for CQS check tasks (no EPG slot)
    )
    draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comment_drafts.id", ondelete="SET NULL"), nullable=True
    )
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reddit_threads.id", ondelete="SET NULL"), nullable=True
    )

    # --- Executor assignment ---
    executor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    executor_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)  # email / telegram / phone (nullable for extension-only delivery)
    executor_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="admin"
    )  # admin | avatar_owner | provider
    delivery_channel: Mapped[str] = mapped_column(
        String(50), nullable=False, default="email"
    )  # email | telegram | portal_push

    # --- Task content (denormalized snapshot, frozen at creation) ---
    task_type: Mapped[str] = mapped_column(String(50), nullable=False, default="comment")  # comment | post | reply | cqs_check
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_url: Mapped[str] = mapped_column(Text, nullable=False)
    thread_title: Mapped[str] = mapped_column(Text, nullable=False)
    avatar_username: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Status lifecycle ---
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="generated"
    )  # generated|emailed|accepted|submitted|url_verified|content_verified|verified|failed|expired|needs_regeneration|cancelled
    status_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    # Full history: [{"status": "emailed", "at": "2026-06-19T18:30:00Z", "by": "system"}]
    status_history: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=list)

    # --- Delivery tracking (denormalized for quick access) ---
    latest_delivery_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    delivery_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Verification ---
    submitted_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- Cancellation (soft delete — tasks are NEVER deleted) ---
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # --- Billing readiness (Audit Patch 6) ---
    billed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    billing_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # --- Extension task lifecycle ---
    execution_node_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_nodes.id", ondelete="SET NULL"), nullable=True
    )
    task_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)  # HMAC-SHA256
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)  # unique
    task_lifecycle_status: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # CREATED/ASSIGNED/EXECUTING/REPORTED/FINALIZED/FAILED/EXPIRED
    probe_type: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # reddit_cqs/submission_visibility/profile_check
    priority: Mapped[str] = mapped_column(String(20), default="content")  # diagnostic/content

    # --- A/B Test: posting strategy override ---
    posting_strategy: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # old_reddit | manual_email | new_reddit_debugger (set by A/B test router)

    # --- Future fields (present, nullable, unused in MVP) ---
    provider_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    cost_per_task: Mapped[float | None] = mapped_column(Float, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # resource_type: owned_avatar | managed_avatar | provider_avatar

    # --- Relationships ---
    epg_slot = relationship("EPGSlot", lazy="joined")
    draft = relationship("CommentDraft", lazy="joined")
    avatar = relationship("Avatar", lazy="joined")
    execution_node = relationship("ExecutionNode", lazy="joined")
    delivery_attempts = relationship("DeliveryAttempt", back_populates="task", lazy="dynamic")

    __table_args__ = (
        Index("ix_execution_tasks_status", "status"),
        Index("ix_execution_tasks_executor_status", "executor_id", "status"),
        Index("ix_execution_tasks_client_created", "client_id", "created_at"),
        Index(
            "ix_execution_tasks_deadline_active",
            "deadline",
            postgresql_where=text(
                "status NOT IN ('verified', 'expired', 'failed', 'cancelled')"
            ),
        ),
        # Partial unique index: one task per EPG slot (only for non-NULL epg_slot_id)
        Index(
            "ix_execution_tasks_epg_slot_id_unique",
            "epg_slot_id",
            unique=True,
            postgresql_where=text("epg_slot_id IS NOT NULL"),
        ),
        # Extension task lifecycle indexes
        Index(
            "ix_execution_tasks_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index("ix_execution_tasks_lifecycle_status", "task_lifecycle_status"),
        Index("ix_execution_tasks_node_id", "execution_node_id"),
    )


class DeliveryAttempt(Base):
    """Individual delivery attempt for an ExecutionTask.

    Separated from ExecutionTask to support:
    - Multiple channels (email, telegram, push)
    - Retry tracking per attempt
    - Idempotency (UNIQUE on task_id + attempt_number)
    - Audit trail of all delivery operations
    """
    __tablename__ = "delivery_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("execution_tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3...

    # Channel
    channel: Mapped[str] = mapped_column(String(50), nullable=False)  # email | telegram | portal_push
    recipient: Mapped[str] = mapped_column(String(255), nullable=False)  # email addr / chat_id / user_id

    # Delivery result
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )  # pending | sent | failed | bounced
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Provider tracking
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)  # SMTP Message-ID
    provider_response: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Content audit (NOT full body — per design v2)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    template_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    body_excerpt: Mapped[str | None] = mapped_column(String(200), nullable=True)  # First 200 chars

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationship
    task = relationship("ExecutionTask", back_populates="delivery_attempts")

    __table_args__ = (
        UniqueConstraint("task_id", "attempt_number", name="uq_delivery_attempt_task_number"),
        Index("ix_delivery_attempts_task_id", "task_id"),
        Index("ix_delivery_attempts_status_sent", "status", "sent_at"),
    )
