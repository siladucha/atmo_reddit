import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey, Index, func, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


# AvatarDraft status constants
DRAFT_STATUS_PENDING_FETCH = "pending_fetch"
DRAFT_STATUS_ANALYZING = "analyzing"
DRAFT_STATUS_READY_FOR_REVIEW = "ready_for_review"
DRAFT_STATUS_CONFIRMED = "confirmed"
DRAFT_STATUS_REJECTED = "rejected"
DRAFT_STATUS_FETCH_FAILED = "fetch_failed"
DRAFT_STATUS_ANALYSIS_FAILED = "analysis_failed"

# Status groups
DRAFT_NON_TERMINAL_STATUSES = (
    DRAFT_STATUS_PENDING_FETCH,
    DRAFT_STATUS_ANALYZING,
    DRAFT_STATUS_READY_FOR_REVIEW,
)
DRAFT_TERMINAL_STATUSES = (
    DRAFT_STATUS_CONFIRMED,
    DRAFT_STATUS_REJECTED,
    DRAFT_STATUS_FETCH_FAILED,
    DRAFT_STATUS_ANALYSIS_FAILED,
)
DRAFT_IN_PROGRESS_STATUSES = (
    DRAFT_STATUS_PENDING_FETCH,
    DRAFT_STATUS_ANALYZING,
)


class AvatarDraft(Base):
    """Intermediate entity for BYOA (Bring Your Own Avatar) async provisioning.

    Represents a Reddit account undergoing analysis before becoming a confirmed Avatar.

    State machine:
        pending_fetch -> analyzing -> ready_for_review -> confirmed | rejected
        Error states (from pending_fetch or analyzing): fetch_failed, analysis_failed

    Terminal states: confirmed, rejected, fetch_failed, analysis_failed
    Non-terminal states: pending_fetch, analyzing, ready_for_review
    """

    __tablename__ = "avatar_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reddit_username: Mapped[str] = mapped_column(String(20), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # State machine
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DRAFT_STATUS_PENDING_FETCH, server_default=DRAFT_STATUS_PENDING_FETCH
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Reddit data (stored after FETCH_REDDIT_PROFILE completes)
    reddit_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # AI analysis result (stored after AI_PROFILE_ANALYSIS completes)
    ai_analysis: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Confirmed avatar reference (set when draft is confirmed into an Avatar)
    avatar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    fetch_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetch_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # Only one non-terminal draft per (reddit_username, client_id) at a time
        Index(
            "ix_avatar_draft_active_username_client",
            "reddit_username",
            "client_id",
            unique=True,
            postgresql_where=text("status IN ('pending_fetch', 'analyzing', 'ready_for_review')"),
        ),
        # Fast lookup of in-progress drafts per client (for trial limit check)
        Index(
            "ix_avatar_draft_client_active",
            "client_id",
            "status",
            postgresql_where=text("status IN ('pending_fetch', 'analyzing', 'ready_for_review')"),
        ),
    )

    @property
    def is_terminal(self) -> bool:
        """Whether this draft is in a final state (no further transitions possible)."""
        return self.status in DRAFT_TERMINAL_STATUSES

    @property
    def is_in_progress(self) -> bool:
        """Whether this draft is being processed (fetch or analysis running)."""
        return self.status in DRAFT_IN_PROGRESS_STATUSES

    def __repr__(self) -> str:
        return f"<AvatarDraft u/{self.reddit_username} status={self.status} client={self.client_id}>"
