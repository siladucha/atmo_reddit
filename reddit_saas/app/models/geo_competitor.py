"""GEO Competitor model — competitor entities tracked per client."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Index, String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GeoCompetitor(Base):
    __tablename__ = "geo_competitors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False)
    competitor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    competitor_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aliases: Mapped[dict | None] = mapped_column(JSONB, nullable=True, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_geo_competitors_client_id", "client_id"),
        Index("ix_geo_competitors_client_active", "client_id", "is_active"),
    )
