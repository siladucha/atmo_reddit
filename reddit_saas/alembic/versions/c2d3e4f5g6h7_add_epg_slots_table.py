"""Add epg_slots table for persistent daily publishing plans.

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-05-25

EPG slots persist the daily plan for each avatar:
- What threads to comment on (hobby + professional)
- Scheduled posting times
- Status tracking (planned → generated → approved → posted)
- Link to generated CommentDraft
"""

revision = "c2d3e4f5g6h7"
down_revision = "b1c2d3e4f5g6"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


def upgrade() -> None:
    op.create_table(
        "epg_slots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("plan_date", sa.Date, nullable=False),
        sa.Column("slot_type", sa.String(50), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, server_default="planned"),
        # Target
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("reddit_threads.id"), nullable=True),
        sa.Column("hobby_post_id", UUID(as_uuid=True), nullable=True),
        sa.Column("subreddit", sa.String(255), nullable=True),
        sa.Column("thread_title", sa.Text, nullable=True),
        sa.Column("thread_ups", sa.Integer, nullable=True),
        # Result
        sa.Column("draft_id", UUID(as_uuid=True), sa.ForeignKey("comment_drafts.id"), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.String(255), nullable=True),
    )

    op.create_index("ix_epg_slots_avatar_date", "epg_slots", ["avatar_id", "plan_date"])
    op.create_index("ix_epg_slots_avatar_date_status", "epg_slots", ["avatar_id", "plan_date", "status"])
    op.create_index(
        "ix_epg_slots_status_planned",
        "epg_slots",
        ["status"],
        postgresql_where=sa.text("status = 'planned'"),
    )
    op.create_index("ix_epg_slots_draft_id", "epg_slots", ["draft_id"])


def downgrade() -> None:
    op.drop_index("ix_epg_slots_draft_id", table_name="epg_slots")
    op.drop_index("ix_epg_slots_status_planned", table_name="epg_slots")
    op.drop_index("ix_epg_slots_avatar_date_status", table_name="epg_slots")
    op.drop_index("ix_epg_slots_avatar_date", table_name="epg_slots")
    op.drop_table("epg_slots")
