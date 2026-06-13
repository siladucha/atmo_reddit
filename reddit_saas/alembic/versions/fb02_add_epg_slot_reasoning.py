"""Add selection_reasoning JSONB to epg_slots for decision transparency.

Stores human-readable explanation of WHY each thread was selected:
- Selection reason (scored engage, keyword match, hobby rotation, etc.)
- Score at selection time
- Factors (subreddit affinity, feedback adjustment, karma history)
- Number of alternatives considered

This enables managers to understand EPG decisions at a glance.

Revision ID: fb02
Revises: fb01
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "fb02"
down_revision = "fb01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("epg_slots", sa.Column("selection_reasoning", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("epg_slots", "selection_reasoning")
