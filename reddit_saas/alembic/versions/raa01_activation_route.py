"""Add activation_route JSONB, activation_zone, zone_entered_at to avatars.

Revision ID: raa01
Revises: frl01
Create Date: 2026-07-02

Risk-Aware Avatar Activation — zone routing (safe → bridge → target).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "raa01"
down_revision = "frl01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "avatars",
        sa.Column("activation_route", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "avatars",
        sa.Column(
            "activation_zone",
            sa.String(20),
            nullable=True,
            comment="Denormalized zone for fast queries: safe/bridge/target/none",
        ),
    )
    op.add_column(
        "avatars",
        sa.Column("zone_entered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_avatars_activation_zone", "avatars", ["activation_zone"])


def downgrade() -> None:
    op.drop_index("ix_avatars_activation_zone", table_name="avatars")
    op.drop_column("avatars", "zone_entered_at")
    op.drop_column("avatars", "activation_zone")
    op.drop_column("avatars", "activation_route")
