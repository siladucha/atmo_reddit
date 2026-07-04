"""Browser extension schema: execution_nodes table + avatar epg_mode + execution_tasks fields.

Creates:
- execution_nodes table (browser extension runtime nodes)

Adds columns:
- avatars.epg_mode (String(20), default "required")
- execution_tasks.execution_node_id (UUID FK → execution_nodes.id)
- execution_tasks.task_hash (String(128), HMAC-SHA256 signature)
- execution_tasks.lease_expires_at (DateTime with timezone)
- execution_tasks.idempotency_key (String(255), unique index)
- execution_tasks.task_lifecycle_status (String(50))
- execution_tasks.probe_type (String(50))
- execution_tasks.priority (String(20), default "content")

Also merges heads: cqs_tasks_01 + stab02.

Revision ID: ext01
Revises: cqs_tasks_01, stab02
Create Date: 2026-06-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "ext01"
down_revision = ("cqs_tasks_01", "stab02")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- 1. Create execution_nodes table ---
    op.create_table(
        "execution_nodes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("executor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("device_fingerprint", sa.String(255), nullable=True),
        sa.Column("extension_version", sa.String(50), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_online", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("active_reddit_username", sa.String(255), nullable=True),
        sa.Column("tasks_in_queue", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_execution_nodes_executor_id", "execution_nodes", ["executor_id"])
    op.create_index("ix_execution_nodes_is_online", "execution_nodes", ["is_online"])

    # --- 2. Add epg_mode to avatars ---
    op.add_column(
        "avatars",
        sa.Column("epg_mode", sa.String(20), nullable=False, server_default="required"),
    )

    # --- 3. Add browser extension fields to execution_tasks ---
    op.add_column(
        "execution_tasks",
        sa.Column("execution_node_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_execution_tasks_execution_node_id",
        "execution_tasks",
        "execution_nodes",
        ["execution_node_id"],
        ["id"],
    )

    op.add_column(
        "execution_tasks",
        sa.Column("task_hash", sa.String(128), nullable=True),
    )

    op.add_column(
        "execution_tasks",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.add_column(
        "execution_tasks",
        sa.Column("idempotency_key", sa.String(255), nullable=True),
    )
    op.create_index(
        "ix_execution_tasks_idempotency_key",
        "execution_tasks",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    op.add_column(
        "execution_tasks",
        sa.Column("task_lifecycle_status", sa.String(50), nullable=True),
    )

    op.add_column(
        "execution_tasks",
        sa.Column("probe_type", sa.String(50), nullable=True),
    )

    op.add_column(
        "execution_tasks",
        sa.Column("priority", sa.String(20), nullable=False, server_default="content"),
    )


def downgrade() -> None:
    # --- Remove execution_tasks columns ---
    op.drop_column("execution_tasks", "priority")
    op.drop_column("execution_tasks", "probe_type")
    op.drop_column("execution_tasks", "task_lifecycle_status")
    op.drop_index("ix_execution_tasks_idempotency_key", table_name="execution_tasks")
    op.drop_column("execution_tasks", "idempotency_key")
    op.drop_column("execution_tasks", "lease_expires_at")
    op.drop_column("execution_tasks", "task_hash")
    op.drop_constraint("fk_execution_tasks_execution_node_id", "execution_tasks", type_="foreignkey")
    op.drop_column("execution_tasks", "execution_node_id")

    # --- Remove avatars.epg_mode ---
    op.drop_column("avatars", "epg_mode")

    # --- Drop execution_nodes table ---
    op.drop_index("ix_execution_nodes_is_online", table_name="execution_nodes")
    op.drop_index("ix_execution_nodes_executor_id", table_name="execution_nodes")
    op.drop_table("execution_nodes")
