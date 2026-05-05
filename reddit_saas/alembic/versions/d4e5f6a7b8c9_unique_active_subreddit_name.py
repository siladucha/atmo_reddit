"""Enforce global uniqueness of active subreddit names

A subreddit can be actively monitored by only one client at a time. Reddit
names are case-insensitive, so the index lowercases the value.

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-05 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_client_subreddits_active_name "
        "ON client_subreddits (lower(subreddit_name)) "
        "WHERE is_active = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_client_subreddits_active_name")
