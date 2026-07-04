"""Add permission_matrix to clients + create action_requests table.

Revision ID: perm01
Revises: ext04, merge_ev01_incub01
Create Date: 2026-07-05
"""
import json
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "perm01"
down_revision = ("ext04", "merge_ev01_incub01")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add permission_matrix JSONB column to clients table
    op.add_column(
        "clients",
        sa.Column(
            "permission_matrix",
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )

    # 2. Create action_requests table
    op.create_table(
        "action_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column(
            "client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False
        ),
        sa.Column(
            "user_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("action_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("rejection_reason", sa.Text, nullable=True),
    )

    # 3. Create indexes for efficient querying
    op.create_index(
        "ix_action_requests_client_status",
        "action_requests",
        ["client_id", "status"],
    )
    op.create_index(
        "ix_action_requests_client_action_status",
        "action_requests",
        ["client_id", "action_type", "status"],
    )

    # 4. Backfill existing clients with DEFAULT_PERMISSION_MAP
    from app.services.permission_map import DEFAULT_PERMISSION_MAP

    op.execute(
        text(
            f"UPDATE clients SET permission_matrix = '{json.dumps(DEFAULT_PERMISSION_MAP)}'::jsonb"
        )
    )


def downgrade() -> None:
    op.drop_table("action_requests")
    op.drop_column("clients", "permission_matrix")
