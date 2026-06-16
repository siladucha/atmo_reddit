"""VoiceFeedback — captures free-text voice/tone feedback from client users.

Used to refine AI generation style. Each entry is a training signal
stored for future injection into comment generation prompts.
"""

import uuid
from datetime import datetime

from sqlalchemy import Text, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class VoiceFeedback(Base):
    __tablename__ = "voice_feedback"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    feedback_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    client = relationship("Client", backref="voice_feedbacks")
    user = relationship("User", backref="voice_feedbacks")
