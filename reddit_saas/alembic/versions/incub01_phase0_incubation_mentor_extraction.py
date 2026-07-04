"""Phase 0 Incubation + Mentor Extraction

- Migrate existing Phase 0 avatars (Mentors) to pool='mentor', warming_phase=1
- Add system settings for incubation configuration
- Add phase0_freeze_timeout_days setting

Revision ID: incub01
Revises: ed0197e3d7e7
Create Date: 2026-06-29
"""

from alembic import op
import sqlalchemy as sa

revision = "incub01"
down_revision = "ed0197e3d7e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: Move existing Phase 0 avatars (all are Mentors) to pool='mentor', phase=1
    op.execute(
        "UPDATE avatars SET pool = 'mentor', warming_phase = 1 "
        "WHERE warming_phase = 0"
    )

    # Step 2: Add system settings for Incubation
    # Note: system_settings.id is UUID PK without server_default, must use gen_random_uuid()
    op.execute(
        "INSERT INTO system_settings (id, key, value, is_secret, \"group\") VALUES "
        "(gen_random_uuid(), 'incubation_safe_subreddits', "
        "'[\"AskReddit\",\"CasualConversation\",\"NoStupidQuestions\",\"TooAfraidToAsk\",\"Showerthoughts\",\"LifeProTips\"]', false, 'incubation') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (id, key, value, is_secret, \"group\") VALUES "
        "(gen_random_uuid(), 'incubation_phase_enabled', 'false', false, 'incubation') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (id, key, value, is_secret, \"group\") VALUES "
        "(gen_random_uuid(), 'phase_gate_p0_min_age_days', '7', false, 'incubation') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (id, key, value, is_secret, \"group\") VALUES "
        "(gen_random_uuid(), 'phase_gate_p0_min_karma', '10', false, 'incubation') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (id, key, value, is_secret, \"group\") VALUES "
        "(gen_random_uuid(), 'phase_gate_p0_min_posted_comments', '3', false, 'incubation') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (id, key, value, is_secret, \"group\") VALUES "
        "(gen_random_uuid(), 'phase_gate_p0_max_deleted_comments', '0', false, 'incubation') "
        "ON CONFLICT (key) DO NOTHING"
    )
    op.execute(
        "INSERT INTO system_settings (id, key, value, is_secret, \"group\") VALUES "
        "(gen_random_uuid(), 'phase0_freeze_timeout_days', '30', false, 'incubation') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    # Revert Mentors back to phase 0
    op.execute(
        "UPDATE avatars SET warming_phase = 0 "
        "WHERE pool = 'mentor'"
    )

    # Remove settings
    op.execute(
        "DELETE FROM system_settings WHERE key IN ("
        "'incubation_safe_subreddits', "
        "'incubation_phase_enabled', "
        "'phase_gate_p0_min_age_days', "
        "'phase_gate_p0_min_karma', "
        "'phase_gate_p0_min_posted_comments', "
        "'phase_gate_p0_max_deleted_comments', "
        "'phase0_freeze_timeout_days'"
        ")"
    )
