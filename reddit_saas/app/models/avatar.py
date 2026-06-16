import uuid
from datetime import datetime

from sqlalchemy import String, Text, Boolean, Integer, DateTime, Numeric, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.avatar_pool import AvatarPool  # noqa: F401 — re-exported for convenience
from app.models.health_status import HealthStatus  # noqa: F401 — referenced for validation/documentation


class Avatar(Base):
    __tablename__ = "avatars"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    reddit_username: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


    # Client-facing persona (hidden: reddit_username, raw karma from client view)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    persona_bio: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Pool & industry classification
    pool: Mapped[str] = mapped_column(String(20), default="b2b", server_default="b2b", nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Farm / rental
    is_farm_avatar: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    rent_price: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)

    # Voice & personality
    voice_profile_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    tone_principles: Mapped[str | None] = mapped_column(Text, nullable=True)
    speech_patterns: Mapped[str | None] = mapped_column(Text, nullable=True)
    hill_i_die_on: Mapped[str | None] = mapped_column(Text, nullable=True)
    helpful_mode_topics: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    vocabulary_lean: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Subreddits
    hobby_subreddits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    business_subreddits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Health & karma
    karma_post: Mapped[int] = mapped_column(Integer, default=0)
    karma_comment: Mapped[int] = mapped_column(Integer, default=0)
    is_shadowbanned: Mapped[bool] = mapped_column(Boolean, default=False)

    # Visibility health, populated by services/health_checker.py.
    # Requires migration p6q7r8s9t0u1_add_avatar_health_check_fields.
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_status: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    health_status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_check_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    consecutive_check_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Reddit status cache (populated by services/reddit_status.py)
    reddit_status: Mapped[str] = mapped_column(String(20), default="unknown", server_default="unknown")
    reddit_karma_comment: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reddit_karma_post: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reddit_account_created: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reddit_icon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reddit_status_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Warming phase
    warming_phase: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    phase_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_phase_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Freeze controls
    is_frozen: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    freeze_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # CQS (Contributor Quality Score) — Reddit's hidden trust classification
    # Levels: lowest, low, moderate, high, highest
    cqs_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cqs_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cqs_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Subreddit presence scan
    presence_last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    presence_scan_status: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- Automated Posting ---
    # Proxy & fingerprint
    proxy_url_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_agent_string: Mapped[str | None] = mapped_column(String(500), nullable=True)
    declared_timezone: Mapped[str] = mapped_column(String(50), default="America/New_York", server_default="America/New_York")

    # Posting control
    posting_mode: Mapped[str] = mapped_column(String(20), default="disabled", server_default="disabled")  # auto | disabled
    reddit_app_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("reddit_apps.id"), nullable=True
    )

    # Auth credentials (encrypted — Fernet AES-128-CBC)
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    reddit_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Posting state
    last_posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_posted_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    consecutive_post_failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
