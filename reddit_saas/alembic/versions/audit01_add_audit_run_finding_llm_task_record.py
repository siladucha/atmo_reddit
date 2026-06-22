"""add_audit_run_finding_llm_task_record

Creates:
- audit_runs table (audit execution sessions)
- audit_findings table (individual findings with severity/decision)
- llm_task_records table (LLM task lifecycle tracking)

Revision ID: audit01
Revises: tci01
Create Date: 2026-06-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = "audit01"
down_revision: Union[str, None] = "tci01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- audit_runs table ---
    op.create_table(
        "audit_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("triggered_by", sa.String(length=100), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("go_no_go", sa.Boolean(), nullable=True),
        sa.Column("incident_probability", sa.Integer(), nullable=True),
        sa.Column(
            "block_statuses",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("report_path", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- audit_findings table ---
    op.create_table(
        "audit_findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("block", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("risk_description", sa.String(length=500), nullable=False),
        sa.Column("owner", sa.String(length=100), nullable=False),
        sa.Column("effort", sa.String(length=5), nullable=False),
        sa.Column("risk_if_unresolved", sa.String(length=200), nullable=False),
        sa.Column(
            "decision",
            sa.String(length=30),
            nullable=False,
            server_default="fix_before_release",
        ),
        sa.Column("requirement_ref", sa.String(length=20), nullable=False),
        sa.Column("data_path", sa.Text(), nullable=True),
        sa.Column("eta", sa.String(length=10), nullable=True),
        sa.Column("exemption_reason", sa.Text(), nullable=True),
        sa.Column("exemption_granted_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["audit_runs.id"]),
        sa.ForeignKeyConstraint(["exemption_granted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "NOT (severity = 'red' AND decision != 'fix_before_release' "
            "AND exemption_reason IS NULL)",
            name="ck_red_requires_exemption_or_fix",
        ),
    )
    op.create_index("ix_audit_findings_run_block", "audit_findings", ["run_id", "block"])
    op.create_index("ix_audit_findings_severity", "audit_findings", ["severity"])

    # --- llm_task_records table ---
    op.create_table(
        "llm_task_records",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=False),
        sa.Column("client_id", sa.UUID(), nullable=False),
        sa.Column("avatar_id", sa.UUID(), nullable=True),
        sa.Column("operation", sa.String(length=50), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("previous_state", sa.String(length=20), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("partial_content", sa.Text(), nullable=True),
        sa.Column(
            "failure_history",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["avatar_id"], ["avatars.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("celery_task_id"),
    )
    op.create_index("ix_llm_task_records_state", "llm_task_records", ["state"])
    op.create_index(
        "ix_llm_task_records_client_created", "llm_task_records", ["client_id", "created_at"]
    )


def downgrade() -> None:
    # Drop llm_task_records
    op.drop_index("ix_llm_task_records_client_created", table_name="llm_task_records")
    op.drop_index("ix_llm_task_records_state", table_name="llm_task_records")
    op.drop_table("llm_task_records")

    # Drop audit_findings
    op.drop_index("ix_audit_findings_severity", table_name="audit_findings")
    op.drop_index("ix_audit_findings_run_block", table_name="audit_findings")
    op.drop_table("audit_findings")

    # Drop audit_runs
    op.drop_table("audit_runs")
