import uuid
from datetime import datetime

from sqlalchemy import Index, String, Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.user_role import UserRole


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    role: Mapped[str] = mapped_column(String(20), default=UserRole.client_viewer.value, server_default="client_viewer")
    client_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("clients.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Email verification
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Password reset
    password_reset_token_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_reset_token_expires: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Telegram notifications
    telegram_chat_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    telegram_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    telegram_notifications_level: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="critical"
    )  # "all", "warning", "critical", "off"

    # Relationships
    client = relationship("Client", foreign_keys=[client_id], lazy="joined")

    __table_args__ = (
        Index("ix_users_role", "role"),
    )

    @property
    def user_role(self) -> UserRole:
        """Return the UserRole enum for this user.

        Falls back to legacy is_superuser check for backward compatibility.
        """
        if self.role:
            try:
                return UserRole(self.role)
            except ValueError:
                pass
        # Legacy fallback
        if self.is_superuser:
            return UserRole.owner
        if self.client_id:
            return UserRole.client_manager
        return UserRole.client_viewer
