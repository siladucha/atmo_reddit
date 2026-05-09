import uuid
from datetime import datetime

from sqlalchemy import Index, Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AnalysisEditRecord(Base):
    __tablename__ = "analysis_edit_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    avatar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False)
    llm_output: Mapped[dict] = mapped_column(JSONB, nullable=False)
    human_edited: Mapped[dict] = mapped_column(JSONB, nullable=False)
    diff_summary: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_analysis_edit_records_avatar_created", "avatar_id", created_at.desc()),
    )
