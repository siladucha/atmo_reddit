"""Add Discovery Engine tables.

Creates:
- discovery_sessions table (iterative Reddit ecosystem research sessions)
- discovery_entities table (named entities extracted from client brief)
- discovery_hypotheses table (testable propositions with confidence scoring)
- visibility_reports table (final structured assessment output)
- discovery_session_id FK column on strategy_documents (handoff linkage)

Revision ID: disc01
Revises: pd01
Create Date: 2026-06-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "disc01"
down_revision = "pd01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. discovery_sessions
    op.create_table(
        "discovery_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("operator_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("client_brief", sa.Text, nullable=False),
        sa.Column("prospect_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="in_progress"),
        sa.Column("current_iteration", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("abandon_reason", sa.String(500), nullable=True),
        sa.Column("session_metadata", JSONB, server_default="{}"),
        sa.Column("total_ai_cost_usd", sa.Numeric(10, 4), server_default="0"),
    )
    op.create_index("ix_discovery_sessions_client_id", "discovery_sessions", ["client_id"])
    op.create_index("ix_discovery_sessions_operator_user_id", "discovery_sessions", ["operator_user_id"])

    # 2. discovery_entities
    op.create_table(
        "discovery_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("source", sa.String(20), server_default="extracted"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_discovery_entities_session_id", "discovery_entities", ["session_id"])

    # 3. discovery_hypotheses
    op.create_table(
        "discovery_hypotheses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("iteration_number", sa.Integer, nullable=False),
        sa.Column("statement", sa.Text, nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("confidence_score", sa.Integer, server_default="50"),
        sa.Column("confidence_delta", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(20), server_default="proposed"),
        sa.Column("classification", sa.String(10), nullable=True),
        sa.Column("provenance", JSONB, server_default="{}"),
        sa.Column("reddit_signals", JSONB, server_default="{}"),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_hypothesis_session_iter_stmt",
        "discovery_hypotheses",
        ["session_id", "iteration_number", "statement"],
    )
    op.create_index("ix_hypothesis_session_status", "discovery_hypotheses", ["session_id", "status"])
    op.create_index("ix_hypothesis_session_iteration", "discovery_hypotheses", ["session_id", "iteration_number"])

    # 4. visibility_reports
    op.create_table(
        "visibility_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("session_id", UUID(as_uuid=True), sa.ForeignKey("discovery_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("operator_notes", sa.Text, nullable=True),
        sa.Column("report_version", sa.Integer, server_default="1"),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("generation_cost_usd", sa.Numeric(10, 4), server_default="0"),
    )
    op.create_index("ix_visibility_reports_session_id", "visibility_reports", ["session_id"])

    # 5. Add discovery_session_id FK to strategy_documents
    op.add_column(
        "strategy_documents",
        sa.Column(
            "discovery_session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("discovery_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Reverse order: drop FK column, then tables
    op.drop_column("strategy_documents", "discovery_session_id")

    op.drop_index("ix_visibility_reports_session_id", table_name="visibility_reports")
    op.drop_table("visibility_reports")

    op.drop_index("ix_hypothesis_session_iteration", table_name="discovery_hypotheses")
    op.drop_index("ix_hypothesis_session_status", table_name="discovery_hypotheses")
    op.drop_constraint("uq_hypothesis_session_iter_stmt", "discovery_hypotheses", type_="unique")
    op.drop_table("discovery_hypotheses")

    op.drop_index("ix_discovery_entities_session_id", table_name="discovery_entities")
    op.drop_table("discovery_entities")

    op.drop_index("ix_discovery_sessions_operator_user_id", table_name="discovery_sessions")
    op.drop_index("ix_discovery_sessions_client_id", table_name="discovery_sessions")
    op.drop_table("discovery_sessions")
