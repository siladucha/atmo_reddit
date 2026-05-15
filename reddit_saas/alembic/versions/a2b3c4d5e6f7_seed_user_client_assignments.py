"""Seed UserClientAssignment records for existing users.

Revision ID: a2b3c4d5e6f7
Revises: z6a7b8c9d0e1
Create Date: 2026-05-13

DATA MIGRATION: Seeds user_client_assignments records for existing users
whose role is 'client_manager' or 'client_viewer' and client_id IS NOT NULL.

NOTE: This migration MUST run AFTER the schema migration from task 1.7
that creates the user_client_assignments table. Update down_revision
to point to the 1.7 migration revision once it is created.

For each qualifying user:
- Copies user_id and client_id from the users table
- Copies the role value from the user record
- Sets is_active = True
- Generates a UUID for the id column

Users with null client_id are skipped without error (Requirement 10.8).
"""

from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Seed UserClientAssignment records for existing users with
    # role in (client_manager, client_viewer) and non-null client_id.
    # Uses gen_random_uuid() for PostgreSQL UUID generation.
    op.execute("""
        INSERT INTO user_client_assignments (id, user_id, client_id, role, is_active, created_at)
        SELECT
            gen_random_uuid(),
            u.id,
            u.client_id,
            u.role,
            true,
            NOW()
        FROM users u
        WHERE u.role IN ('client_manager', 'client_viewer')
          AND u.client_id IS NOT NULL
        ON CONFLICT (user_id, client_id) DO NOTHING
    """)


def downgrade() -> None:
    # Remove all seeded records from user_client_assignments.
    # This is safe because this migration only seeds data — the table
    # itself is created by the schema migration (task 1.7).
    op.execute("DELETE FROM user_client_assignments")
