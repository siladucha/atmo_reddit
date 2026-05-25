"""Add avatar_manager role to user roles.

Revision ID: a3b4c5d6e7f8
Revises: 6da36db9c7c4
Create Date: 2026-05-25

Adds the 'avatar_manager' role value. Since the role column is VARCHAR(20)
(not a PostgreSQL ENUM type), no schema change is needed — this migration
exists for documentation and to increase the column width to accommodate
the new role name (15 chars, within 20 limit).
"""

from alembic import op
import sqlalchemy as sa

revision = "a3b4c5d6e7f8"
down_revision = "6da36db9c7c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No schema change needed — role is VARCHAR(20) and 'avatar_manager' is 14 chars.
    # This migration serves as documentation that the role was added.
    pass


def downgrade() -> None:
    # Reset any avatar_manager users back to client_viewer (safe default)
    op.execute("""
        UPDATE users SET role = 'client_viewer' WHERE role = 'avatar_manager'
    """)
