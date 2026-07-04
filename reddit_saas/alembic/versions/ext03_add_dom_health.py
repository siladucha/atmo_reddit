"""ext03: Add health monitoring fields to execution_nodes.

Extension v2 heartbeat sends dom_health, reddit_session_valid,
last_task_executed_at, and pending_approvals for operator awareness
and email fallback routing.
"""

revision = "ext03"
down_revision = "ext02"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.add_column(
        "execution_nodes",
        sa.Column("dom_health", sa.String(20), nullable=True, server_default="ok"),
    )
    op.add_column(
        "execution_nodes",
        sa.Column("dom_health_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "execution_nodes",
        sa.Column("last_task_executed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "execution_nodes",
        sa.Column("reddit_session_valid", sa.Boolean(), nullable=True, server_default="true"),
    )
    op.add_column(
        "execution_nodes",
        sa.Column("pending_approvals", sa.Integer(), nullable=True, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("execution_nodes", "pending_approvals")
    op.drop_column("execution_nodes", "reddit_session_valid")
    op.drop_column("execution_nodes", "last_task_executed_at")
    op.drop_column("execution_nodes", "dom_health_since")
    op.drop_column("execution_nodes", "dom_health")
