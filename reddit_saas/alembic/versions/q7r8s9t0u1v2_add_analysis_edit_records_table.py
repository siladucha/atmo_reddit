"""Add analysis_edit_records table

Stores human corrections to LLM-generated behavioral profiles.
Used by the learning loop to inject few-shot examples into future analyses.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-05-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "q7r8s9t0u1v2"
down_revision = "p6q7r8s9t0u1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_edit_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "avatar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("avatars.id"),
            nullable=False,
        ),
        sa.Column("llm_output", postgresql.JSONB(), nullable=False),
        sa.Column("human_edited", postgresql.JSONB(), nullable=False),
        sa.Column("diff_summary", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    # Composite index for "most recent N edits per avatar" query
    op.create_index(
        "ix_analysis_edit_records_avatar_created",
        "analysis_edit_records",
        ["avatar_id", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_edit_records_avatar_created",
        table_name="analysis_edit_records",
    )
    op.drop_table("analysis_edit_records")
