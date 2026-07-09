"""Property test for Activity Event Per-Client Grouping (Property 6).

**Validates: Requirements 5.1, 5.2, 5.3, 5.5**

Property 6: Activity Event Per-Client Grouping
For any expiry run that expires drafts for C distinct clients, exactly C
ActivityEvent records SHALL be emitted, each with:
  - event_type='system'
  - correct client_id
  - metadata.action='stale_draft_expiry'
  - integer counts (drafts_expired_count, approved_expired_count,
    pending_expired_count, tasks_cancelled_count)
  - a list of distinct avatar UUID strings
  - a message matching the pattern "Expired {N} stale draft(s) for {M} avatar(s)"
  where N equals drafts_expired_count and M equals len(distinct avatar_ids)

Feature: stale-draft-expiry, Property 6: Activity Event Per-Client Grouping
"""

import re
import uuid
from unittest.mock import MagicMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.draft_expiry import (
    DraftExpiry,
    DraftExpiryResult,
    DraftExpiryService,
)


# --- Strategies ---

avatar_id_strategy = st.builds(uuid.uuid4)
client_id_strategy = st.builds(uuid.uuid4)


@st.composite
def draft_expiry_strategy(draw):
    """Generate a random DraftExpiry with varying original_status and avatar_ids."""
    return DraftExpiry(
        draft_id=draw(st.builds(uuid.uuid4)),
        avatar_id=draw(avatar_id_strategy),
        client_id=draw(client_id_strategy),  # will be overridden by caller
        original_status=draw(st.sampled_from(["approved", "pending"])),
        age_hours=draw(st.integers(min_value=49, max_value=500)),
        slot_expired=draw(st.booleans()),
        tasks_cancelled=draw(st.integers(min_value=0, max_value=5)),
    )


@st.composite
def expiry_result_strategy(draw):
    """Generate a DraftExpiryResult with C distinct clients (1-10), each having 1-20 expired drafts."""
    num_clients = draw(st.integers(min_value=1, max_value=10))

    # Generate distinct client IDs
    client_ids = [uuid.uuid4() for _ in range(num_clients)]

    per_client: dict[uuid.UUID, list[DraftExpiry]] = {}

    for client_id in client_ids:
        num_drafts = draw(st.integers(min_value=1, max_value=20))
        # Generate a pool of avatar IDs for this client (1 to num_drafts distinct)
        num_avatars = draw(st.integers(min_value=1, max_value=max(1, num_drafts)))
        avatar_pool = [uuid.uuid4() for _ in range(num_avatars)]

        expiries = []
        for _ in range(num_drafts):
            avatar_id = draw(st.sampled_from(avatar_pool))
            expiry = DraftExpiry(
                draft_id=uuid.uuid4(),
                avatar_id=avatar_id,
                client_id=client_id,
                original_status=draw(st.sampled_from(["approved", "pending"])),
                age_hours=draw(st.integers(min_value=49, max_value=500)),
                slot_expired=draw(st.booleans()),
                tasks_cancelled=draw(st.integers(min_value=0, max_value=5)),
            )
            expiries.append(expiry)

        per_client[client_id] = expiries

    # Compute totals
    all_expiries = [e for exps in per_client.values() for e in exps]
    total_expired = len(all_expiries)
    approved_expired = sum(1 for e in all_expiries if e.original_status == "approved")
    pending_expired = sum(1 for e in all_expiries if e.original_status == "pending")
    tasks_cancelled = sum(e.tasks_cancelled for e in all_expiries)

    result = DraftExpiryResult(
        total_expired=total_expired,
        approved_expired=approved_expired,
        pending_expired=pending_expired,
        tasks_cancelled=tasks_cancelled,
        per_client=per_client,
        batch_errors=[],
        duration_ms=draw(st.integers(min_value=10, max_value=5000)),
    )

    return result


# --- Property Test ---

MESSAGE_PATTERN = re.compile(r"^Expired (\d+) stale draft\(s\) for (\d+) avatar\(s\)$")


