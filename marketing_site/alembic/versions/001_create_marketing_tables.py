"""Create marketing tables

Revision ID: 001
Revises:
Create Date: 2026-05-14

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- waitlist_signups ---
    op.create_table(
        "waitlist_signups",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("company", sa.String(200), nullable=True),
        sa.Column("role", sa.String(100), nullable=True),
        sa.Column("accounts_count", sa.Integer(), nullable=True),
        sa.Column("price_tier", sa.String(50), nullable=True),
        sa.Column("feedback", sa.Text(), nullable=True),
        sa.Column("variant_shown", JSONB(), nullable=True),
        sa.Column("source_page", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_waitlist_signups_email", "waitlist_signups", ["email"])
    op.create_index("ix_waitlist_signups_created_at", "waitlist_signups", ["created_at"])

    # --- ab_test_assignments ---
    op.create_table(
        "ab_test_assignments",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("test_name", sa.String(100), nullable=False),
        sa.Column("variant_name", sa.String(100), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "converted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ab_test_assignments_visitor_id", "ab_test_assignments", ["visitor_id"]
    )
    op.create_index(
        "ix_ab_test_assignments_test_variant",
        "ab_test_assignments",
        ["test_name", "variant_name"],
    )

    # --- analytics_events ---
    op.create_table(
        "analytics_events",
        sa.Column("id", UUID(as_uuid=True), nullable=False),
        sa.Column("visitor_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("event_data", JSONB(), nullable=True),
        sa.Column("page_path", sa.String(500), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_events_visitor_id", "analytics_events", ["visitor_id"]
    )
    op.create_index(
        "ix_analytics_events_type_timestamp",
        "analytics_events",
        ["event_type", "timestamp"],
    )


def downgrade() -> None:
    op.drop_table("analytics_events")
    op.drop_table("ab_test_assignments")
    op.drop_table("waitlist_signups")
