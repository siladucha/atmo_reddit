"""Add self-learning loop tables

Creates edit_records and correction_patterns tables for the self-learning loop
feature. Also adds learning_metadata JSONB column to comment_drafts for
generation provenance tracking.

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-06-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "s9t0u1v2w3x4"
down_revision: Union[str, None] = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- edit_records table ---
    op.create_table(
        "edit_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("comment_draft_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("comment_drafts.id"), nullable=False),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False),
        # Content
        sa.Column("ai_draft", sa.Text(), nullable=False),
        sa.Column("edited_draft", sa.Text(), nullable=True),
        sa.Column("edit_summary", sa.String(500), nullable=True),
        # Context
        sa.Column("subreddit", sa.String(255), nullable=False),
        sa.Column("engagement_mode", sa.String(100), nullable=True),
        sa.Column("post_title", sa.Text(), nullable=False),
        sa.Column("post_body", sa.String(500), nullable=True),
        sa.Column("final_status", sa.String(50), nullable=False),
        # Lifecycle
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # CHECK constraint
        sa.CheckConstraint(
            "final_status IN ('approved', 'approved_unchanged', 'rejected')",
            name="chk_final_status",
        ),
    )

    # Indexes for edit_records
    op.create_index(
        "ix_edit_records_avatar_client",
        "edit_records",
        ["avatar_id", "client_id"],
    )
    op.create_index(
        "ix_edit_records_avatar_client_created",
        "edit_records",
        ["avatar_id", "client_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_edit_records_subreddit",
        "edit_records",
        ["avatar_id", "client_id", "subreddit"],
    )
    op.create_index(
        "ix_edit_records_not_archived",
        "edit_records",
        ["avatar_id", "client_id"],
        postgresql_where=sa.text("is_archived = FALSE"),
    )

    # --- correction_patterns table ---
    op.create_table(
        "correction_patterns",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id"), nullable=False),
        # Pattern data
        sa.Column("pattern_type", sa.String(50), nullable=False),
        sa.Column("rule_text", sa.String(100), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        # Lifecycle
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # CHECK constraint
        sa.CheckConstraint(
            "pattern_type IN ("
            "'length_adjustment', 'tone_shift', 'vocabulary_change', "
            "'structure_change', 'content_removal', 'content_addition')",
            name="chk_pattern_type",
        ),
    )

    # Indexes for correction_patterns
    op.create_index(
        "ix_correction_patterns_avatar_client_rule",
        "correction_patterns",
        ["avatar_id", "client_id", "rule_text"],
        unique=True,
    )
    op.create_index(
        "ix_correction_patterns_frequency",
        "correction_patterns",
        ["avatar_id", "client_id", sa.text("frequency DESC")],
    )

    # --- learning_metadata column on comment_drafts ---
    op.add_column(
        "comment_drafts",
        sa.Column("learning_metadata", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    # Drop learning_metadata column
    op.drop_column("comment_drafts", "learning_metadata")

    # Drop correction_patterns indexes and table
    op.drop_index("ix_correction_patterns_frequency", table_name="correction_patterns")
    op.drop_index("ix_correction_patterns_avatar_client_rule", table_name="correction_patterns")
    op.drop_table("correction_patterns")

    # Drop edit_records indexes and table
    op.drop_index("ix_edit_records_not_archived", table_name="edit_records")
    op.drop_index("ix_edit_records_subreddit", table_name="edit_records")
    op.drop_index("ix_edit_records_avatar_client_created", table_name="edit_records")
    op.drop_index("ix_edit_records_avatar_client", table_name="edit_records")
    op.drop_table("edit_records")
