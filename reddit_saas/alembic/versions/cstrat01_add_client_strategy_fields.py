"""add_client_strategy_fields

Adds strategy_context JSONB and related fields to clients table.
Adds priority + engagement_approach to client_subreddit_assignments.

Revision ID: cstrat01
Revises: exec01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers
revision = "cstrat01"
down_revision = "exec01"
branch_labels = None
depends_on = None


def upgrade():
    # Client strategy fields
    op.add_column("clients", sa.Column("strategy_context", JSONB, nullable=True))
    op.add_column("clients", sa.Column("strategy_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("clients", sa.Column("strategy_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clients", sa.Column("strategy_source_session_id", UUID(as_uuid=True), nullable=True))
    op.add_column("clients", sa.Column("strategy_history", JSONB, nullable=True))

    # Subreddit assignment priority fields
    op.add_column("client_subreddit_assignments", sa.Column("priority", sa.Integer(), nullable=True))
    op.add_column("client_subreddit_assignments", sa.Column("engagement_approach", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("client_subreddit_assignments", "engagement_approach")
    op.drop_column("client_subreddit_assignments", "priority")
    op.drop_column("clients", "strategy_history")
    op.drop_column("clients", "strategy_source_session_id")
    op.drop_column("clients", "strategy_generated_at")
    op.drop_column("clients", "strategy_version")
    op.drop_column("clients", "strategy_context")
