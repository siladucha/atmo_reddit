"""Fix missing columns from stripe01 migration.

stripe01 was stamped (not applied) on prod during a pg_restore scenario.
This migration adds the missing column idempotently.

Revision ID: stripe01_fix
Revises: 66d0a72d616f
Create Date: 2026-07-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "stripe01_fix"
down_revision = "66d0a72d616f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Check which columns are missing and add them
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_columns = {col["name"] for col in inspector.get_columns("clients")}

    if "subscription_canceled_at" not in existing_columns:
        op.add_column(
            "clients",
            sa.Column("subscription_canceled_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("clients", "subscription_canceled_at")
