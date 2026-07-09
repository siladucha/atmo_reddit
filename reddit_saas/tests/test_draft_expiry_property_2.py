"""Property-based test for DraftExpiryService — Property 2: Status Transition Integrity.

For any stale draft identified by the candidate query, after expiry processing
completes, the draft's status SHALL be 'expired' and its `learning_metadata`
SHALL contain `stale_age_hours` (integer, equal to the actual age in whole hours
at the time of expiry).

Validates: Requirements 1.3, 2.2, 8.4

Feature: stale-draft-expiry, Property 2: Status Transition Integrity
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.draft_expiry import DraftExpiryService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def stale_drafts(draw):
    """Generate random stale drafts with varying statuses and timestamps.

    Produces mock CommentDraft objects with status 'approved' or 'pending'
    and timestamps old enough to be considered stale (49-500 hours old).
    """
    status = draw(st.sampled_from(["approved", "pending"]))

    # Age in hours: at least 49h (past approved threshold of 48h) and up to 500h
    age_hours = draw(st.integers(min_value=49, max_value=500))
    # Add fractional minutes to test truncation behavior
    extra_minutes = draw(st.integers(min_value=0, max_value=59))

    now = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
    age_delta = timedelta(hours=age_hours, minutes=extra_minutes)

    draft = MagicMock()
    draft.id = uuid.uuid4()
    draft.avatar_id = uuid.uuid4()
    draft.client_id = uuid.uuid4()
    draft.status = status

    # Set timestamps based on status
    if status == "approved":
        draft.updated_at = now - age_delta
        draft.created_at = now - age_delta - timedelta(hours=draw(st.integers(min_value=1, max_value=48)))
    else:  # pending
        draft.created_at = now - age_delta
        draft.updated_at = now - age_delta + timedelta(hours=draw(st.integers(min_value=0, max_value=24)))

    # Optionally include existing learning_metadata
    has_existing_metadata = draw(st.booleans())
    if has_existing_metadata:
        draft.learning_metadata = draw(
            st.fixed_dictionaries({
                "edit_record_ids": st.lists(st.text(min_size=3, max_size=10), max_size=3),
            })
        )
    else:
        draft.learning_metadata = None

    return draft, now, age_hours, extra_minutes


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestStatusTransitionIntegrity:
    """Property 2: Status Transition Integrity.

    **Validates: Requirements 1.3, 2.2, 8.4**
    """

    @given(data=stale_drafts())
    @settings(max_examples=100)
    def test_expired_draft_has_correct_status_and_metadata(self, data):
        """For any stale draft, after expiry:
        - status == 'expired'
        - learning_metadata['stale_age_hours'] is an integer
        - stale_age_hours equals int((now - reference_time).total_seconds() / 3600)
        - expiry_reason matches original status
        """
        draft, now, age_hours, extra_minutes = data
        original_status = draft.status

        service = DraftExpiryService()
        db = MagicMock()

        with patch.object(service, "_cascade_epg_slot", return_value=None), \
             patch.object(service, "_cancel_execution_tasks", return_value=0):
            service._expire_draft(db, draft, now)

        # 1. Draft status MUST be 'expired' after processing
        assert draft.status == "expired", (
            f"Draft status should be 'expired', got '{draft.status}'"
        )

        # 2. learning_metadata MUST contain stale_age_hours as integer
        assert draft.learning_metadata is not None, (
            "learning_metadata should not be None after expiry"
        )
        assert "stale_age_hours" in draft.learning_metadata, (
            "learning_metadata must contain 'stale_age_hours'"
        )
        stale_age = draft.learning_metadata["stale_age_hours"]
        assert isinstance(stale_age, int), (
            f"stale_age_hours must be an integer, got {type(stale_age).__name__}"
        )

        # 3. stale_age_hours equals the actual age in whole hours
        if original_status == "approved":
            reference_time = draft.updated_at
        else:  # pending
            reference_time = draft.created_at

        expected_age = int((now - reference_time).total_seconds() / 3600)
        assert stale_age == expected_age, (
            f"stale_age_hours should be {expected_age}, got {stale_age} "
            f"(status={original_status})"
        )

        # 4. expiry_reason matches original status
        assert "expiry_reason" in draft.learning_metadata, (
            "learning_metadata must contain 'expiry_reason'"
        )
        expiry_reason = draft.learning_metadata["expiry_reason"]
        if original_status == "approved":
            assert expiry_reason == "stale_approved", (
                f"expiry_reason should be 'stale_approved' for approved draft, "
                f"got '{expiry_reason}'"
            )
        else:
            assert expiry_reason == "stale_pending", (
                f"expiry_reason should be 'stale_pending' for pending draft, "
                f"got '{expiry_reason}'"
            )