@settings(max_examples=100, deadline=None)
@given(result=expiry_result_strategy())
def test_activity_event_per_client_grouping(result: DraftExpiryResult):
    """Property 6: Activity Event Per-Client Grouping.

    **Validates: Requirements 5.1, 5.2, 5.3, 5.5**

    For any expiry run that expires drafts for C distinct clients, exactly C
    ActivityEvent records are emitted, each with correct structure and metadata.
    """
    service = DraftExpiryService()
    db = MagicMock()

    num_clients = len(result.per_client)

    with patch("app.services.draft_expiry.record_activity_event") as mock_record:
        service._emit_activity_events(db, result)

        # Assert: record_activity_event was called exactly C times (once per client)
        assert mock_record.call_count == num_clients, (
            f"Expected {num_clients} calls to record_activity_event, "
            f"got {mock_record.call_count}"
        )

        # Collect all calls keyed by client_id for verification
        calls_by_client: dict[uuid.UUID, dict] = {}
        for call in mock_record.call_args_list:
            # record_activity_event(db, event_type=..., message=..., client_id=..., metadata=...)
            kwargs = call.kwargs if call.kwargs else {}
            args = call.args if call.args else ()

            # The function is called with positional db, then keyword args
            call_db = args[0] if args else kwargs.get("db")
            event_type = kwargs.get("event_type", args[1] if len(args) > 1 else None)
            message = kwargs.get("message", args[2] if len(args) > 2 else None)
            client_id = kwargs.get("client_id", args[3] if len(args) > 3 else None)
            metadata = kwargs.get("metadata", args[4] if len(args) > 4 else None)

            # Assert: each call had event_type='system'
            assert event_type == "system", (
                f"Expected event_type='system', got '{event_type}'"
            )

            # Assert: client_id is present and is one of our expected clients
            assert client_id is not None, "client_id must not be None"
            assert client_id in result.per_client, (
                f"Unexpected client_id {client_id} not in expected clients"
            )

            calls_by_client[client_id] = {
                "message": message,
                "metadata": metadata,
            }

        # Assert: each distinct client received exactly one call
        assert len(calls_by_client) == num_clients, (
            f"Expected calls for {num_clients} distinct clients, "
            f"got {len(calls_by_client)}"
        )

        # Verify each client's event metadata and message
        for client_id, expiries in result.per_client.items():
            assert client_id in calls_by_client, (
                f"No activity event emitted for client {client_id}"
            )

            call_data = calls_by_client[client_id]
            metadata = call_data["metadata"]
            message = call_data["message"]

            # Expected values for this client
            n = len(expiries)
            distinct_avatar_ids = list({str(e.avatar_id) for e in expiries})
            m = len(distinct_avatar_ids)
            a = sum(1 for e in expiries if e.original_status == "approved")
            p = sum(1 for e in expiries if e.original_status == "pending")
            t = sum(e.tasks_cancelled for e in expiries)

            # Assert: metadata contains action='stale_draft_expiry'
            assert metadata is not None, "metadata must not be None"
            assert metadata.get("action") == "stale_draft_expiry", (
                f"Expected metadata.action='stale_draft_expiry', "
                f"got '{metadata.get('action')}'"
            )

            # Assert: drafts_expired_count is integer and correct
            assert isinstance(metadata.get("drafts_expired_count"), int), (
                f"drafts_expired_count must be int, "
                f"got {type(metadata.get('drafts_expired_count'))}"
            )
            assert metadata["drafts_expired_count"] == n, (
                f"Expected drafts_expired_count={n}, "
                f"got {metadata['drafts_expired_count']}"
            )

            # Assert: approved_expired_count is integer and correct
            assert isinstance(metadata.get("approved_expired_count"), int), (
                f"approved_expired_count must be int, "
                f"got {type(metadata.get('approved_expired_count'))}"
            )
            assert metadata["approved_expired_count"] == a, (
                f"Expected approved_expired_count={a}, "
                f"got {metadata['approved_expired_count']}"
            )

            # Assert: pending_expired_count is integer and correct
            assert isinstance(metadata.get("pending_expired_count"), int), (
                f"pending_expired_count must be int, "
                f"got {type(metadata.get('pending_expired_count'))}"
            )
            assert metadata["pending_expired_count"] == p, (
                f"Expected pending_expired_count={p}, "
                f"got {metadata['pending_expired_count']}"
            )

            # Assert: tasks_cancelled_count is integer and correct
            assert isinstance(metadata.get("tasks_cancelled_count"), int), (
                f"tasks_cancelled_count must be int, "
                f"got {type(metadata.get('tasks_cancelled_count'))}"
            )
            assert metadata["tasks_cancelled_count"] == t, (
                f"Expected tasks_cancelled_count={t}, "
                f"got {metadata['tasks_cancelled_count']}"
            )

            # Assert: avatar_ids is a list of strings
            avatar_ids_in_metadata = metadata.get("avatar_ids")
            assert isinstance(avatar_ids_in_metadata, list), (
                f"avatar_ids must be a list, got {type(avatar_ids_in_metadata)}"
            )
            assert all(isinstance(aid, str) for aid in avatar_ids_in_metadata), (
                "All avatar_ids must be strings"
            )

            # Assert: avatar_ids are distinct
            assert len(avatar_ids_in_metadata) == len(set(avatar_ids_in_metadata)), (
                "avatar_ids must be distinct"
            )

            # Assert: avatar_ids count matches expected distinct avatars
            assert len(avatar_ids_in_metadata) == m, (
                f"Expected {m} distinct avatar_ids, "
                f"got {len(avatar_ids_in_metadata)}"
            )

            # Assert: all avatar_ids in metadata are valid UUIDs from this client's expiries
            expected_avatar_id_strings = {str(e.avatar_id) for e in expiries}
            actual_avatar_id_strings = set(avatar_ids_in_metadata)
            assert actual_avatar_id_strings == expected_avatar_id_strings, (
                f"avatar_ids mismatch: expected {expected_avatar_id_strings}, "
                f"got {actual_avatar_id_strings}"
            )

            # Assert: message matches pattern "Expired {N} stale draft(s) for {M} avatar(s)"
            match = MESSAGE_PATTERN.match(message)
            assert match is not None, (
                f"Message '{message}' does not match pattern "
                f"'Expired {{N}} stale draft(s) for {{M}} avatar(s)'"
            )

            # Assert: N in message equals drafts_expired_count
            message_n = int(match.group(1))
            assert message_n == n, (
                f"Message N={message_n} does not match "
                f"drafts_expired_count={n}"
            )

            # Assert: M in message equals len(distinct avatar_ids)
            message_m = int(match.group(2))
            assert message_m == m, (
                f"Message M={message_m} does not match "
                f"distinct avatar count={m}"
            )
