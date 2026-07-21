"""Create report_generation_jobs and report_job_events tables.

Revision ID: lro01
Revises: lqm01
Create Date: 2026-07-21

Adds:
- report_generation_jobs: lifecycle tracking for landscape report generation
- report_job_events: append-only audit log of state transitions
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "lro01"
down_revision = "lqm01"
branch_labels = None
depends_on = None


def upgrade():
    # -- report_generation_jobs --
    op.create_table(
        "report_generation_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("onboarding_id", UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_step", sa.String(100), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_cost", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("report_data", JSONB, nullable=True),
        sa.Column("triggered_by", sa.String(50), nullable=False, server_default="portal"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_report_gen_jobs_client_status",
        "report_generation_jobs",
        ["client_id", "status"],
    )
    op.create_index(
        "ix_report_gen_jobs_created",
        "report_generation_jobs",
        ["created_at"],
    )

    # -- report_job_events --
    op.create_table(
        "report_job_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("job_id", UUID(as_uuid=True), sa.ForeignKey("report_generation_jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_index(
        "ix_report_job_events_job_id",
        "report_job_events",
        ["job_id"],
    )
    op.create_index(
        "ix_report_job_events_type_created",
        "report_job_events",
        ["event_type", "created_at"],
    )


def downgrade():
    op.drop_table("report_job_events")
    op.drop_table("report_generation_jobs")
