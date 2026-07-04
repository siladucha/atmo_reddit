"""Add email verification and password reset fields to users table.

Revision ID: ev01
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "ev01"
down_revision = "ed0197e3d7e7"  # merge of ext02 and hp01
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("verification_token_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("verification_token_expires", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("password_reset_token_hash", sa.String(255), nullable=True))
    op.add_column("users", sa.Column("password_reset_token_expires", sa.DateTime(timezone=True), nullable=True))

    # Mark all existing users as verified (they were created before this feature)
    op.execute("UPDATE users SET email_verified = true, email_verified_at = now()")


def downgrade() -> None:
    op.drop_column("users", "password_reset_token_expires")
    op.drop_column("users", "password_reset_token_hash")
    op.drop_column("users", "verification_token_expires")
    op.drop_column("users", "verification_token_hash")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
