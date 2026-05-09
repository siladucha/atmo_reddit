"""Add avatar_subreddit_presence table.

Creates the avatar_subreddit_presence table for per-avatar, per-subreddit
presence tracking (comment count, karma, last activity). Also adds
presence_last_scanned_at and presence_scan_status columns to avatars table.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-05-20 14:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, None] = "q7r8s9t0u1v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create avatar_subreddit_presence table
    op.create_table(
        "avatar_subreddit_presence",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "avatar_id",
            UUID(as_uuid=True),
            sa.ForeignKey("avatars.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subreddit_name", sa.String(255), nullable=False),
        sa.Column("comment_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_karma", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "last_activity_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "avatar_id", "subreddit_name", name="uq_avatar_subreddit_presence"
        ),
    )
    op.create_index(
        "ix_avatar_subreddit_presence_avatar_id",
        "avatar_subreddit_presence",
        ["avatar_id"],
    )

    # 2. Add presence columns to avatars table (idempotent)
    conn = op.get_bind()
    for col_name, col_def in [
        (
            "presence_last_scanned_at",
            sa.Column(
                "presence_last_scanned_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        ),
        (
            "presence_scan_status",
            sa.Column(
                "presence_scan_status",
                sa.String(20),
                nullable=True,
            ),
        ),
    ]:
        result = conn.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='avatars' AND column_name=:col"
            ),
            {"col": col_name},
        )
        if not result.fetchone():
            op.add_column("avatars", col_def)


def downgrade() -> None:
    # Drop presence columns from avatars
    op.drop_column("avatars", "presence_scan_status")
    op.drop_column("avatars", "presence_last_scanned_at")

    # Drop avatar_subreddit_presence table
    op.drop_index(
        "ix_avatar_subreddit_presence_avatar_id",
        table_name="avatar_subreddit_presence",
    )
    op.drop_table("avatar_subreddit_presence")
