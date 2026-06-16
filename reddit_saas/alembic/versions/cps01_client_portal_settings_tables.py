"""Add client portal settings tables.

Creates:
- brand_guardrails JSONB column on clients table
- voice_feedback table (client voice/tone feedback entries)
- subreddit_requests table (request-based subreddit additions)

Revision ID: cps01
Revises: b2c3d4e5f6g7
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "cps01"
down_revision = "b2c3d4e5f6g7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add brand_guardrails JSONB column to clients table
    op.add_column("clients", sa.Column("brand_guardrails", JSONB, nullable=True))

    # 2. Create voice_feedback table
    op.create_table(
        "voice_feedback",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("feedback_text", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_voice_feedback_client_id", "voice_feedback", ["client_id"])

    # 3. Create subreddit_requests table
    op.create_table(
        "subreddit_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=False),
        sa.Column("subreddit_name", sa.String(100), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_subreddit_requests_client_status", "subreddit_requests", ["client_id", "status"])


def downgrade() -> None:
    # Drop subreddit_requests
    op.drop_index("ix_subreddit_requests_client_status", table_name="subreddit_requests")
    op.drop_table("subreddit_requests")

    # Drop voice_feedback
    op.drop_index("ix_voice_feedback_client_id", table_name="voice_feedback")
    op.drop_table("voice_feedback")

    # Remove brand_guardrails column
    op.drop_column("clients", "brand_guardrails")
