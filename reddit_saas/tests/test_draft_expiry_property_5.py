"""Property test for Batch Independence and Error Isolation (Property 5).

**Validates: Requirements 1.4, 1.6, 2.3, 2.5**

Property 5: Batch Independence and Error Isolation
For any set of N stale drafts processed in ceil(N/50) batches, if batch K fails
with a database error, then:
  (a) batches 1 through K-1 remain committed,
  (b) batch K is fully rolled back,
  (c) batches K+1 through ceil(N/50) are still attempted and can succeed independently.

Feature: stale-draft-expiry, Property 5: Batch Independence and Error Isolation
"""

import math
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy.exc import SQLAlchemyError

from app.services.draft_expiry import (
    BatchResult,
    DraftExpiry,
    DraftExpiryService,
)


def _make_mock_draft(index: int) -> MagicMock:
    """Create a mock CommentDraft with a unique id for testing."""
    draft = MagicMock()
    draft.id = uuid.uuid4()
    draft.avatar_id = uuid.uuid4()
    draft.client_id = uuid.uuid4()
    draft.status = "approved"
    draft.created_at = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    draft.updated_at = datetime(2026, 7, 2, 10, 0, tzinfo=timezone.utc)
    draft.learning_metadata = None
    return draft


def _make_draft_expiry(draft: MagicMock) -> DraftExpiry:
    """Create a DraftExpiry result for a successfully expired draft."""
    return DraftExpiry(
        draft_id=draft.id,
        avatar_id=draft.avatar_id,
        client_id=draft.client_id,
        original_status="approved",
        age_hours=72,
        slot_expired=False,
        tasks_cancelled=0,
    )


@settings(max_examples=100, deadline=None)
@given(
    n_drafts=st.integers(min_value=1, max_value=200),
    failure_batch_offset=st.floats(min_value=0.0, max_value=1.0),
)
def test_batch_independence_error_isolation(n_drafts: int, failure_batch_offset: float):
    """Property 5: Batch Independence and Error Isolation.

    **Validates: Requirements 1.4, 1.6, 2.3, 2.5**

    For N drafts in ceil(N/50) batches, injecting a failure at batch K:
    - Batches before K produce DraftExpiry results (committed)
    - Batch K produces 0 results and 1 error string (rolled back)
    - Batches after K produce DraftExpiry results (committed)
    - Total successful expiries = N - (size of batch K)
    """
    total_batches = math.ceil(n_drafts / 50)
    # Derive failure batch index K from the float offset (0 to total_batches-1)
    failure_batch_k = min(
        int(failure_batch_offset * total_batches), total_batches - 1
    )

    # Create N mock drafts
    all_drafts = [_make_mock_draft(i) for i in range(n_drafts)]

    # Chunk into batches of 50 (same logic as run())
    batches = []
    for i in range(0, n_drafts, 50):
        batches.append(all_drafts[i : i + 50])

    assert len(batches) == total_batches

    # Track which batch is currently being processed
    batch_call_count = [0]

    service = DraftExpiryService()
    now = datetime(2026, 7, 5, 14, 0, tzinfo=timezone.utc)

    def mock_expire_draft(db, draft, now_arg):
        """Mock _expire_draft: raises SQLAlchemyError for drafts in batch K."""
        # Determine which batch this draft belongs to
        draft_index = all_drafts.index(draft)
        draft_batch_index = draft_index // 50

        if draft_batch_index == failure_batch_k:
            raise SQLAlchemyError("Simulated database error in batch K")

        return _make_draft_expiry(draft)

    # Process each batch directly using _process_batch to verify isolation
    db = MagicMock()
    # Mock begin_nested as a context manager
    db.begin_nested.return_value.__enter__ = MagicMock()
    db.begin_nested.return_value.__exit__ = MagicMock(return_value=False)

    batch_results: list[BatchResult] = []

    with patch.object(service, "_expire_draft", side_effect=mock_expire_draft):
        for batch in batches:
            result = service._process_batch(db, batch, now)
            batch_results.append(result)

    # --- Assertions ---

    # (a) Batches before K produced DraftExpiry results (committed)
    for i in range(failure_batch_k):
        batch_size = len(batches[i])
        assert len(batch_results[i].expired) == batch_size, (
            f"Batch {i} (before failure batch {failure_batch_k}) should have "
            f"{batch_size} expired drafts, got {len(batch_results[i].expired)}"
        )
        assert len(batch_results[i].errors) == 0, (
            f"Batch {i} (before failure) should have 0 errors"
        )

    # (b) Batch K produced 0 results and 1 error string (rolled back)
    assert len(batch_results[failure_batch_k].expired) == 0, (
        f"Failure batch {failure_batch_k} should have 0 expired drafts "
        f"(rolled back), got {len(batch_results[failure_batch_k].expired)}"
    )
    assert len(batch_results[failure_batch_k].errors) == 1, (
        f"Failure batch {failure_batch_k} should have exactly 1 error string, "
        f"got {len(batch_results[failure_batch_k].errors)}"
    )

    # (c) Batches after K produced DraftExpiry results (committed)
    for i in range(failure_batch_k + 1, total_batches):
        batch_size = len(batches[i])
        assert len(batch_results[i].expired) == batch_size, (
            f"Batch {i} (after failure batch {failure_batch_k}) should have "
            f"{batch_size} expired drafts, got {len(batch_results[i].expired)}"
        )
        assert len(batch_results[i].errors) == 0, (
            f"Batch {i} (after failure) should have 0 errors"
        )

    # Total successful expiries = N - (size of batch K)
    failed_batch_size = len(batches[failure_batch_k])
    total_expired = sum(len(r.expired) for r in batch_results)
    expected_total = n_drafts - failed_batch_size

    assert total_expired == expected_total, (
        f"Total expired should be {expected_total} "
        f"(N={n_drafts} minus batch K size={failed_batch_size}), "
        f"got {total_expired}"
    )
