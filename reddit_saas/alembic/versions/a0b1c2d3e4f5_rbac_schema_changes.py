"""RBAC schema changes: user_client_assignments, avatar_rentals, client/avatar columns, users.role index.

Revision ID: a0b1c2d3e4f5
Revises: a1b2c3d4e5f7
Create Date: 2026-05-13

Creates:
- user_client_assignments table (many-to-many user↔client for partner users)
- avatar_rentals table (farm avatar rental tracking)
- clients: max_avatars, plan_type, draft_approval_enabled columns
- avatars: is_farm_avatar, rent_price columns
- users: ix_users_role index

All changes are additive (CREATE TABLE, ADD COLUMN, CREATE INDEX).
No existing data is modified or deleted.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "a0b1c2d3e4f5"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- user_client_assignments table ---
    op.create_table(
        "user_client_assignments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_user_client_assignment", "user_client_assignments", ["user_id", "client_id"])
    op.create_index("ix_user_client_assignments_user_id", "user_client_assignments", ["user_id"])
    op.create_index("ix_user_client_assignments_client_id", "user_client_assignments", ["client_id"])

    # --- avatar_rentals table ---
    op.create_table(
        "avatar_rentals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("rented_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=True),
    )
    op.create_unique_constraint("uq_avatar_rental", "avatar_rentals", ["avatar_id", "client_id"])
    op.create_index("ix_avatar_rentals_avatar_id", "avatar_rentals", ["avatar_id"])
    op.create_index("ix_avatar_rentals_client_id", "avatar_rentals", ["client_id"])
    # Partial index for active rentals. Note: expires_at > NOW() cannot be used
    # in a partial index because NOW() is not IMMUTABLE. We index on is_active only;
    # expiry filtering happens at query time.
    op.create_index(
        "ix_avatar_rentals_active",
        "avatar_rentals",
        ["client_id"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # --- Client table: add RBAC/plan columns ---
    op.add_column("clients", sa.Column("max_avatars", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("clients", sa.Column("plan_type", sa.String(20), nullable=False, server_default="starter"))
    op.add_column("clients", sa.Column("draft_approval_enabled", sa.Boolean(), nullable=False, server_default="false"))

    # --- Avatar table: add farm columns ---
    op.add_column("avatars", sa.Column("is_farm_avatar", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("avatars", sa.Column("rent_price", sa.Numeric(10, 2), nullable=True))

    # --- Users table: add index on role ---
    op.create_index("ix_users_role", "users", ["role"])


def downgrade() -> None:
    # --- Users table: drop role index ---
    op.drop_index("ix_users_role", table_name="users")

    # --- Avatar table: drop farm columns ---
    op.drop_column("avatars", "rent_price")
    op.drop_column("avatars", "is_farm_avatar")

    # --- Client table: drop RBAC/plan columns ---
    op.drop_column("clients", "draft_approval_enabled")
    op.drop_column("clients", "plan_type")
    op.drop_column("clients", "max_avatars")

    # --- avatar_rentals table ---
    op.drop_index("ix_avatar_rentals_active", table_name="avatar_rentals")
    op.drop_index("ix_avatar_rentals_client_id", table_name="avatar_rentals")
    op.drop_index("ix_avatar_rentals_avatar_id", table_name="avatar_rentals")
    op.drop_constraint("uq_avatar_rental", "avatar_rentals", type_="unique")
    op.drop_table("avatar_rentals")

    # --- user_client_assignments table ---
    op.drop_index("ix_user_client_assignments_client_id", table_name="user_client_assignments")
    op.drop_index("ix_user_client_assignments_user_id", table_name="user_client_assignments")
    op.drop_constraint("uq_user_client_assignment", "user_client_assignments", type_="unique")
    op.drop_table("user_client_assignments")
