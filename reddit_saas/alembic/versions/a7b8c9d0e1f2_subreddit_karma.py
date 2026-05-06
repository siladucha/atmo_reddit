"""Subreddit-specific karma tracking.

Creates the subreddit_karma table for per-avatar, per-subreddit karma snapshots.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-06 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subreddit_karma",
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
        sa.Column("comment_karma", sa.Integer(), server_default="0", nullable=False),
        sa.Column("post_karma", sa.Integer(), server_default="0", nullable=False),
        sa.Column("comment_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "previous_comment_karma", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "previous_post_karma", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "subreddit_type",
            sa.String(50),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "last_updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "avatar_id", "subreddit_name", name="uq_subreddit_karma_avatar_sub"
        ),
    )
    op.create_index("ix_subreddit_karma_avatar", "subreddit_karma", ["avatar_id"])


def downgrade() -> None:
    op.drop_index("ix_subreddit_karma_avatar", table_name="subreddit_karma")
    op.drop_table("subreddit_karma")
