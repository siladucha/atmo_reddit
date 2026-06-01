"""Add automated posting tables and avatar extensions.

Creates:
- reddit_apps table (OAuth/script app registry)
- posting_events table (audit trail)
- New columns on avatars (proxy, posting_mode, credentials, state)

Revision ID: ap01
Revises: 6da36db9c7c4
Create Date: 2026-05-31
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "ap01"
down_revision = "6da36db9c7c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- reddit_apps table ---
    op.create_table(
        "reddit_apps",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=True),
        sa.Column("client_id_reddit", sa.String(255), unique=True, nullable=False),
        sa.Column("client_secret_encrypted", sa.Text(), nullable=False),
        sa.Column("app_name", sa.String(255), nullable=False),
        sa.Column("app_type", sa.String(20), server_default="script", nullable=False),
        sa.Column("registered_under_username", sa.String(255), nullable=False),
        sa.Column("redirect_uri", sa.String(500), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("health_status", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- posting_events table ---
    op.create_table(
        "posting_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("draft_id", UUID(as_uuid=True), sa.ForeignKey("comment_drafts.id"), nullable=True),
        sa.Column("epg_slot_id", UUID(as_uuid=True), sa.ForeignKey("epg_slots.id"), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("ip_used", sa.String(45), nullable=True),
        sa.Column("proxy_url_hash", sa.String(64), nullable=True),
        sa.Column("user_agent_used", sa.String(500), nullable=True),
        sa.Column("reddit_comment_id", sa.String(20), nullable=True),
        sa.Column("reddit_comment_url", sa.Text(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body_excerpt", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("outcome", sa.String(20), nullable=False),
    )
    op.create_index("ix_posting_events_avatar_id", "posting_events", ["avatar_id"])
    op.create_index("ix_posting_events_posted_at", "posting_events", ["posted_at"])
    op.create_index("ix_posting_events_outcome", "posting_events", ["outcome"])

    # --- Avatar extensions ---
    op.add_column("avatars", sa.Column("proxy_url_encrypted", sa.Text(), nullable=True))
    op.add_column("avatars", sa.Column("user_agent_string", sa.String(500), nullable=True))
    op.add_column("avatars", sa.Column("declared_timezone", sa.String(50), server_default="America/New_York", nullable=False))
    op.add_column("avatars", sa.Column("posting_mode", sa.String(20), server_default="disabled", nullable=False))
    op.add_column("avatars", sa.Column("reddit_app_id", UUID(as_uuid=True), nullable=True))
    op.add_column("avatars", sa.Column("refresh_token_encrypted", sa.Text(), nullable=True))
    op.add_column("avatars", sa.Column("reddit_password_encrypted", sa.Text(), nullable=True))
    op.add_column("avatars", sa.Column("last_posted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("avatars", sa.Column("last_posted_ip", sa.String(45), nullable=True))
    op.add_column("avatars", sa.Column("consecutive_post_failures", sa.Integer(), server_default="0", nullable=False))

    op.create_foreign_key(
        "fk_avatars_reddit_app_id",
        "avatars",
        "reddit_apps",
        ["reddit_app_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_avatars_reddit_app_id", "avatars", type_="foreignkey")
    op.drop_column("avatars", "consecutive_post_failures")
    op.drop_column("avatars", "last_posted_ip")
    op.drop_column("avatars", "last_posted_at")
    op.drop_column("avatars", "reddit_password_encrypted")
    op.drop_column("avatars", "refresh_token_encrypted")
    op.drop_column("avatars", "reddit_app_id")
    op.drop_column("avatars", "posting_mode")
    op.drop_column("avatars", "declared_timezone")
    op.drop_column("avatars", "user_agent_string")
    op.drop_column("avatars", "proxy_url_encrypted")

    op.drop_index("ix_posting_events_outcome", table_name="posting_events")
    op.drop_index("ix_posting_events_posted_at", table_name="posting_events")
    op.drop_index("ix_posting_events_avatar_id", table_name="posting_events")
    op.drop_table("posting_events")
    op.drop_table("reddit_apps")
