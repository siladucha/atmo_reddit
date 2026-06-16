"""ClientActionLog — tracks rate-limited actions triggered by client users.

Used to enforce daily/weekly limits on expensive operations:
- pipeline: full pipeline run (scrape > score > generate) — max 2/day
- epg_rebuild: EPG rebuild for client's avatars — max 1/day
- strategy: strategy generation per avatar — max 1/week per avatar
- discovery: discovery session creation — max 2/week
- regenerate: individual draft regeneration — unlimited (tracked for analytics)
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ClientActionLog(Base):
    __tablename__ = "client_action_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )
    triggered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # Optional: for per-avatar rate limits (strategy generation)
    avatar_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=True
    )
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "ix_client_action_log_client_type_time",
            "client_id",
            "action_type",
            triggered_at.desc(),
        ),
    )
