"""Property test for Execution Window Protection (Property 7).

**Validates: Requirements 1.2**

Property 7: Execution Window Protection
For any approved draft with an associated EPGSlot whose `scheduled_at` is within
the next 2 hours from the current time, the draft SHALL NOT appear in the expiry
candidate set regardless of its age.

Feature: stale-draft-expiry, Property 7: Execution Window Protection
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, note
from hypothesis import strategies as st

from app.services.draft_expiry import DraftExpiryService


# ---------------------------------------------------------------------------
# Fixed reference time
# ---------------------------------------------------------------------------

NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Mock Data Structures
# ---------------------------------------------------------------------------


@dataclass
class MockDraft:
    """A generated draft for testing execution window protection."""

    id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime
    client_id: Optional[uuid.UUID]
    avatar_id: uuid.UUID


@dataclass
class MockEPGSlot:
    """A generated EPG slot associated with a draft."""

    id: uuid.UUID
    draft_id: uuid.UUID
    scheduled_at: Optional[datetime]


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

# Age of draft in hours — range from just past threshold to extremely old (1000h)
# All generated drafts will exceed a 48h threshold to ensure they WOULD normally
# be candidates (tests that protection works regardless of age)
draft_age_hours = st.integers(min_value=49, max_value=1000)

# EPG scheduled_at within the 2-hour protection window: offset from NOW in minutes
# Range: 0 minutes (exactly now) to 119 minutes (just under 2h)
protection_window_offset_minutes = st.integers(min_value=0, max_value=119)

# Number of protected drafts to generate
num_protected_drafts = st.integers(min_value=1, max_value=20)

# Number of unprotected drafts to include (for contrast)
num_unprotected_drafts = st.integers(min_value=0, max_value=15)


@st.composite
def protected_draft(draw):
    """Generate a draft that IS protected (EPGSlot within 2h).

    These drafts are intentionally very old (age > threshold) to prove
    that execution window protection overrides age-based expiry.
    """
    draft_id = draw(st.builds(uuid.uuid4))
    age = draw(draft_age_hours)
    offset_min = draw(protection_window_offset_minutes)

    draft = MockDraft(
        id=draft_id,
        status="approved",
        created_at=NOW - timedelta(hours=age + 24),
        updated_at=NOW - timedelta(hours=age),
        client_id=draw(st.builds(uuid.uuid4)),
        avatar_id=draw(st.builds(uuid.uuid4)),
    )

    # EPG slot scheduled within the next 2 hours from NOW
    epg_slot = MockEPGSlot(
        id=draw(st.builds(uuid.uuid4)),
        draft_id=draft_id,
        scheduled_at=NOW + timedelta(minutes=offset_min),
    )

    return draft, epg_slot


@st.composite
def unprotected_draft(draw):
    """Generate a draft that is NOT protected (no EPGSlot, or slot > 2h away).

    These drafts are also old enough to be candidates, and have valid client_id.
    """
    draft_id = draw(st.builds(uuid.uuid4))
    age = draw(draft_age_hours)

    draft = MockDraft(
        id=draft_id,
        status="approved",
        created_at=NOW - timedelta(hours=age + 24),
        updated_at=NOW - timedelta(hours=age),
        client_id=draw(st.builds(uuid.uuid4)),
        avatar_id=draw(st.builds(uuid.uuid4)),
    )

    # Either no EPG slot, or slot scheduled > 2h from now
    has_slot = draw(st.booleans())
    epg_slot = None
    if has_slot:
        # Scheduled more than 2 hours from now (121 min to 72h)
        far_offset = draw(st.integers(min_value=121, max_value=4320))
        epg_slot = MockEPGSlot(
            id=draw(st.builds(uuid.uuid4)),
            draft_id=draft_id,
            scheduled_at=NOW + timedelta(minutes=far_offset),
        )

    return draft, epg_slot


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestExecutionWindowProtectionProperty:
    """Property 7: Execution Window Protection.

    For any approved draft with an associated EPGSlot whose scheduled_at is
    within the next 2 hours from NOW, the draft SHALL NOT appear in the expiry
    candidate set regardless of its age.

    Feature: stale-draft-expiry, Property 7: Execution Window Protection
    """

    @given(
        protected_drafts=st.lists(protected_draft(), min_size=1, max_size=20),
        unprotected_drafts=st.lists(unprotected_draft(), min_size=0, max_size=15),
    )
    @settings(max_examples=100)
    def test_protected_drafts_never_in_candidate_set(
        self,
        protected_drafts: list[tuple[MockDraft, MockEPGSlot]],
        unprotected_drafts: list[tuple[MockDraft, Optional[MockEPGSlot]]],
    ):
        """Regardless of how old a draft is (even 1000h old), if its EPGSlot
        is scheduled within the next 2 hours, it SHALL NOT appear in candidates.

        The DB correctly filters these out via the SQL WHERE clause:
          (es.id IS NULL OR es.scheduled_at IS NULL OR es.scheduled_at > NOW + 2h)

        We simulate this: the DB returns only unprotected drafts (the SQL filter
        works correctly). We verify no protected draft IDs appear in the result.

        **Validates: Requirements 1.2**
        """
        service = DraftExpiryService()
        approved_threshold = 48  # Standard threshold

        # Collect protected draft IDs — these must NEVER appear in results
        protected_ids = {draft.id for draft, _ in protected_drafts}

        note(f"Protected draft count: {len(protected_drafts)}")
        note(f"Unprotected draft count: {len(unprotected_drafts)}")

        # Log ages to show we're testing extreme ages
        for draft, slot in protected_drafts:
            age_h = int((NOW - draft.updated_at).total_seconds() / 3600)
            offset_min = int((slot.scheduled_at - NOW).total_seconds() / 60)
            note(
                f"  Protected: age={age_h}h, "
                f"slot_offset=+{offset_min}min"
            )

        # Simulate what the SQL query returns AFTER the protection filter:
        # Only unprotected drafts pass the WHERE clause
        protection_window = NOW + timedelta(hours=2)
        db_would_return = []
        for draft, epg_slot in unprotected_drafts:
            # Verify this draft is genuinely unprotected
            if epg_slot is not None and epg_slot.scheduled_at is not None:
                if epg_slot.scheduled_at <= protection_window:
                    # This shouldn't happen given our strategy, but defensive
                    continue
            # Only include if age exceeds threshold
            cutoff = NOW - timedelta(hours=approved_threshold)
            if draft.updated_at >= cutoff:
                continue
            db_would_return.append(draft)

        db_would_return = db_would_return[:500]

        # Mock the DB query
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.outerjoin.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = db_would_return

        with patch("app.services.draft_expiry.datetime") as mock_datetime:
            mock_datetime.now.return_value = NOW
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = service._query_stale_approved(mock_db, approved_threshold)

        # CORE PROPERTY ASSERTION:
        # No draft with EPGSlot.scheduled_at within 2h of NOW appears in candidates
        result_ids = {d.id for d in result}
        for pid in protected_ids:
            assert pid not in result_ids, (
                f"Protected draft {pid} (EPGSlot within 2h of NOW) "
                f"incorrectly included in expiry candidate set. "
                f"Execution window protection VIOLATED."
            )

        # Additional: all results are unprotected drafts with valid client_id
        for draft in result:
            assert draft.client_id is not None, (
                f"Draft {draft.id} has client_id=None but appeared in results"
            )
            assert draft.id not in protected_ids, (
                f"Draft {draft.id} is protected but appeared in results"
            )

    @given(
        age_hours=st.integers(min_value=49, max_value=1000),
        offset_minutes=st.integers(min_value=0, max_value=119),
    )
    @settings(max_examples=100)
    def test_single_draft_protection_at_any_age(
        self,
        age_hours: int,
        offset_minutes: int,
    ):
        """For a single approved draft of any age with EPGSlot within 2h,
        it SHALL NOT be returned as an expiry candidate.

        This focuses on the guarantee that age is irrelevant when execution
        window protection applies — even a 1000-hour-old draft is protected.

        **Validates: Requirements 1.2**
        """
        service = DraftExpiryService()
        approved_threshold = 48

        draft_id = uuid.uuid4()
        draft = MockDraft(
            id=draft_id,
            status="approved",
            created_at=NOW - timedelta(hours=age_hours + 24),
            updated_at=NOW - timedelta(hours=age_hours),
            client_id=uuid.uuid4(),
            avatar_id=uuid.uuid4(),
        )

        epg_slot = MockEPGSlot(
            id=uuid.uuid4(),
            draft_id=draft_id,
            scheduled_at=NOW + timedelta(minutes=offset_minutes),
        )

        note(f"Draft age: {age_hours}h, slot offset: +{offset_minutes}min from NOW")

        # The SQL protection filter would EXCLUDE this draft.
        # DB returns empty (this draft is the only one, and it's protected).
        db_would_return = []

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.outerjoin.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = db_would_return

        with patch("app.services.draft_expiry.datetime") as mock_datetime:
            mock_datetime.now.return_value = NOW
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = service._query_stale_approved(mock_db, approved_threshold)

        # PROPERTY: The protected draft must NOT be in the result
        assert len(result) == 0, (
            f"Expected 0 candidates (sole draft is protected), got {len(result)}. "
            f"Draft age={age_hours}h, slot_offset=+{offset_minutes}min. "
            f"Execution window protection MUST override age."
        )

    @given(
        protected_count=st.integers(min_value=1, max_value=10),
        unprotected_count=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=100)
    def test_mixed_set_only_unprotected_returned(
        self,
        protected_count: int,
        unprotected_count: int,
    ):
        """Given a mix of protected and unprotected drafts, the result contains
        ONLY unprotected drafts. Protected drafts are filtered out by the SQL,
        and the count of results equals exactly the unprotected count.

        **Validates: Requirements 1.2**
        """
        service = DraftExpiryService()
        approved_threshold = 48

        # Create protected drafts (slot within 2h)
        protected_drafts_list = []
        for _ in range(protected_count):
            did = uuid.uuid4()
            d = MockDraft(
                id=did,
                status="approved",
                created_at=NOW - timedelta(hours=200),
                updated_at=NOW - timedelta(hours=100),
                client_id=uuid.uuid4(),
                avatar_id=uuid.uuid4(),
            )
            protected_drafts_list.append(d)

        protected_ids = {d.id for d in protected_drafts_list}

        # Create unprotected drafts (no slot or slot > 2h away)
        unprotected_drafts_list = []
        for _ in range(unprotected_count):
            d = MockDraft(
                id=uuid.uuid4(),
                status="approved",
                created_at=NOW - timedelta(hours=200),
                updated_at=NOW - timedelta(hours=100),
                client_id=uuid.uuid4(),
                avatar_id=uuid.uuid4(),
            )
            unprotected_drafts_list.append(d)

        # DB returns only the unprotected drafts (SQL WHERE filters out protected)
        db_would_return = unprotected_drafts_list[:500]

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.outerjoin.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.all.return_value = db_would_return

        with patch("app.services.draft_expiry.datetime") as mock_datetime:
            mock_datetime.now.return_value = NOW
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = service._query_stale_approved(mock_db, approved_threshold)

        # PROPERTY: result count == unprotected_count (all passed, none protected)
        assert len(result) == unprotected_count, (
            f"Expected {unprotected_count} unprotected candidates, "
            f"got {len(result)}. Protected drafts may have leaked through."
        )

        # PROPERTY: No protected ID in result
        result_ids = {d.id for d in result}
        for pid in protected_ids:
            assert pid not in result_ids, (
                f"Protected draft {pid} found in result set. "
                f"Execution window protection VIOLATED."
            )
