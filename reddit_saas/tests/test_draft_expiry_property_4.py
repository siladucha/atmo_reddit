"""Property test for Terminal State Preservation (Property 4).

Property 4: For any EPGSlot in a terminal status ('posted', 'skipped', 'expired')
or ExecutionTask in a terminal status ('submitted', 'verified', 'expired', 'cancelled'),
the expiry process SHALL NOT modify the record regardless of its association with an
expired draft.

Validates: Requirements 3.3, 4.3

Feature: stale-draft-expiry, Property 4: Terminal State Preservation
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.draft_expiry import DraftExpiryService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

epg_slot_terminal_statuses = st.sampled_from(["posted", "skipped", "expired"])

execution_task_terminal_statuses = st.sampled_from(
    ["submitted", "verified", "expired", "cancelled"]
)


@st.composite
def terminal_epg_slot(draw):
    """Generate a mock EPGSlot in a terminal status."""
    slot = MagicMock()
    slot.id = uuid.uuid4()
    slot.draft_id = uuid.uuid4()
    slot.status = draw(epg_slot_terminal_statuses)
    slot.skip_reason = draw(
        st.one_of(st.none(), st.text(min_size=1, max_size=50))
    )
    slot.scheduled_at = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=datetime(2025, 1, 1),
                max_value=datetime(2027, 12, 31),
                timezones=st.just(timezone.utc),
            ),
        )
    )
    return slot


@st.composite
def terminal_execution_task(draw):
    """Generate a mock ExecutionTask in a terminal status."""
    task = MagicMock()
    task.id = uuid.uuid4()
    task.epg_slot_id = uuid.uuid4()
    task.status = draw(execution_task_terminal_statuses)
    task.cancel_reason = draw(
        st.one_of(st.none(), st.text(min_size=1, max_size=50))
    )
    task.cancelled_at = draw(
        st.one_of(
            st.none(),
            st.datetimes(
                min_value=datetime(2025, 1, 1),
                max_value=datetime(2027, 12, 31),
                timezones=st.just(timezone.utc),
            ),
        )
    )
    task.task_lifecycle_status = draw(
        st.sampled_from(["ASSIGNED", "CANCELLED", "COMPLETED", None])
    )
    return task


# ---------------------------------------------------------------------------
# Property Tests
# ---------------------------------------------------------------------------


class TestTerminalStatePreservation:
    """Property 4: Terminal State Preservation.

    **Validates: Requirements 3.3, 4.3**
    """

    def setup_method(self):
        self.service = DraftExpiryService()

    @given(slot=terminal_epg_slot())
    @settings(max_examples=100)
    def test_cascade_epg_slot_does_not_modify_terminal_slots(self, slot):
        """Terminal EPGSlots are NOT modified by _cascade_epg_slot.

        For any EPGSlot in a terminal status ('posted', 'skipped', 'expired'),
        the method returns None and leaves status and skip_reason unchanged.
        """
        # Record initial state
        initial_status = slot.status
        initial_skip_reason = slot.skip_reason

        # Mock DB to return our terminal slot
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = slot

        draft_id = uuid.uuid4()

        # Call the method
        result = self.service._cascade_epg_slot(db, draft_id)

        # Assert: returns None for terminal slots
        assert result is None

        # Assert: status and skip_reason are NOT modified
        assert slot.status == initial_status
        assert slot.skip_reason == initial_skip_reason

    @given(
        tasks=st.lists(
            terminal_execution_task(), min_size=1, max_size=10
        )
    )
    @settings(max_examples=100)
    def test_cancel_execution_tasks_does_not_modify_terminal_tasks(self, tasks):
        """Terminal ExecutionTasks are NOT modified by _cancel_execution_tasks.

        For any ExecutionTask in a terminal status ('submitted', 'verified',
        'expired', 'cancelled'), the method returns 0 cancelled and leaves
        status, cancel_reason, and cancelled_at all unchanged.
        """
        # Record initial state of each task
        initial_states = []
        for task in tasks:
            initial_states.append(
                {
                    "status": task.status,
                    "cancel_reason": task.cancel_reason,
                    "cancelled_at": task.cancelled_at,
                    "task_lifecycle_status": task.task_lifecycle_status,
                }
            )

        # Create a mock slot (non-None so the method actually queries tasks)
        mock_slot = MagicMock()
        mock_slot.id = uuid.uuid4()

        # Mock DB to return our terminal tasks
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = tasks

        # Call the method
        cancelled_count = self.service._cancel_execution_tasks(db, mock_slot)

        # Assert: returns 0 since all tasks are terminal
        assert cancelled_count == 0

        # Assert: no task was modified
        for task, initial in zip(tasks, initial_states):
            assert task.status == initial["status"]
            assert task.cancel_reason == initial["cancel_reason"]
            assert task.cancelled_at == initial["cancelled_at"]
            assert task.task_lifecycle_status == initial["task_lifecycle_status"]

    @given(slot=terminal_epg_slot())
    @settings(max_examples=100)
    def test_cancel_execution_tasks_returns_zero_when_slot_is_none(self, slot):
        """_cancel_execution_tasks returns 0 when slot is None.

        When _cascade_epg_slot returns None (terminal slot), the subsequent
        call to _cancel_execution_tasks(db, None) returns 0 immediately.
        """
        db = MagicMock()

        # When slot is None, method should return 0 without querying
        cancelled_count = self.service._cancel_execution_tasks(db, None)

        assert cancelled_count == 0
        # DB should not be queried at all
        db.query.assert_not_called()
