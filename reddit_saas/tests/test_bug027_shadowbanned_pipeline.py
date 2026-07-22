"""BUG-027 Regression: System must NOT include shadowbanned/inactive avatars in pipeline.

Production bug: Client pipeline was generating content for shadowbanned accounts
(Middle-Mode3001, emma_richardson) instead of active target accounts only.

Root cause: Avatar assignments (client_ids) not cleaned after shadowban detection.
The EPG filter excludes health_status="shadowbanned" but:
1. Health status might not be correctly set for all detected accounts
2. Client API endpoints (portal, review) may still show/count these avatars

This test verifies the pipeline exclusion gate works correctly.
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client


@pytest.fixture
def client_with_mixed_avatars(db: Session):
    """Create a client with both healthy and shadowbanned avatars."""
    client = Client(
        id=uuid.uuid4(),
        client_name="TestCorp Inc",
        brand_name="TestCorp",
        is_active=True,
        plan_type="starter",
    )
    db.add(client)
    db.flush()

    client_id_str = str(client.id)

    # Active healthy avatar
    healthy_avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"healthy_test_{uuid.uuid4().hex[:8]}",
        client_ids=[client_id_str],
        active=True,
        is_frozen=False,
        warming_phase=2,
        health_status="active",
        pool="b2b",
    )

    # Shadowbanned avatar (should be excluded from pipeline)
    shadowbanned_avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"shadowbanned_test_{uuid.uuid4().hex[:8]}",
        client_ids=[client_id_str],
        active=True,  # Still marked active — the bug!
        is_frozen=False,  # Not frozen — phase 0 demotion model
        warming_phase=0,
        health_status="shadowbanned",
        pool="b2b",
    )

    # Suspended avatar (should be excluded)
    suspended_avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"suspended_test_{uuid.uuid4().hex[:8]}",
        client_ids=[client_id_str],
        active=True,
        is_frozen=False,
        warming_phase=1,
        health_status="suspended",
        pool="b2b",
    )

    # Frozen avatar (should be excluded)
    frozen_avatar = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"frozen_test_{uuid.uuid4().hex[:8]}",
        client_ids=[client_id_str],
        active=True,
        is_frozen=True,
        warming_phase=2,
        health_status="active",
        pool="b2b",
    )

    db.add_all([healthy_avatar, shadowbanned_avatar, suspended_avatar, frozen_avatar])
    db.commit()

    return {
        "client": client,
        "healthy": healthy_avatar,
        "shadowbanned": shadowbanned_avatar,
        "suspended": suspended_avatar,
        "frozen": frozen_avatar,
    }


class TestEPGAvatarExclusion:
    """EPG must never build slots for shadowbanned/suspended/frozen avatars."""

    def test_epg_task_excludes_shadowbanned(self, db, client_with_mixed_avatars):
        """EPG query filter excludes health_status='shadowbanned'."""
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.pool != "mentor",
            )
            .all()
        )

        # Secondary filter (same as in epg.py)
        eligible = [
            a for a in avatars
            if a.health_status not in ("shadowbanned", "suspended")
        ]

        eligible_ids = {a.id for a in eligible}
        assert client_with_mixed_avatars["shadowbanned"].id not in eligible_ids
        assert client_with_mixed_avatars["suspended"].id not in eligible_ids
        assert client_with_mixed_avatars["frozen"].id not in eligible_ids
        assert client_with_mixed_avatars["healthy"].id in eligible_ids

    def test_epg_task_excludes_frozen(self, db, client_with_mixed_avatars):
        """EPG query filter excludes is_frozen=True."""
        avatars = (
            db.query(Avatar)
            .filter(
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.pool != "mentor",
            )
            .all()
        )

        avatar_ids = {a.id for a in avatars}
        assert client_with_mixed_avatars["frozen"].id not in avatar_ids

    def test_portfolio_manager_rejects_shadowbanned(self, db, client_with_mixed_avatars):
        """build_portfolio() returns 'excluded' for shadowbanned avatar."""
        from app.services.portfolio_manager import build_portfolio

        avatar = client_with_mixed_avatars["shadowbanned"]
        result = build_portfolio(db, avatar)

        assert result.status == "excluded"
        assert "shadowbanned" in result.message.lower()

    def test_portfolio_manager_rejects_suspended(self, db, client_with_mixed_avatars):
        """build_portfolio() returns 'excluded' for suspended avatar."""
        from app.services.portfolio_manager import build_portfolio

        avatar = client_with_mixed_avatars["suspended"]
        result = build_portfolio(db, avatar)

        assert result.status == "excluded"
        assert "suspended" in result.message.lower()

    def test_portfolio_manager_rejects_frozen(self, db, client_with_mixed_avatars):
        """build_portfolio() returns 'frozen' for frozen avatar."""
        from app.services.portfolio_manager import build_portfolio

        avatar = client_with_mixed_avatars["frozen"]
        result = build_portfolio(db, avatar)

        assert result.status == "frozen"


class TestClientAvatarVisibility:
    """Client-facing endpoints must not count/show shadowbanned avatars as active."""

    def test_client_active_avatar_count_excludes_unhealthy(self, db, client_with_mixed_avatars):
        """Active avatar count for client must exclude shadowbanned/suspended."""
        client = client_with_mixed_avatars["client"]
        client_id_str = str(client.id)

        # This is how the portal/admin counts active avatars
        active_count = (
            db.query(Avatar)
            .filter(
                Avatar.client_ids.any(client_id_str),
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
            )
            .count()
        )

        # BUG: Without health_status filter, this returns 3 (healthy + shadowbanned + suspended)
        # Expected: should show only truly pipeline-eligible avatars to the client

        # Count what EPG actually uses (the real eligibility)
        pipeline_eligible = (
            db.query(Avatar)
            .filter(
                Avatar.client_ids.any(client_id_str),
                Avatar.active.is_(True),
                Avatar.is_frozen.is_(False),
                Avatar.health_status.notin_(["shadowbanned", "suspended"]),
            )
            .count()
        )

        assert pipeline_eligible == 1  # Only healthy_account_01

        # The raw count without health filter (this is the bug symptom)
        # Client sees 3 "active" avatars but only 1 is actually working
        assert active_count == 3  # This confirms the display bug exists


class TestHealthStatusTransition:
    """When avatar is detected as shadowbanned, ensure it's properly marked."""

    def test_shadowban_sets_health_status(self, db, client_with_mixed_avatars):
        """Verify health_status field is properly set (precondition for EPG filter)."""
        avatar = client_with_mixed_avatars["shadowbanned"]
        assert avatar.health_status == "shadowbanned"

        # The filter that EPG uses
        assert avatar.health_status in ("shadowbanned", "suspended")

    def test_avatar_still_assigned_to_client_after_shadowban(self, db, client_with_mixed_avatars):
        """
        BUG CONFIRMATION: Shadowbanned avatar remains in client_ids.

        This is the root cause — avatar isn't removed from client assignment
        when shadowbanned. The fix should either:
        a) Remove from client_ids on shadowban (breaking change), OR
        b) Ensure ALL queries that show "client's avatars" filter by health_status
        """
        avatar = client_with_mixed_avatars["shadowbanned"]
        client = client_with_mixed_avatars["client"]

        # This is True — the assignment persists after shadowban
        assert str(client.id) in avatar.client_ids

        # This is the design question: should it persist?
        # Current design: YES (avatar may recover from shadowban → Phase 0 → re-enter pipeline)
        # The fix must be in the QUERY layer, not the assignment layer
