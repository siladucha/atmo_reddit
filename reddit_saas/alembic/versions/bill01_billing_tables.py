"""billing tables and plan definitions

Creates:
- plan_definitions (source of truth for plan limits)
- client_subscriptions (Stripe mirror + counters + grace)
- webhook_events (Stripe webhook audit log)
- billing_period_history (archived period records)
- upsell_events (conversion funnel tracking)
- 3 new columns on clients (subscription_status, billing_period_start/end)
- Seeds plan_definitions from existing PLAN_LIMITS values
- Creates ClientSubscription rows for existing clients

Revision ID: bill01
Revises: tg01
Create Date: 2026-07-13
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB


revision = "bill01"
down_revision = "tg01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. plan_definitions
    op.create_table(
        "plan_definitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("plan_type", sa.String(20), unique=True, nullable=False),
        sa.Column("label", sa.String(50), nullable=False),
        sa.Column("price_usd", sa.Integer, nullable=False),
        sa.Column("stripe_price_id", sa.String(100), nullable=True),
        sa.Column("max_actions_per_month", sa.Integer, nullable=False),
        sa.Column("max_avatars", sa.Integer, nullable=False),
        sa.Column("max_subreddits", sa.Integer, nullable=False),
        sa.Column("max_professional_subreddits", sa.Integer, nullable=False),
        sa.Column("max_posts_per_month", sa.Integer, nullable=False),
        sa.Column("max_keywords", sa.Integer, nullable=False),
        sa.Column("geo_monitoring_enabled", sa.Boolean, nullable=False),
        sa.Column("geo_prompts_limit", sa.Integer, nullable=False),
        sa.Column("is_self_serve", sa.Boolean, server_default="true", nullable=False),
        sa.Column("tier_order", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. client_subscriptions
    op.create_table(
        "client_subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("stripe_customer_id", sa.String(100), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(100), nullable=True, unique=True),
        sa.Column("status", sa.String(20), server_default="trial", nullable=False),
        sa.Column("billing_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("billing_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("monthly_action_counter", sa.Integer, server_default="0", nullable=False),
        sa.Column("monthly_post_counter", sa.Integer, server_default="0", nullable=False),
        sa.Column("last_notified_threshold", sa.Integer, server_default="0", nullable=False),
        sa.Column("grace_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grace_period_days", sa.Integer, server_default="7", nullable=False),
        sa.Column("previous_grace_ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_downgrade_plan", sa.String(20), nullable=True),
        sa.Column("pending_downgrade_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean, server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_client_subscriptions_client_id", "client_subscriptions", ["client_id"])

    # 3. webhook_events
    op.create_table(
        "webhook_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("stripe_event_id", sa.String(100), unique=True, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), nullable=True),
        sa.Column("stripe_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_result", sa.String(50), nullable=False),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("raw_payload", JSONB, nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_events_event_type", "webhook_events", ["event_type"])
    op.create_index("ix_webhook_events_client_id", "webhook_events", ["client_id"])

    # 4. billing_period_history
    op.create_table(
        "billing_period_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plan_type", sa.String(20), nullable=False),
        sa.Column("actions_used", sa.Integer, nullable=False),
        sa.Column("posts_used", sa.Integer, nullable=False),
        sa.Column("actions_limit", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_billing_period_history_client_id", "billing_period_history", ["client_id"])

    # 5. upsell_events
    op.create_table(
        "upsell_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt_type", sa.String(30), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("clicked_plan", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_upsell_events_client_id", "upsell_events", ["client_id"])

    # 6. Add billing columns to clients
    op.add_column("clients", sa.Column("subscription_status", sa.String(20), nullable=True))
    op.add_column("clients", sa.Column("billing_period_start", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("billing_period_end", sa.DateTime(timezone=True), nullable=True))

    # Set subscription_status for existing clients based on plan_type
    op.execute("""
        UPDATE clients SET subscription_status = CASE
            WHEN plan_type = 'trial' THEN 'trial'
            ELSE 'active'
        END
    """)

    # Make subscription_status NOT NULL with default for new rows
    op.alter_column("clients", "subscription_status", nullable=False, server_default="trial")

    # 7. Seed plan_definitions with standard tiers
    op.execute("""
        INSERT INTO plan_definitions (plan_type, label, price_usd, max_actions_per_month, max_avatars, max_subreddits, max_professional_subreddits, max_posts_per_month, max_keywords, geo_monitoring_enabled, geo_prompts_limit, is_self_serve, tier_order)
        VALUES
            ('trial', 'Trial (14 days)', 0, 30, 1, 2, 1, 0, 10, false, 5, true, 0),
            ('seed', 'Seed', 149, 30, 1, 3, 1, 0, 20, false, 10, true, 1),
            ('starter', 'Starter', 399, 60, 3, 5, 2, 5, 30, true, 20, true, 2),
            ('growth', 'Growth', 799, 150, 7, 10, 5, 10, 50, true, 40, true, 3),
            ('scale', 'Scale', 1499, 400, 15, 999, 999, 30, 100, true, 60, true, 4),
            ('agency', 'Agency', 2000, 9999, 999, 999, 999, 999, 200, true, 100, false, 5)
        ON CONFLICT (plan_type) DO NOTHING
    """)

    # 8. Create ClientSubscription rows for existing clients
    op.execute("""
        INSERT INTO client_subscriptions (client_id, status, monthly_action_counter)
        SELECT id,
               CASE WHEN plan_type = 'trial' THEN 'trial' ELSE 'active' END,
               0
        FROM clients
        WHERE id NOT IN (SELECT client_id FROM client_subscriptions)
    """)


def downgrade() -> None:
    op.drop_column("clients", "billing_period_end")
    op.drop_column("clients", "billing_period_start")
    op.drop_column("clients", "subscription_status")
    op.drop_table("upsell_events")
    op.drop_table("billing_period_history")
    op.drop_table("webhook_events")
    op.drop_table("client_subscriptions")
    op.drop_table("plan_definitions")
