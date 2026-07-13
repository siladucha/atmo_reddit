"""Plan definitions — source of truth for all per-plan limits.

Replaces the hardcoded PLAN_LIMITS dict in plan_limits.py.
Runtime-modifiable via admin UI without deploy.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlanDefinition(Base):
    __tablename__ = "plan_definitions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_type: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    price_usd: Mapped[int] = mapped_column(Integer, nullable=False)  # monthly price in USD (whole dollars)
    stripe_price_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Limits
    max_actions_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    max_avatars: Mapped[int] = mapped_column(Integer, nullable=False)
    max_subreddits: Mapped[int] = mapped_column(Integer, nullable=False)
    max_professional_subreddits: Mapped[int] = mapped_column(Integer, nullable=False)
    max_posts_per_month: Mapped[int] = mapped_column(Integer, nullable=False)
    max_keywords: Mapped[int] = mapped_column(Integer, nullable=False)
    geo_monitoring_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    geo_prompts_limit: Mapped[int] = mapped_column(Integer, nullable=False)

    # Metadata
    is_self_serve: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    tier_order: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=trial, 1=seed, ..., 5=agency

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self) -> str:
        return f"<PlanDefinition {self.plan_type} (${self.price_usd}/mo, {self.max_actions_per_month} actions)>"
