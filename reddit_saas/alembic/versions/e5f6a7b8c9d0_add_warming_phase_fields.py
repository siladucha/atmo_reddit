"""Add warming phase fields, comment deletion tracking, and brand_domain.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-05-05 12:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Avatar phase fields
    op.add_column(
        "avatars",
        sa.Column("warming_phase", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "avatars",
        sa.Column(
            "phase_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "avatars",
        sa.Column("last_phase_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Comment tracking fields
    op.add_column(
        "comment_drafts",
        sa.Column("is_deleted", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "comment_drafts",
        sa.Column("reddit_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "comment_drafts",
        sa.Column("deleted_detected_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Client brand domain
    op.add_column(
        "clients",
        sa.Column("brand_domain", sa.String(length=255), nullable=True),
    )

    # Conditional phase assignment for existing avatars:
    # Phase 2 for accounts with reddit_account_created >= 60 days ago.
    # Phase 1 (default) covers everything else, including NULL reddit_account_created.
    op.execute(
        """
        UPDATE avatars
        SET warming_phase = 2,
            phase_changed_at = NOW()
        WHERE reddit_account_created IS NOT NULL
          AND reddit_account_created < NOW() - INTERVAL '60 days'
        """
    )


def downgrade() -> None:
    op.drop_column("clients", "brand_domain")
    op.drop_column("comment_drafts", "deleted_detected_at")
    op.drop_column("comment_drafts", "reddit_score")
    op.drop_column("comment_drafts", "is_deleted")
    op.drop_column("avatars", "last_phase_evaluated_at")
    op.drop_column("avatars", "phase_changed_at")
    op.drop_column("avatars", "warming_phase")
