"""Make epg_slot_id nullable on execution_tasks for CQS check tasks.

- ALTER COLUMN epg_slot_id DROP NOT NULL
- Drop the existing UNIQUE constraint on epg_slot_id
- Create partial unique index WHERE epg_slot_id IS NOT NULL (preserves idempotency for EPG tasks)

Revision ID: cqs_tasks_01
Revises: pe01
Create Date: 2026-06-27
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = "cqs_tasks_01"
down_revision = "pe01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop the existing UNIQUE constraint on epg_slot_id
    # The constraint was created by sa.UniqueConstraint('epg_slot_id') in the original migration,
    # which generates the name "execution_tasks_epg_slot_id_key" by PostgreSQL convention.
    op.drop_constraint("execution_tasks_epg_slot_id_key", "execution_tasks", type_="unique")

    # 2. Make epg_slot_id nullable (DROP NOT NULL)
    op.alter_column(
        "execution_tasks",
        "epg_slot_id",
        existing_type=sa.UUID(),
        nullable=True,
    )

    # 3. Create partial unique index WHERE epg_slot_id IS NOT NULL
    # This preserves the one-task-per-slot idempotency for EPG tasks
    # while allowing multiple rows with NULL (CQS check tasks)
    op.create_index(
        "ix_execution_tasks_epg_slot_id_unique",
        "execution_tasks",
        ["epg_slot_id"],
        unique=True,
        postgresql_where=sa.text("epg_slot_id IS NOT NULL"),
    )


def downgrade() -> None:
    # Drop the partial unique index
    op.drop_index("ix_execution_tasks_epg_slot_id_unique", table_name="execution_tasks")

    # Restore NOT NULL (will fail if any NULL values exist)
    op.alter_column(
        "execution_tasks",
        "epg_slot_id",
        existing_type=sa.UUID(),
        nullable=False,
    )

    # Restore the original UNIQUE constraint
    op.create_unique_constraint(
        "execution_tasks_epg_slot_id_key", "execution_tasks", ["epg_slot_id"]
    )
