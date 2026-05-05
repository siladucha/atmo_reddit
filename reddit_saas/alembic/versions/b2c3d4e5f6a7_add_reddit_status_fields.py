"""Add Reddit status cache fields to avatars table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-04 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "avatars",
        sa.Column("reddit_status", sa.String(length=20), server_default="unknown", nullable=False),
    )
    op.add_column(
        "avatars",
        sa.Column("reddit_karma_comment", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "avatars",
        sa.Column("reddit_karma_post", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "avatars",
        sa.Column("reddit_account_created", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "avatars",
        sa.Column("reddit_icon_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "avatars",
        sa.Column("reddit_status_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("avatars", "reddit_status_checked_at")
    op.drop_column("avatars", "reddit_icon_url")
    op.drop_column("avatars", "reddit_account_created")
    op.drop_column("avatars", "reddit_karma_post")
    op.drop_column("avatars", "reddit_karma_comment")
    op.drop_column("avatars", "reddit_status")
