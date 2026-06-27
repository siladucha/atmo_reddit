"""Pipeline Run tracking table for observability.

Revision ID: stab02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "stab02"
down_revision = "stab01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("pipeline_type", sa.String(50), nullable=False),
        sa.Column("trigger_source", sa.String(50), nullable=False, server_default="scheduler"),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("items_processed", sa.Integer, server_default="0"),
        sa.Column("items_succeeded", sa.Integer, server_default="0"),
        sa.Column("items_failed", sa.Integer, server_default="0"),
        sa.Column("items_skipped", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("steps", JSONB, nullable=True),
        sa.Column("run_meta", JSONB, nullable=True),
    )
    op.create_index("ix_pipeline_runs_type_started", "pipeline_runs", ["pipeline_type", "started_at"])
    op.create_index("ix_pipeline_runs_avatar_started", "pipeline_runs", ["avatar_id", "started_at"])
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])


def downgrade() -> None:
    op.drop_table("pipeline_runs")
