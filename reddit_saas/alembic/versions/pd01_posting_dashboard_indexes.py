"""Add posting_events indexes for unified posting dashboard.

Optimizes cursor-based pagination (posted_at DESC) and
avatar-filtered queries (avatar_id, posted_at DESC).

Changes:
- Drop existing ix_posting_events_posted_at (ASC) from ap01
- Recreate ix_posting_events_posted_at with DESC ordering
- Add composite ix_posting_events_avatar_posted (avatar_id, posted_at DESC)
- Verify: ix_epg_slots_avatar_date already covers EPG panel queries

Revision ID: pd01
Revises: perf01
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = "pd01"
down_revision = "perf01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop existing ASC index on posted_at (created in ap01)
    # and recreate with DESC for efficient cursor-based pagination
    op.drop_index("ix_posting_events_posted_at", table_name="posting_events")
    op.execute(
        "CREATE INDEX ix_posting_events_posted_at "
        "ON posting_events (posted_at DESC)"
    )

    # Composite index for avatar-filtered posting log queries:
    # WHERE avatar_id = ? AND posted_at < cursor ORDER BY posted_at DESC
    op.execute(
        "CREATE INDEX ix_posting_events_avatar_posted "
        "ON posting_events (avatar_id, posted_at DESC)"
    )

    # NOTE: ix_epg_slots_avatar_date on epg_slots(avatar_id, plan_date)
    # already covers EPG panel queries which filter by plan_date and
    # optionally by avatar. No additional EPG index needed.


def downgrade() -> None:
    op.drop_index("ix_posting_events_avatar_posted", table_name="posting_events")
    op.drop_index("ix_posting_events_posted_at", table_name="posting_events")
    # Restore the original ASC index from ap01
    op.create_index(
        "ix_posting_events_posted_at", "posting_events", ["posted_at"]
    )
