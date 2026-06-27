"""Add execution_source and execution_task_id to posting_events.

These columns were added to the model (Audit Patch 4) but never migrated.
Fixes: ProgrammingError on /admin/posting — "column posting_events.execution_source does not exist"

Revision ID: pe01
Revises: asb01
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision = "pe01"
down_revision = "asb01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "posting_events",
        sa.Column("execution_source", sa.String(50), nullable=True),
    )
    op.add_column(
        "posting_events",
        sa.Column("execution_task_id", UUID(as_uuid=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("posting_events", "execution_task_id")
    op.drop_column("posting_events", "execution_source")
