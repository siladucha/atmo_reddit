import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    company_profile: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_worldview: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    competitive_landscape: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_voice: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_studies: Mapped[str | None] = mapped_column(Text, nullable=True)
    icp_profiles: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    brand_domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    subreddits = relationship("ClientSubreddit", back_populates="client")  # legacy, kept for migration
    subreddit_assignments = relationship("ClientSubredditAssignment", back_populates="client")
