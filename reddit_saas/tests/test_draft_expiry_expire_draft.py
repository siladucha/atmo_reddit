"""Unit tests for DraftExpiryService._expire_draft() method."""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.services.draft_expiry import DraftExpiryService, DraftExpiry


def _make_draft(
    status: str = "approved",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
    learning_metadata: dict | None = None,
):
    """Create a mock CommentDraft for testing."""
    draft = MagicMock()
    draft.id = uuid.uuid4()
    draft.avatar_id = uuid.uuid4()
    draft.client_id = uuid.uuid4()
    draft.status = status
    draft.created_at = created_at or datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    draft.updated_at = updated_at or datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    draft.learning_metadata = learning_metadata
    return draft


class TestExpireDraft:
    """Tests for _expire_draft method."""

    def setup_method(self):
        self.service = DraftExpiryService()
        self.db = MagicMock()
        self.now = datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc)

    def test_approved_draft_status_set_to_expired(self):
        """Approved draft transitions to 'expired' status."""
        draft = _make_draft(status="approved")
        result = self.service._expire_draft(self.db, draft, self.now)

        assert draft.status == "expired"
        assert result.original_status == "approved"

    def test_pending_draft_status_set_to_expired(self):
        """Pending draft transitions to 'expired' status."""
        draft = _make_draft(status="pending")
        result = self.service._expire_draft(self.db, draft, self.now)

        assert draft.status == "expired"
        assert result.original_status == "pending"

    def test_approved_age_computed_from_updated_at(self):
        """Approved draft age is hours since updated_at."""
        # updated_at = July 2 10:00, now = July 5 14:00 → 76 hours
        draft = _make_draft(
            status="approved",
            updated_at=datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc),
        )
        result = self.service._expire_draft(self.db, draft, self.now)

        assert result.age_hours == 76

    def test_pending_age_computed_from_created_at(self):
        """Pending draft age is hours since created_at."""
        # created_at = July 1 10:00, now = July 5 14:00 → 100 hours
        draft = _make_draft(
            status="pending",
            created_at=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        )
        result = self.service._expire_draft(self.db, draft, self.now)

        assert result.age_hours == 100

    def test_age_truncates_to_whole_hours(self):
        """Age should be truncated (int) not rounded."""
        # 49h 59min → should be 49, not 50
        draft = _make_draft(
            status="approved",
            updated_at=self.now - timedelta(hours=49, minutes=59),
        )
        result = self.service._expire_draft(self.db, draft, self.now)

        assert result.age_hours == 49

    def test_learning_metadata_set_when_none(self):
        """When learning_metadata is None, it starts fresh with expiry info."""
        draft = _make_draft(status="approved", learning_metadata=None)
        self.service._expire_draft(self.db, draft, self.now)

        assert draft.learning_metadata["expiry_reason"] == "stale_approved"
        assert isinstance(draft.learning_metadata["stale_age_hours"], int)
        assert draft.learning_metadata["expired_at"] == self.now.isoformat()

    def test_learning_metadata_preserves_existing_keys(self):
        """Existing learning_metadata keys are preserved when adding expiry info."""
        existing_meta = {
            "edit_record_ids": ["rec-1", "rec-2"],
            "correction_patterns": ["pattern1"],
        }
        draft = _make_draft(status="pending", learning_metadata=existing_meta)
        self.service._expire_draft(self.db, draft, self.now)

        # Existing keys preserved
        assert draft.learning_metadata["edit_record_ids"] == ["rec-1", "rec-2"]
        assert draft.learning_metadata["correction_patterns"] == ["pattern1"]
        # Expiry keys added
        assert draft.learning_metadata["expiry_reason"] == "stale_pending"
        assert "stale_age_hours" in draft.learning_metadata
        assert "expired_at" in draft.learning_metadata

    def test_expiry_reason_stale_approved(self):
        """Approved drafts get reason 'stale_approved'."""
        draft = _make_draft(status="approved")
        self.service._expire_draft(self.db, draft, self.now)

        assert draft.learning_metadata["expiry_reason"] == "stale_approved"

    def test_expiry_reason_stale_pending(self):
        """Pending drafts get reason 'stale_pending'."""
        draft = _make_draft(status="pending")
        self.service._expire_draft(self.db, draft, self.now)

        assert draft.learning_metadata["expiry_reason"] == "stale_pending"

    def test_expired_at_is_iso8601(self):
        """expired_at is stored as ISO 8601 string."""
        draft = _make_draft(status="approved")
        self.service._expire_draft(self.db, draft, self.now)

        expired_at = draft.learning_metadata["expired_at"]
        # Should parse without error
        parsed = datetime.fromisoformat(expired_at)
        assert parsed == self.now

    def test_returns_draft_expiry_dataclass(self):
        """Returns a fully populated DraftExpiry dataclass."""
        draft = _make_draft(status="approved")
        result = self.service._expire_draft(self.db, draft, self.now)

        assert isinstance(result, DraftExpiry)
        assert result.draft_id == draft.id
        assert result.avatar_id == draft.avatar_id
        assert result.client_id == draft.client_id
        assert result.original_status == "approved"
        assert isinstance(result.age_hours, int)
        # Cascade stubs return None/0
        assert result.slot_expired is False
        assert result.tasks_cancelled == 0

    def test_cascade_methods_called(self):
        """_cascade_epg_slot and _cancel_execution_tasks are called."""
        draft = _make_draft(status="approved")

        with patch.object(
            self.service, "_cascade_epg_slot", return_value=None
        ) as mock_cascade, patch.object(
            self.service, "_cancel_execution_tasks", return_value=0
        ) as mock_cancel:
            self.service._expire_draft(self.db, draft, self.now)

            mock_cascade.assert_called_once_with(self.db, draft.id)
            mock_cancel.assert_called_once_with(self.db, None)

    def test_cascade_slot_expired_true_when_slot_returned(self):
        """slot_expired is True when _cascade_epg_slot returns a slot."""
        draft = _make_draft(status="approved")
        mock_slot = MagicMock()

        with patch.object(
            self.service, "_cascade_epg_slot", return_value=mock_slot
        ), patch.object(self.service, "_cancel_execution_tasks", return_value=3):
            result = self.service._expire_draft(self.db, draft, self.now)

            assert result.slot_expired is True
            assert result.tasks_cancelled == 3

    def test_learning_metadata_updated_in_place(self):
        """learning_metadata is mutated in place (not replaced) for JSONB detection."""
        existing_meta = {"existing_key": "value"}
        draft = _make_draft(status="approved", learning_metadata=existing_meta)

        self.service._expire_draft(self.db, draft, self.now)

        # Verify the dict was updated in-place (same object reference)
        assert draft.learning_metadata is existing_meta
        assert "expiry_reason" in draft.learning_metadata
        assert draft.learning_metadata["existing_key"] == "value"
