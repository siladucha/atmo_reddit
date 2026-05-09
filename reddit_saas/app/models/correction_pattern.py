import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CorrectionPattern(Base):
    __tablename__ = "correction_patterns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False)

    pattern_type: Mapped[str] = mapped_column(String(50), nullable=False)
    rule_text: Mapped[str] = mapped_column(String(100), nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "pattern_type IN ("
            "'length_adjustment', 'tone_shift', 'vocabulary_change', "
            "'structure_change', 'content_removal', 'content_addition')",
            name="chk_pattern_type",
        ),
        Index(
            "ix_correction_patterns_avatar_client_rule",
            "avatar_id", "client_id", "rule_text",
            unique=True,
        ),
        Index(
            "ix_correction_patterns_frequency",
            "avatar_id", "client_id", frequency.desc(),
        ),
    )
