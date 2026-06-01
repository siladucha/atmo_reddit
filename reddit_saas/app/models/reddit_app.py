"""RedditApp — registered Reddit OAuth/script application for posting.

Each app is scoped to a specific client (blast radius isolation) or to the
shared pool (farm/warming avatars). For password auth MVP, a single script-type
app record suffices for all avatars.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RedditApp(Base):
    __tablename__ = "reddit_apps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Client scoping: NULL = shared pool (farm/warming avatars)
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True
    )

    # Reddit's OAuth client_id string (from /prefs/apps)
    client_id_reddit: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)

    # Encrypted client_secret (Fernet AES-128-CBC)
    client_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)

    app_name: Mapped[str] = mapped_column(String(255), nullable=False)
    app_type: Mapped[str] = mapped_column(String(20), default="script", server_default="script")  # script | web
    registered_under_username: Mapped[str] = mapped_column(String(255), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(500), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Health monitoring (OAuth mode)
    health_status: Mapped[str] = mapped_column(
        String(20), default="unknown", server_default="unknown"
    )  # healthy | suspect | revoked | unknown
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
