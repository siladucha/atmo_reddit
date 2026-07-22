"""BugReport model — Engineering Memory incidents stored in PostgreSQL."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.orm import mapped_column, Mapped

from app.database import Base


class BugReport(Base):
    __tablename__ = "bug_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bug_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    problem: Mapped[str] = mapped_column(Text, nullable=False)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    fix: Mapped[str | None] = mapped_column(Text, nullable=True)
    rule: Mapped[str | None] = mapped_column(Text, nullable=True)
    protection: Mapped[str | None] = mapped_column(String(50), nullable=True)  # None/Manual/Test/CI/Prompt/Checklist
    risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)  # Low/Medium/High/Critical
    category: Mapped[str | None] = mapped_column(String(30), nullable=True)  # AI/UX/Backend/Compliance/Integration
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="Reported", index=True)  # Reported/Investigating/Fixed/Verified
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="prod")  # dev/staging/prod
    reporter: Mapped[str] = mapped_column(String(200), nullable=False, default="Client")
    reporter_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    screenshot_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    fixed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    verification_comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self):
        return f"<BugReport {self.bug_id}: {self.title[:40]}>"
