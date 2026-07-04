"""ab01: A/B Test Framework tables

Creates 6 tables for the Extension Posting A/B Test framework:
- ab_experiments: Experiment configuration and lifecycle
- ab_treatment_groups: Groups within experiment (one per posting method)
- ab_avatar_assignments: Avatar-to-group assignment with eligibility snapshot
- ab_metric_snapshots: Weekly per-avatar health metrics (immutable)
- ab_weekly_reports: Statistical analysis reports per week
- ab_control_violations: Control variable breach records

Also adds `posting_strategy` VARCHAR(50) nullable column to `execution_tasks`.

Revision ID: ab01
Revises: perm01
Create Date: 2026-07-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# revision identifiers, used by Alembic.
revision = "ab01"
down_revision = "perm01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. ab_experiments — experiment configuration and lifecycle
    op.create_table(
        "ab_experiments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        # Configuration
        sa.Column("planned_duration_weeks", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("daily_volume_per_avatar", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("subreddit_risk_max", sa.Integer(), nullable=False, server_default="40"),
        sa.Column("content_type", sa.String(20), nullable=False, server_default="hobby"),
        sa.Column("generation_model", sa.String(100), nullable=False),
        # Lifecycle timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("concluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pause_reason", sa.Text(), nullable=True),
        # Metadata
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("conclusion_summary", JSONB, nullable=True),
        sa.Column("config_history", JSONB, nullable=False, server_default="[]"),
        # Constraints
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'concluded', 'aborted')",
            name="ck_ab_experiments_status",
        ),
    )
    op.create_index("ix_ab_experiments_status", "ab_experiments", ["status"])

    # 2. ab_treatment_groups — one per posting method per experiment
    op.create_table(
        "ab_treatment_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("ab_experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("posting_method", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Constraints
        sa.UniqueConstraint("experiment_id", "posting_method", name="uq_ab_group_experiment_method"),
    )
    op.create_index("ix_ab_groups_experiment", "ab_treatment_groups", ["experiment_id"])

    # 3. ab_avatar_assignments — avatar-to-group with immutable eligibility snapshot
    op.create_table(
        "ab_avatar_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("ab_experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("ab_treatment_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Eligibility snapshot at assignment time (immutable)
        sa.Column("assignment_snapshot", JSONB, nullable=False),
        # Exclusion tracking
        sa.Column("is_excluded", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exclusion_reason", sa.String(100), nullable=True),
        # Constraints
        sa.UniqueConstraint("experiment_id", "avatar_id", name="uq_ab_avatar_experiment"),
    )
    op.create_index("ix_ab_assignments_experiment", "ab_avatar_assignments", ["experiment_id"])
    op.create_index("ix_ab_assignments_avatar", "ab_avatar_assignments", ["avatar_id"])
    op.create_index("ix_ab_assignments_group", "ab_avatar_assignments", ["group_id"])

    # 4. ab_metric_snapshots — weekly per-avatar health metrics (immutable)
    op.create_table(
        "ab_metric_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("ab_experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", UUID(as_uuid=True), sa.ForeignKey("ab_treatment_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Health metrics
        sa.Column("removal_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("total_posted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_deleted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("karma_velocity_4h", sa.Numeric(8, 2), nullable=True),
        sa.Column("karma_velocity_24h", sa.Numeric(8, 2), nullable=True),
        sa.Column("karma_velocity_7d", sa.Numeric(8, 2), nullable=True),
        sa.Column("shadowban_events", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cqs_level_start", sa.String(20), nullable=True),
        sa.Column("cqs_level_end", sa.String(20), nullable=True),
        sa.Column("cqs_changed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("subreddit_bans_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("phase_at_start", sa.Integer(), nullable=False),
        sa.Column("phase_at_end", sa.Integer(), nullable=False),
        sa.Column("phase_promoted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("account_warnings", sa.Integer(), nullable=False, server_default="0"),
        # Control variable compliance
        sa.Column("volume_violations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("subreddit_violations", sa.Integer(), nullable=False, server_default="0"),
        # Task execution metrics
        sa.Column("tasks_attempted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_succeeded", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tasks_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_reasons", JSONB, nullable=True, server_default="{}"),
        # Constraints
        sa.UniqueConstraint("experiment_id", "avatar_id", "week_number", name="uq_ab_metric_avatar_week"),
    )
    op.create_index("ix_ab_metrics_experiment_week", "ab_metric_snapshots", ["experiment_id", "week_number"])
    op.create_index("ix_ab_metrics_group_week", "ab_metric_snapshots", ["group_id", "week_number"])

    # 5. ab_weekly_reports — statistical analysis reports per week
    op.create_table(
        "ab_weekly_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("ab_experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("week_number", sa.Integer(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # Statistical results
        sa.Column("statistics_json", JSONB, nullable=False),
        sa.Column("cumulative_json", JSONB, nullable=False),
        sa.Column("raw_data_json", JSONB, nullable=False),
        # Alert flags
        sa.Column("early_termination_recommended", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("alert_metrics", JSONB, nullable=True, server_default="[]"),
        # Constraints
        sa.UniqueConstraint("experiment_id", "week_number", name="uq_ab_report_experiment_week"),
    )

    # 6. ab_control_violations — control variable breach records
    op.create_table(
        "ab_control_violations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("experiment_id", UUID(as_uuid=True), sa.ForeignKey("ab_experiments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("violation_type", sa.String(50), nullable=False),
        sa.Column("violation_date", sa.Date(), nullable=False),
        sa.Column("details", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_ab_violations_experiment", "ab_control_violations", ["experiment_id", "violation_date"])

    # 7. Add posting_strategy column to execution_tasks
    op.add_column(
        "execution_tasks",
        sa.Column("posting_strategy", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    # Remove posting_strategy column from execution_tasks
    op.drop_column("execution_tasks", "posting_strategy")

    # Drop tables in reverse order (respect FK dependencies)
    op.drop_table("ab_control_violations")
    op.drop_table("ab_weekly_reports")
    op.drop_table("ab_metric_snapshots")
    op.drop_table("ab_avatar_assignments")
    op.drop_table("ab_treatment_groups")
    op.drop_table("ab_experiments")
