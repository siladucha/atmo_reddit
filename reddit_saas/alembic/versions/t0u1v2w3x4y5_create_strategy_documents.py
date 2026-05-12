"""Create strategy_documents table

Stores versioned strategy documents per avatar. Each generation creates a new
version with goals, subreddit priorities, tone guidelines, cadence rules,
hook inventory, and LLM cost metadata.

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-05-10 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "t0u1v2w3x4y5"
down_revision: Union[str, None] = "s9t0u1v2w3x4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "strategy_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("avatar_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("avatars.id"), nullable=False),
        # Content sections
        sa.Column("goals", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("subreddit_priorities", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("tone_guidelines", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("cadence_rules", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("hook_inventory", postgresql.JSONB, nullable=False, server_default="{}"),
        sa.Column("forecast", postgresql.JSONB, nullable=True),
        # Full markdown
        sa.Column("document_md", sa.Text, nullable=False, server_default=""),
        # Versioning
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("is_current", sa.Boolean, nullable=False, server_default="true"),
        # Manual edits
        sa.Column("edited_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        # LLM metadata
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("cost_usd", sa.Float, nullable=True),
        sa.Column("generation_duration_ms", sa.Integer, nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Indexes
    op.create_index(
        "ix_strategy_docs_avatar_current",
        "strategy_documents",
        ["avatar_id", "is_current"],
    )
    op.create_index(
        "ix_strategy_docs_avatar_version",
        "strategy_documents",
        ["avatar_id", "version"],
    )


def downgrade() -> None:
    op.drop_index("ix_strategy_docs_avatar_version", table_name="strategy_documents")
    op.drop_index("ix_strategy_docs_avatar_current", table_name="strategy_documents")
    op.drop_table("strategy_documents")
