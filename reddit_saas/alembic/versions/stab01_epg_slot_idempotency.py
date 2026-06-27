"""EPG slot idempotency: unique partial indexes on (avatar_id, plan_date, thread_id/hobby_post_id)

Prevents duplicate EPG slots for the same avatar+date+target.
This is the DB-level enforcement of the application-level dedup guard.

Revision ID: stab01
Revises: (head)
"""
from alembic import op

revision = "stab01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Unique constraint: one slot per avatar per day per professional thread
    op.create_index(
        "uq_epg_slots_avatar_date_thread",
        "epg_slots",
        ["avatar_id", "plan_date", "thread_id"],
        unique=True,
        postgresql_where="thread_id IS NOT NULL",
    )
    # Unique constraint: one slot per avatar per day per hobby post
    op.create_index(
        "uq_epg_slots_avatar_date_hobby",
        "epg_slots",
        ["avatar_id", "plan_date", "hobby_post_id"],
        unique=True,
        postgresql_where="hobby_post_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_epg_slots_avatar_date_hobby", table_name="epg_slots")
    op.drop_index("uq_epg_slots_avatar_date_thread", table_name="epg_slots")
