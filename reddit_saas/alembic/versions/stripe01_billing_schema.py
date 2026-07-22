"""Add Stripe billing schema.

Creates:
- 4 new columns on clients table (stripe_customer_id, stripe_subscription_id,
  stripe_price_id, subscription_canceled_at)
- billing_events table (webhook event audit log)
- client_invoices table (cached invoice data)
- billing_coupons table (coupon/discount tracking)
- Composite indexes for query performance

Additive only — no destructive changes.

Revision ID: stripe01
Revises: lro01
Create Date: 2026-07-22
"""

import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "stripe01"
down_revision = "lro01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add Stripe columns to clients table
    op.add_column(
        "clients",
        sa.Column("stripe_customer_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("stripe_price_id", sa.String(255), nullable=True),
    )
    op.add_column(
        "clients",
        sa.Column("subscription_canceled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        "uq_clients_stripe_customer_id", "clients", ["stripe_customer_id"]
    )
    op.create_unique_constraint(
        "uq_clients_stripe_subscription_id", "clients", ["stripe_subscription_id"]
    )

    # 2. Create billing_events table
    op.create_table(
        "billing_events",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column("stripe_event_id", sa.String(255), unique=True, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id"),
            nullable=True,
        ),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column(
            "processing_status",
            sa.String(20),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 3. Create client_invoices table
    op.create_table(
        "client_invoices",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id"),
            nullable=False,
        ),
        sa.Column("stripe_invoice_id", sa.String(255), unique=True, nullable=False),
        sa.Column("amount_cents", sa.Integer, nullable=False),
        sa.Column("currency", sa.String(3), server_default="usd", nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invoice_pdf_url", sa.Text, nullable=True),
        sa.Column("hosted_invoice_url", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 4. Create billing_coupons table
    op.create_table(
        "billing_coupons",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            default=uuid.uuid4,
        ),
        sa.Column("stripe_coupon_id", sa.String(255), unique=True, nullable=False),
        sa.Column("code", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("percent_off", sa.Integer, nullable=True),
        sa.Column("amount_off_cents", sa.Integer, nullable=True),
        sa.Column("duration_in_months", sa.Integer, nullable=False),
        sa.Column("max_redemptions", sa.Integer, nullable=True),
        sa.Column("times_redeemed", sa.Integer, server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean, server_default="true", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # 5. Create indexes for billing_events
    op.create_index(
        "ix_billing_events_client_created",
        "billing_events",
        ["client_id", "created_at"],
    )
    op.create_index(
        "ix_billing_events_type",
        "billing_events",
        ["event_type"],
    )

    # 6. Create index for client_invoices
    op.create_index(
        "ix_client_invoices_client_created",
        "client_invoices",
        ["client_id", "created_at"],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_client_invoices_client_created", table_name="client_invoices")
    op.drop_index("ix_billing_events_type", table_name="billing_events")
    op.drop_index("ix_billing_events_client_created", table_name="billing_events")

    # Drop tables
    op.drop_table("billing_coupons")
    op.drop_table("client_invoices")
    op.drop_table("billing_events")

    # Drop client columns and constraints
    op.drop_constraint("uq_clients_stripe_subscription_id", "clients", type_="unique")
    op.drop_constraint("uq_clients_stripe_customer_id", "clients", type_="unique")
    op.drop_column("clients", "subscription_canceled_at")
    op.drop_column("clients", "stripe_price_id")
    op.drop_column("clients", "stripe_subscription_id")
    op.drop_column("clients", "stripe_customer_id")
