"""Property-based test for DraftExpiryService cascade atomicity (Property 3).

Feature: stale-draft-expiry, Property 3: Cascade Atomicity

For any expired draft, if its associated EPGSlot has a non-terminal status
('generated' or 'approved'), then within the same database commit:
  - The slot status SHALL be 'expired' with skip_reason == 'draft_stale_expired'
  - All associated ExecutionTasks with non-terminal status SHALL have
    status == 'cancelled', cancel_reason == 'draft_stale_expired'
  - If task_lifecycle_status == 'ASSIGNED': it becomes 'CANCELLED'

**Validates: Requirements 3.2, 4.2, 4.5**
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.draft_expiry import DraftExpiryService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

non_terminal_slot_statuses = st.sampled_from(["generated", "approved"])
non_terminal_task_statuses = st.sampled_from(["generated", "emailed", "accepted"])
task_lifecycle_statuses = st.sampled_from(["CREATED", "ASSIGNED", "CANCELLED", "COMPLETED"])


@st.composite
def mock_epg_slot(draw):
    """Generate a mock EPGSlot with a non-terminal status."""
    slot = MagicMock()
    slot.id = uuid.uuid4()
    slot.draft_id = uuid.uuid4()
    slot.status = draw(non_terminal_slot_statuses)
    slot.skip_reason = None
    return slot


@st.composite
def mock_execution_task(draw):
    """Generate a mock ExecutionTask with random status and lifecycle."""
    task = MagicMock()
    task.id = uuid.uuid4()
    task.epg_slot_id = uuid.uuid4()
    task.status = draw(non_terminal_task_statuses)
    task.cancel_reason = None
    task.cancelled_at = None
    task.task_lifecycle_status = draw(task_lifecycle_statuses)
    return task


# ---------------------------------------------------------------------------
# Property Test
# ---------------------------------------------------------------------------


class TestCascadeAtomicityProperty:
    """Property 3: Cascade Atomicity — EPGSlot and ExecutionTask transitions."""

    @given(
        slot=mock_epg_slot(),
        tasks=st.lists(mock_execution_task(), min_size=0, max_size=10),
    )
    @settings(max_examples=100)
    def test_cascade_slot_transitions_to_expired(self, slot, tasks):
        """**Validates: Requirements 3.2**

        If EPGSlot has non-terminal status ('generated' or 'approved'), after
        cascade, slot.status == 'expired' and slot.skip_reason == 'draft_stale_expired'.
        """
        service = DraftExpiryService()
        db = MagicMock()

        # Mock db.query(EPGSlot).filter(...).first() to return our slot
        db.query.return_value.filter.return_value.first.return_value = slot

        draft_id = slot.draft_id

        # Call cascade
        result_slot = service._cascade_epg_slot(db, draft_id)

        # Assert: slot transitioned to expired with correct skip_reason
        assert result_slot is not None
        assert slot.status == "expired"
        assert slot.skip_reason == "draft_stale_expired"

    @given(
        slot=mock_epg_slot(),
        tasks=st.lists(mock_execution_task(), min_size=1, max_size=10),
    )
    @settings(max_examples=100)
    def test_cascade_tasks_cancelled_with_reason(self, slot, tasks):
        """**Validates: Requirements 4.2, 4.5**

        For each ExecutionTask with non-terminal status ('generated', 'emailed',
        'accepted'): after cancellation, task.status == 'cancelled' and
        task.cancel_reason == 'draft_stale_expired'.
        If task_lifecycle_status == 'ASSIGNED', it becomes 'CANCELLED'.
        """
        service = DraftExpiryService()
        db = MagicMock()

        # Set all tasks to reference this slot
        for task in tasks:
            task.epg_slot_id = slot.id

        # Mock db.query(ExecutionTask).filter(...).all() to return our tasks
        db.query.return_value.filter.return_value.all.return_value = tasks

        # First cascade the slot to get it into expired state
        db_slot = MagicMock()
        db_slot.query = db.query
        db.query.return_value.filter.return_value.first.return_value = slot
        service._cascade_epg_slot(db, slot.draft_id)

        # Now cancel execution tasks — pass the expired slot
        cancelled_count = service._cancel_execution_tasks(db, slot)

        # Assert: all tasks with non-terminal status are cancelled correctly
        assert cancelled_count == len(tasks)
        for task in tasks:
            assert task.status == "cancelled"
            assert task.cancel_reason == "draft_stale_expired"
            assert task.cancelled_at is not None

    @given(
        slot=mock_epg_slot(),
        tasks=st.lists(mock_execution_task(), min_size=1, max_size=10),
    )
    @settings(max_examples=100)
    def test_assigned_lifecycle_becomes_cancelled(self, slot, tasks):
        """**Validates: Requirements 4.5**

        If task_lifecycle_status == 'ASSIGNED' before cancellation, it SHALL
        become 'CANCELLED' after.
        """
        service = DraftExpiryService()
        db = MagicMock()

        # Track which tasks were ASSIGNED before cancellation
        assigned_task_ids = set()
        non_assigned_task_ids = set()
        for task in tasks:
            task.epg_slot_id = slot.id
            if task.task_lifecycle_status == "ASSIGNED":
                assigned_task_ids.add(task.id)
            else:
                non_assigned_task_ids.add(task.id)

        # Record original lifecycle statuses for non-ASSIGNED tasks
        original_lifecycle = {}
        for task in tasks:
            if task.id in non_assigned_task_ids:
                original_lifecycle[task.id] = task.task_lifecycle_status

        # Mock db.query(ExecutionTask).filter(...).all()
        db.query.return_value.filter.return_value.all.return_value = tasks

        # Cancel execution tasks
        service._cancel_execution_tasks(db, slot)

        # Assert lifecycle transitions
        for task in tasks:
            if task.id in assigned_task_ids:
                assert task.task_lifecycle_status == "CANCELLED"
            else:
                # Non-ASSIGNED tasks keep their original lifecycle status
                assert task.task_lifecycle_status == original_lifecycle[task.id]

    @given(
        slot=mock_epg_slot(),
        tasks=st.lists(mock_execution_task(), min_size=0, max_size=10),
    )
    @settings(max_examples=100)
    def test_full_cascade_atomicity(self, slot, tasks):
        """**Validates: Requirements 3.2, 4.2, 4.5**

        Full cascade: _cascade_epg_slot + _cancel_execution_tasks executed
        together. Both slot and all non-terminal tasks transition correctly
        in what would be a single database commit.
        """
        service = DraftExpiryService()
        db = MagicMock()

        # Set all tasks to reference this slot
        for task in tasks:
            task.epg_slot_id = slot.id

        # Track which tasks had ASSIGNED lifecycle
        originally_assigned = {
            task.id for task in tasks if task.task_lifecycle_status == "ASSIGNED"
        }

        # Setup mock chain for cascade_epg_slot (query → filter → first)
        filter_mock_slot = MagicMock()
        filter_mock_slot.first.return_value = slot

        # Setup mock chain for cancel_execution_tasks (query → filter → all)
        filter_mock_tasks = MagicMock()
        filter_mock_tasks.all.return_value = tasks

        # We need the db.query to route correctly for both calls
        # _cascade_epg_slot calls: db.query(EPGSlot).filter(...).first()
        # _cancel_execution_tasks calls: db.query(ExecutionTask).filter(...).all()
        call_count = [0]

        def query_side_effect(*args):
            call_count[0] += 1
            mock_q = MagicMock()
            if call_count[0] == 1:
                # First call: EPGSlot query in _cascade_epg_slot
                mock_q.filter.return_value = filter_mock_slot
            else:
                # Second call: ExecutionTask query in _cancel_execution_tasks
                mock_q.filter.return_value = filter_mock_tasks
            return mock_q

        db.query.side_effect = query_side_effect

        # Execute full cascade
        result_slot = service._cascade_epg_slot(db, slot.draft_id)
        cancelled_count = service._cancel_execution_tasks(db, result_slot)

        # Assert slot cascade
        assert slot.status == "expired"
        assert slot.skip_reason == "draft_stale_expired"

        # Assert task cancellation
        assert cancelled_count == len(tasks)
        for task in tasks:
            assert task.status == "cancelled"
            assert task.cancel_reason == "draft_stale_expired"
            assert task.cancelled_at is not None
            if task.id in originally_assigned:
                assert task.task_lifecycle_status == "CANCELLED"
