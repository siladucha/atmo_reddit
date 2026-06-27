"""Add avatar_subreddit_bans table for per-subreddit ban tracking.

Revision ID: asb01
Revises: merge01_merge_dor01_cstrat01
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = "asb01"
down_revision = "merge01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "avatar_subreddit_bans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("avatars.id", ondelete="CASCADE"), nullable=False),
        sa.Column("subreddit", sa.String(255), nullable=False),
        # Detection
        sa.Column("banned_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("ban_source", sa.String(30), nullable=False),
        sa.Column("detection_evidence", postgresql.JSONB, server_default="{}"),
        sa.Column("consecutive_deletions", sa.Integer, server_default="0"),
        # Unban
        sa.Column("unbanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unban_source", sa.String(30), nullable=True),
        # State
        sa.Column("is_active", sa.Boolean, server_default="true"),
        # Probe
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_probe_result", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        # Constraints
        sa.UniqueConstraint("avatar_id", "subreddit", name="uq_avatar_subreddit_ban_active"),
    )
    op.create_index("ix_asb_avatar_active", "avatar_subreddit_bans", ["avatar_id", "is_active"])
    op.create_index("ix_asb_subreddit", "avatar_subreddit_bans", ["subreddit"])


def downgrade() -> None:
    op.drop_index("ix_asb_subreddit", table_name="avatar_subreddit_bans")
    op.drop_index("ix_asb_avatar_active", table_name="avatar_subreddit_bans")
    op.drop_table("avatar_subreddit_bans")
