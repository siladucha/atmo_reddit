"""frl01: Forecast & Reporting Layer tables

Creates:
- client_intelligence_reports (5-layer JSONB structured weekly reports)
- forecast_accuracy_log (predicted vs actual tracking)
- observed_snapshots (point-in-time observed metrics)

Revision ID: frl01
Revises: ext03, merge_ev01_incub01
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "frl01"
down_revision = "ext03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. client_intelligence_reports — 5-layer structured weekly reports
    op.create_table(
        "client_intelligence_reports",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_period", sa.String(10), nullable=False),
        sa.Column("report_version", sa.Integer(), nullable=False, server_default="1"),
        # Structured layers (each independently queryable)
        sa.Column("observed_json", JSONB, nullable=False),
        sa.Column("planned_json", JSONB, nullable=False),
        sa.Column("forecasted_json", JSONB, nullable=False),
        sa.Column("risks_json", JSONB, nullable=False),
        sa.Column("business_impact_json", JSONB, nullable=False),
        # Metadata
        sa.Column("model_version", sa.String(20), nullable=False),
        sa.Column("data_freshness_json", JSONB, nullable=False),
        sa.Column("generation_cost_usd", sa.Numeric(8, 4), server_default="0"),
        # Lifecycle
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        # Unique constraint
        sa.UniqueConstraint("client_id", "report_period", "report_version", name="uq_report_client_period_version"),
    )
    op.create_index("ix_cir_client_period", "client_intelligence_reports", ["client_id", "report_period"])

    # 2. forecast_accuracy_log — predicted vs actual tracking
    op.create_table(
        "forecast_accuracy_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("report_id", UUID(as_uuid=True), sa.ForeignKey("client_intelligence_reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_id", sa.String(100), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("scenario", sa.String(20), nullable=False),
        sa.Column("predicted_value", sa.Numeric(8, 2), nullable=False),
        sa.Column("actual_value", sa.Numeric(8, 2), nullable=True),
        sa.Column("error_pp", sa.Numeric(8, 2), nullable=True),
        sa.Column("within_bounds", sa.Boolean(), nullable=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=True),
        # Unique constraint
        sa.UniqueConstraint("report_id", "metric_id", "target_date", "scenario", name="uq_accuracy_report_metric_target"),
    )
    op.create_index("ix_fal_client_metric", "forecast_accuracy_log", ["client_id", "metric_id"])

    # 3. observed_snapshots — point-in-time observed metrics
    op.create_table(
        "observed_snapshots",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("metrics_json", JSONB, nullable=False),
        sa.Column("data_gaps", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source_availability", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_obs_client_collected", "observed_snapshots", ["client_id", "collected_at"])


def downgrade() -> None:
    op.drop_table("observed_snapshots")
    op.drop_table("forecast_accuracy_log")
    op.drop_table("client_intelligence_reports")
