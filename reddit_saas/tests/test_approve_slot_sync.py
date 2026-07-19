"""Tests for EPG slot sync on draft approval.

Validates the fix for Bug B: when a draft is approved via any path
(portal, review API, extension, decision center), the linked EPG slot
MUST transition to "approved" and an ExecutionTask MUST be created.

This ensures the extension/email delivery channel picks up approved
drafts regardless of which UI surface triggered the approval.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_client_obj(db: Session) -> Client:
    """Create a test client."""
    c = Client(
        id=uuid.uuid4(),
        client_name="TestClient_SlotSync",
        brand_name="TestBrand",
        is_active=True,
        keywords={"high": ["test"], "medium": [], "low": []},
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture
def test_avatar(db: Session, test_client_obj: Client) -> Avatar:
    """Create a test avatar linked to the client."""
    a = Avatar(
        id=uuid.uuid4(),
        reddit_username=f"test_sync_{uuid.uuid4().hex[:6]}",
        warming_phase=2,
        is_frozen=False,
        health_status="healthy",
        pool="b2b",
        active=True,
        is_shadowbanned=False,
        client_ids=[str(test_client_obj.id)],
        delivery_channel="extension",
    )
    db.add(a)
    db.flush()
    return a


@pytest.fixture
def pending_draft_with_slot(db: Session, test_avatar: Avatar, test_client_obj: Client):
    """Create a pending draft linked to an EPG slot (status=generated).

    This simulates the state after EPG build + generation when auto_approve is OFF:
    - EPGSlot: status=generated
    - CommentDraft: status=pending
    """
    draft = CommentDraft(
        id=uuid.uuid4(),
        avatar_id=test_avatar.id,
        client_id=test_client_obj.id,
        ai_draft="This is a test comment for slot sync validation.",
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(draft)
    db.flush()

    slot = EPGSlot(
        id=uuid.uuid4(),
        avatar_id=test_avatar.id,
        client_id=test_client_obj.id,
        plan_date=date.today(),
        slot_type="hobby",
        status="generated",
        draft_id=draft.id,
        subreddit="CasualConversation",
        scheduled_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    db.add(slot)
    db.flush()

    return draft, slot


# ---------------------------------------------------------------------------
# Tests: sync_slot_status unit
# ---------------------------------------------------------------------------


class TestSyncSlotStatus:
    """Direct tests for the sync_slot_status function."""

    def test_approve_syncs_slot_and_dispatches(self, db: Session, pending_draft_with_slot):
        """When sync_slot_status is called with 'approved', slot transitions
        and _dispatch_email_task_if_enabled is called."""
        draft, slot = pending_draft_with_slot
        draft.status = "approved"
        db.flush()

        from app.services.epg_executor import sync_slot_status

        with patch("app.services.epg_executor._dispatch_email_task_if_enabled") as mock_dispatch:
            sync_slot_status(db, draft.id, "approved")
            db.flush()

        assert slot.status == "approved"
        mock_dispatch.assert_called_once_with(db, slot)

    def test_reject_syncs_slot_to_skipped(self, db: Session, pending_draft_with_slot):
        """When sync_slot_status is called with 'rejected', slot becomes skipped."""
        draft, slot = pending_draft_with_slot
        draft.status = "rejected"
        db.flush()

        from app.services.epg_executor import sync_slot_status
        sync_slot_status(db, draft.id, "rejected")
        db.flush()

        assert slot.status == "skipped"
        assert slot.skip_reason == "rejected_by_reviewer"

    def test_posted_syncs_slot(self, db: Session, pending_draft_with_slot):
        """When sync_slot_status is called with 'posted', slot transitions."""
        draft, slot = pending_draft_with_slot
        draft.status = "posted"
        db.flush()

        from app.services.epg_executor import sync_slot_status
        sync_slot_status(db, draft.id, "posted")
        db.flush()

        assert slot.status == "posted"
        assert slot.posted_at is not None

    def test_no_slot_is_noop(self, db: Session, test_avatar, test_client_obj):
        """When draft has no linked EPG slot, sync_slot_status does nothing."""
        draft = CommentDraft(
            id=uuid.uuid4(),
            avatar_id=test_avatar.id,
            client_id=test_client_obj.id,
            ai_draft="Draft without slot",
            status="approved",
            created_at=datetime.now(timezone.utc),
        )
        db.add(draft)
        db.flush()

        from app.services.epg_executor import sync_slot_status
        # Should not raise
        sync_slot_status(db, draft.id, "approved")
        db.flush()


# ---------------------------------------------------------------------------
# Tests: Portal approve path
# ---------------------------------------------------------------------------


class TestPortalApproveSlotSync:
    """Verify portal_approve_draft triggers slot sync."""

    def test_portal_approve_syncs_slot(self, db: Session, admin_client, pending_draft_with_slot, test_client_obj):
        """POST /clients/{id}/drafts/{id}/approve must sync EPG slot status."""
        draft, slot = pending_draft_with_slot

        with patch("app.services.epg_executor._dispatch_email_task_if_enabled"):
            resp = admin_client.post(
                f"/clients/{test_client_obj.id}/drafts/{draft.id}/approve",
            )

        assert resp.status_code == 200
        db.refresh(slot)
        assert slot.status == "approved"

    def test_portal_approve_creates_execution_task(self, db: Session, admin_client, pending_draft_with_slot, test_client_obj):
        """POST /clients/{id}/drafts/{id}/approve must call _dispatch_email_task_if_enabled."""
        draft, slot = pending_draft_with_slot

        with patch("app.services.epg_executor._dispatch_email_task_if_enabled") as mock_dispatch:
            resp = admin_client.post(
                f"/clients/{test_client_obj.id}/drafts/{draft.id}/approve",
            )

        assert resp.status_code == 200
        # _dispatch_email_task_if_enabled is called from sync_slot_status
        mock_dispatch.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: Review API path
# ---------------------------------------------------------------------------


class TestReviewApiSlotSync:
    """Verify PATCH /review-api/comments/{id} triggers slot sync."""

    def test_review_approve_syncs_slot(self, db: Session, admin_client, pending_draft_with_slot):
        """PATCH /review-api/comments/{id} with status=approved must sync EPG slot."""
        draft, slot = pending_draft_with_slot

        with patch("app.services.epg_executor._dispatch_email_task_if_enabled"):
            resp = admin_client.patch(
                f"/review-api/comments/{draft.id}",
                json={"status": "approved"},
            )

        assert resp.status_code == 200
        db.refresh(slot)
        assert slot.status == "approved"

    def test_review_reject_syncs_slot(self, db: Session, admin_client, pending_draft_with_slot):
        """PATCH /review-api/comments/{id} with status=rejected must sync EPG slot to skipped."""
        draft, slot = pending_draft_with_slot

        resp = admin_client.patch(
            f"/review-api/comments/{draft.id}",
            json={"status": "rejected"},
        )

        assert resp.status_code == 200
        db.refresh(slot)
        assert slot.status == "skipped"
