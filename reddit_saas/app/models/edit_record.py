import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EditRecord(Base):
    __tablename__ = "edit_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    comment_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comment_drafts.id"), nullable=False
    )
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False
    )

    # Content
    ai_draft: Mapped[str] = mapped_column(Text, nullable=False)
    edited_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    edit_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Context
    subreddit: Mapped[str] = mapped_column(String(255), nullable=False)
    engagement_mode: Mapped[str | None] = mapped_column(String(100), nullable=True)
    post_title: Mapped[str] = mapped_column(Text, nullable=False)
    post_body: Mapped[str | None] = mapped_column(String(500), nullable=True)
    final_status: Mapped[str] = mapped_column(String(50), nullable=False)

    # Lifecycle
    is_archived: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "final_status IN ('approved', 'approved_unchanged', 'rejected')",
            name="chk_final_status",
        ),
        Index("ix_edit_records_avatar_client", "avatar_id", "client_id"),
        Index(
            "ix_edit_records_avatar_client_created",
            "avatar_id",
            "client_id",
            created_at.desc(),
        ),
        Index("ix_edit_records_subreddit", "avatar_id", "client_id", "subreddit"),
        Index(
            "ix_edit_records_not_archived",
            "avatar_id",
            "client_id",
            postgresql_where=text("is_archived = FALSE"),
        ),
    )
