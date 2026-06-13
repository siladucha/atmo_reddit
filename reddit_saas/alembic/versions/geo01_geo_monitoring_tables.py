"""Add GEO/AEO Prompt Monitoring tables.

Creates:
- geo_prompts table (buyer-intent prompts per client)
- geo_competitors table (competitor entities per client)
- geo_execution_batches table (batch tracking)
- geo_query_results table (individual query results)
- geo_frequency_metrics table (aggregated metrics)
- Adds geo_monitoring_enabled and geo_execution_frequency to clients table

Revision ID: geo01
Revises: fb02
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "geo01"
down_revision = "fb02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. geo_prompts
    op.create_table(
        "geo_prompts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_prompts_client_id", "geo_prompts", ["client_id"])
    op.create_index("ix_geo_prompts_client_active", "geo_prompts", ["client_id", "is_active"])

    # 2. geo_competitors
    op.create_table(
        "geo_competitors",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("competitor_name", sa.String(255), nullable=False),
        sa.Column("competitor_domain", sa.String(255), nullable=True),
        sa.Column("aliases", JSONB, server_default="[]", nullable=True),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_competitors_client_id", "geo_competitors", ["client_id"])
    op.create_index("ix_geo_competitors_client_active", "geo_competitors", ["client_id", "is_active"])

    # 3. geo_execution_batches
    op.create_table(
        "geo_execution_batches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("triggered_by", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="running", nullable=False),
        sa.Column("is_baseline", sa.Boolean, server_default="false", nullable=False),
        sa.Column("total_queries", sa.Integer, server_default="0"),
        sa.Column("successful_queries", sa.Integer, server_default="0"),
        sa.Column("failed_queries", sa.Integer, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_batches_client_id", "geo_execution_batches", ["client_id"])
    op.create_index("ix_geo_batches_client_started", "geo_execution_batches", ["client_id", "started_at"])

    # 4. geo_query_results
    op.create_table(
        "geo_query_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("prompt_id", UUID(as_uuid=True), sa.ForeignKey("geo_prompts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_batch_id", UUID(as_uuid=True), sa.ForeignKey("geo_execution_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("run_number", sa.Integer, nullable=False),
        sa.Column("response_text", sa.Text, nullable=True),
        sa.Column("brand_mentioned", sa.Boolean, server_default="false", nullable=False),
        sa.Column("competitors_mentioned", JSONB, nullable=True),
        sa.Column("reddit_urls_found", JSONB, nullable=True),
        sa.Column("citation_sources", JSONB, nullable=True),
        sa.Column("response_tokens", sa.Integer, server_default="0"),
        sa.Column("latency_ms", sa.Integer, server_default="0"),
        sa.Column("status", sa.String(20), server_default="success", nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_results_batch_id", "geo_query_results", ["execution_batch_id"])
    op.create_index("ix_geo_results_prompt_id", "geo_query_results", ["prompt_id"])
    op.create_index("ix_geo_results_client_executed", "geo_query_results", ["client_id", "executed_at"])

    # 5. geo_frequency_metrics
    op.create_table(
        "geo_frequency_metrics",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("execution_batch_id", UUID(as_uuid=True), sa.ForeignKey("geo_execution_batches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_id", UUID(as_uuid=True), sa.ForeignKey("geo_prompts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("total_runs", sa.Integer, server_default="0"),
        sa.Column("brand_appearances", sa.Integer, server_default="0"),
        sa.Column("brand_appearance_rate", sa.Numeric(5, 2), server_default="0"),
        sa.Column("competitor_appearances", JSONB, nullable=True),
        sa.Column("reddit_citation_count", sa.Integer, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_geo_metrics_batch_id", "geo_frequency_metrics", ["execution_batch_id"])
    op.create_index("ix_geo_metrics_prompt_batch", "geo_frequency_metrics", ["prompt_id", "execution_batch_id"])

    # 6. Add GEO fields to clients table
    op.add_column("clients", sa.Column("geo_monitoring_enabled", sa.Boolean, server_default="false", nullable=False))
    op.add_column("clients", sa.Column("geo_execution_frequency", sa.String(20), server_default="twice_weekly", nullable=False))


def downgrade() -> None:
    # Remove client columns
    op.drop_column("clients", "geo_execution_frequency")
    op.drop_column("clients", "geo_monitoring_enabled")

    # Drop tables in reverse order
    op.drop_index("ix_geo_metrics_prompt_batch", table_name="geo_frequency_metrics")
    op.drop_index("ix_geo_metrics_batch_id", table_name="geo_frequency_metrics")
    op.drop_table("geo_frequency_metrics")

    op.drop_index("ix_geo_results_client_executed", table_name="geo_query_results")
    op.drop_index("ix_geo_results_prompt_id", table_name="geo_query_results")
    op.drop_index("ix_geo_results_batch_id", table_name="geo_query_results")
    op.drop_table("geo_query_results")

    op.drop_index("ix_geo_batches_client_started", table_name="geo_execution_batches")
    op.drop_index("ix_geo_batches_client_id", table_name="geo_execution_batches")
    op.drop_table("geo_execution_batches")

    op.drop_index("ix_geo_competitors_client_active", table_name="geo_competitors")
    op.drop_index("ix_geo_competitors_client_id", table_name="geo_competitors")
    op.drop_table("geo_competitors")

    op.drop_index("ix_geo_prompts_client_active", table_name="geo_prompts")
    op.drop_index("ix_geo_prompts_client_id", table_name="geo_prompts")
    op.drop_table("geo_prompts")
