"""Add role field to users table.

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-05-12

Adds a `role` column to the users table for role-based access control.
Migrates existing users:
- is_superuser=True → role='owner'
- is_superuser=False + client_id IS NOT NULL → role='client_manager'
- is_superuser=False + client_id IS NULL → role='qa'

The is_superuser column is kept for backward compatibility but role takes precedence.
"""

from alembic import op
import sqlalchemy as sa

revision = "z6a7b8c9d0e1"
down_revision = "y5z6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add role column with default
    op.add_column(
        "users",
        sa.Column("role", sa.String(20), server_default="client_viewer", nullable=False),
    )

    # Migrate existing data
    op.execute("""
        UPDATE users SET role = 'owner' WHERE is_superuser = true
    """)
    op.execute("""
        UPDATE users SET role = 'client_manager'
        WHERE is_superuser = false AND client_id IS NOT NULL
    """)
    op.execute("""
        UPDATE users SET role = 'qa'
        WHERE is_superuser = false AND client_id IS NULL AND role = 'client_viewer'
    """)


def downgrade() -> None:
    op.drop_column("users", "role")
