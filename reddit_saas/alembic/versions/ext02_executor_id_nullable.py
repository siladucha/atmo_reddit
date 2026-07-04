"""ext02: Make execution_nodes.executor_id nullable.

Zero-input activation doesn't always have an executor User mapped.
The extension activates by Reddit username — executor_id is resolved
later if possible, or left NULL.
"""

revision = "ext02"
down_revision = "ext01"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.alter_column(
        "execution_nodes",
        "executor_id",
        existing_type=sa.UUID(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "execution_nodes",
        "executor_id",
        existing_type=sa.UUID(),
        nullable=False,
    )
