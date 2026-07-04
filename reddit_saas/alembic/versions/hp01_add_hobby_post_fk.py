"""Add FK constraint on comment_drafts.hobby_post_id -> hobby_subreddits.id

Revision ID: hp01
Revises: ext01
Create Date: 2026-06-28
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "hp01"
down_revision = "ext01"
branch_labels = None
depends_on = None


def upgrade():
    # First, NULL out any orphaned hobby_post_id values that reference non-existent records.
    # This prevents FK violation when adding the constraint.
    op.execute("""
        UPDATE comment_drafts
        SET hobby_post_id = NULL
        WHERE hobby_post_id IS NOT NULL
          AND hobby_post_id NOT IN (SELECT id FROM hobby_subreddits)
    """)

    # Add FK constraint with SET NULL on delete (if hobby post is removed, draft stays but loses link)
    op.create_foreign_key(
        "fk_comment_drafts_hobby_post_id",
        "comment_drafts",
        "hobby_subreddits",
        ["hobby_post_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_comment_drafts_hobby_post_id", "comment_drafts", type_="foreignkey")
