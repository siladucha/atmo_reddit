"""A/B Test Framework models — Extension Posting Method Experiment.

Models for managing controlled experiments comparing posting methods
(old_reddit, manual_email, new_reddit_debugger) and measuring their
impact on avatar health metrics.

Tables:
- ab_experiments: Experiment configuration and lifecycle
- ab_treatment_groups: Groups within an experiment (one per posting method)
- ab_avatar_assignments: Avatar-to-group assignment with eligibility snapshot
- ab_metric_snapshots: Weekly per-avatar health metrics (immutable)
- ab_weekly_reports: Statistical analysis reports per week
- ab_control_violations: Control variable breach records
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, Index, Integer,
    Numeric, String, Text, ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ExperimentRun(Base):
    """A/B test experiment — top-level configuration and lifecycle."""

    __tablename__ = "ab_experiments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )

    # Configuration
    planned_duration_weeks: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8
    )
    daily_volume_per_avatar: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    subreddit_risk_max: Mapped[int] = mapped_column(
        Integer, nullable=False, default=40
    )
    content_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="hobby"
    )
    generation_model: Mapped[str] = mapped_column(String(100), nullable=False)

    # Lifecycle timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    concluded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadata
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    conclusion_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    config_history: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'concluded', 'aborted')",
            name="ck_ab_experiments_status",
        ),
        Index("ix_ab_experiments_status", "status"),
    )


class TreatmentGroup(Base):
    """Treatment group within an experiment — one per posting method."""

    __tablename__ = "ab_treatment_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ab_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    posting_method: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "posting_method",
            name="uq_ab_group_experiment_method",
        ),
        Index("ix_ab_groups_experiment", "experiment_id"),
    )


class AvatarAssignment(Base):
    """Avatar-to-group assignment with immutable eligibility snapshot."""

    __tablename__ = "ab_avatar_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ab_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ab_treatment_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Eligibility snapshot at assignment time (immutable)
    assignment_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Exclusion tracking
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    excluded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    exclusion_reason: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "avatar_id",
            name="uq_ab_avatar_experiment",
        ),
        Index("ix_ab_assignments_experiment", "experiment_id"),
        Index("ix_ab_assignments_avatar", "avatar_id"),
        Index("ix_ab_assignments_group", "group_id"),
    )


class MetricSnapshot(Base):
    """Weekly per-avatar health metric snapshot (immutable once written)."""

    __tablename__ = "ab_metric_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ab_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("avatars.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ab_treatment_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Health metrics
    removal_rate: Mapped[float | None] = mapped_column(
        Numeric(5, 4), nullable=True
    )
    total_posted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_deleted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    karma_velocity_4h: Mapped[float | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    karma_velocity_24h: Mapped[float | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    karma_velocity_7d: Mapped[float | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )

    shadowban_events: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    cqs_level_start: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    cqs_level_end: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    cqs_changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    subreddit_bans_new: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    phase_at_start: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_at_end: Mapped[int] = mapped_column(Integer, nullable=False)
    phase_promoted: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    account_warnings: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Control variable compliance
    volume_violations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    subreddit_violations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )

    # Task execution metrics
    tasks_attempted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    tasks_succeeded: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    tasks_failed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failure_reasons: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "avatar_id", "week_number",
            name="uq_ab_metric_avatar_week",
        ),
        Index(
            "ix_ab_metrics_experiment_week", "experiment_id", "week_number"
        ),
        Index("ix_ab_metrics_group_week", "group_id", "week_number"),
    )


class WeeklyReport(Base):
    """Statistical analysis report generated per experiment per week."""

    __tablename__ = "ab_weekly_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ab_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    week_number: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Statistical results per metric
    statistics_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Cumulative analysis (all weeks up to this point)
    cumulative_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Raw data for transparency
    raw_data_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # Alert flags
    early_termination_recommended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    alert_metrics: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, server_default="[]"
    )

    __table_args__ = (
        UniqueConstraint(
            "experiment_id", "week_number",
            name="uq_ab_report_experiment_week",
        ),
    )


class ControlViolation(Base):
    """Record of a control variable violation during an experiment."""

    __tablename__ = "ab_control_violations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    experiment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ab_experiments.id", ondelete="CASCADE"),
        nullable=False,
    )
    avatar_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("avatars.id"), nullable=False
    )
    violation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    violation_date: Mapped[date] = mapped_column(Date, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "ix_ab_violations_experiment",
            "experiment_id", "violation_date",
        ),
    )
