"""Add avatar_drafts table for BYOA async provisioning.

Revision ID: byoa01_add_avatar_drafts
Revises: 24d4adc2305b
Create Date: 2026-06-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "byoa01_add_avatar_drafts"
down_revision = "24d4adc2305b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reddit_username", sa.String(20), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_fetch"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("reddit_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("ai_analysis", postgresql.JSONB(), nullable=True),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("fetch_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetch_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analysis_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("analysis_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["avatar_id"], ["avatars.id"]),
    )

    # Index for fast client lookup
    op.create_index("ix_avatar_drafts_client_id", "avatar_drafts", ["client_id"])

    # Partial unique index: only one non-terminal draft per (reddit_username, client_id)
    op.execute(
        """
        CREATE UNIQUE INDEX ix_avatar_draft_active_username_client
        ON avatar_drafts (reddit_username, client_id)
        WHERE status IN ('pending_fetch', 'analyzing', 'ready_for_review')
        """
    )

    # Partial index for fast lookup of active drafts per client (trial limit check)
    op.execute(
        """
        CREATE INDEX ix_avatar_draft_client_active
        ON avatar_drafts (client_id, status)
        WHERE status IN ('pending_fetch', 'analyzing', 'ready_for_review')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_avatar_draft_client_active", table_name="avatar_drafts")
    op.drop_index("ix_avatar_draft_active_username_client", table_name="avatar_drafts")
    op.drop_index("ix_avatar_drafts_client_id", table_name="avatar_drafts")
    op.drop_table("avatar_drafts")
