"""Property-based tests for LLM Context Isolation.

Tests Property 6: Every item in assembled context belongs to target client_id.

Creates multi-client test data, invokes context assembly for one client,
and asserts no cross-contamination occurs.

Uses Hypothesis to generate random client_ids, avatar configurations,
and context items (EditRecords, CorrectionPatterns, StrategyDocuments).

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.6**
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.services.generation import _assert_context_isolation
from app.services.isolation import _avatar_accessible_by_client


# ---------------------------------------------------------------------------
# Data classes for test objects (lightweight mocks without DB dependency)
# ---------------------------------------------------------------------------


@dataclass
class FakeClient:
    """Minimal Client object for isolation testing."""

    id: uuid.UUID
    client_name: str = "TestClient"
    brand_name: str = "TestBrand"
    is_active: bool = True


@dataclass
class FakeAvatar:
    """Minimal Avatar object for isolation testing."""

    id: uuid.UUID
    reddit_username: str = "test_avatar"
    client_ids: list[str] = field(default_factory=list)
    is_farm_avatar: bool = False


@dataclass
class FakeEditRecord:
    """Minimal EditRecord mock for isolation testing."""

    id: uuid.UUID
    client_id: uuid.UUID
    avatar_id: uuid.UUID
    subreddit: str = "r/test"
    engagement_mode: str = "helpful"
    ai_draft: str = "AI generated text"
    edited_draft: Optional[str] = None
    edit_summary: Optional[str] = None
    final_status: str = "approved"
    is_archived: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FakeCorrectionPattern:
    """Minimal CorrectionPattern mock for isolation testing."""

    id: uuid.UUID
    client_id: uuid.UUID
    avatar_id: uuid.UUID
    pattern_type: str = "tone_shift"
    rule_text: str = "Be more casual"
    frequency: int = 3
    last_seen_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class FakeStrategyDocument:
    """Minimal StrategyDocument mock for isolation testing."""

    id: uuid.UUID
    avatar_id: uuid.UUID
    document_md: str = "Strategy content"
    is_current: bool = True
    is_approved: bool = True


@dataclass
class FakeAvatarRental:
    """Minimal AvatarRental mock for isolation testing."""

    id: uuid.UUID
    avatar_id: uuid.UUID
    client_id: uuid.UUID
    is_active: bool = True
    expires_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Hypothesis Strategies
# ---------------------------------------------------------------------------

uuid_strategy = st.uuids()

# Generate a random subreddit name
subreddit_strategy = st.text(
    min_size=3, max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_")
).map(lambda s: f"r/{s}")

# Generate a random engagement mode
engagement_mode_strategy = st.sampled_from([
    "helpful", "cynical_deconstruction", "reframe_drop",
    "personal_anecdote", "contrarian_insight",
])

# Generate a random pattern type
pattern_type_strategy = st.sampled_from([
    "length_adjustment", "tone_shift", "vocabulary_change",
    "structure_change", "content_removal", "content_addition",
])

# Generate a random final status
final_status_strategy = st.sampled_from(["approved", "approved_unchanged", "rejected"])


@st.composite
def multi_client_scenario(draw):
    """Generate a scenario with 2+ clients, each with avatars and context data.

    Returns a dict with:
    - clients: list of FakeClient
    - avatars: dict mapping client_id -> list of FakeAvatar
    - edit_records: dict mapping client_id -> list of FakeEditRecord
    - correction_patterns: dict mapping client_id -> list of FakeCorrectionPattern
    - strategies: dict mapping client_id -> list of FakeStrategyDocument
    """
    num_clients = draw(st.integers(min_value=2, max_value=4))

    clients = []
    avatars = {}
    edit_records = {}
    correction_patterns = {}
    strategies = {}

    for i in range(num_clients):
        client_id = draw(uuid_strategy)
        client = FakeClient(id=client_id, client_name=f"Client_{i}")
        clients.append(client)

        # Generate 1-3 avatars per client
        num_avatars = draw(st.integers(min_value=1, max_value=3))
        client_avatars = []
        for _ in range(num_avatars):
            avatar_id = draw(uuid_strategy)
            username = draw(st.text(min_size=3, max_size=15, alphabet=st.characters(whitelist_categories=("L", "N"))))
            avatar = FakeAvatar(
                id=avatar_id,
                reddit_username=username,
                client_ids=[str(client_id)],
            )
            client_avatars.append(avatar)
        avatars[client_id] = client_avatars

        # Generate 0-5 edit records per client
        num_records = draw(st.integers(min_value=0, max_value=5))
        client_records = []
        for _ in range(num_records):
            record = FakeEditRecord(
                id=draw(uuid_strategy),
                client_id=client_id,
                avatar_id=client_avatars[0].id,
                subreddit=draw(subreddit_strategy),
                engagement_mode=draw(engagement_mode_strategy),
                final_status=draw(final_status_strategy),
            )
            client_records.append(record)
        edit_records[client_id] = client_records

        # Generate 0-3 correction patterns per client
        num_patterns = draw(st.integers(min_value=0, max_value=3))
        client_patterns = []
        for _ in range(num_patterns):
            pattern = FakeCorrectionPattern(
                id=draw(uuid_strategy),
                client_id=client_id,
                avatar_id=client_avatars[0].id,
                pattern_type=draw(pattern_type_strategy),
                rule_text=draw(st.text(min_size=5, max_size=50, alphabet=st.characters(whitelist_categories=("L", "N", "Z")))),
                frequency=draw(st.integers(min_value=1, max_value=20)),
            )
            client_patterns.append(pattern)
        correction_patterns[client_id] = client_patterns

        # Generate 0-1 strategy per client (per avatar)
        has_strategy = draw(st.booleans())
        client_strategies = []
        if has_strategy and client_avatars:
            strategy = FakeStrategyDocument(
                id=draw(uuid_strategy),
                avatar_id=client_avatars[0].id,
            )
            client_strategies.append(strategy)
        strategies[client_id] = client_strategies

    return {
        "clients": clients,
        "avatars": avatars,
        "edit_records": edit_records,
        "correction_patterns": correction_patterns,
        "strategies": strategies,
    }


# ---------------------------------------------------------------------------
# Property 6: Every item in assembled context belongs to target client_id
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(scenario=multi_client_scenario())
def test_property_6_assert_context_isolation_passes_for_correct_data(scenario):
    """**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6**

    For any client C with avatars, edit records, correction patterns, and strategy
    documents all belonging to C, _assert_context_isolation SHALL NOT raise.
    """
    for client in scenario["clients"]:
        client_id = client.id
        client_avatars = scenario["avatars"][client_id]
        client_examples = scenario["edit_records"][client_id]
        client_patterns = scenario["correction_patterns"][client_id]
        client_strategies = scenario["strategies"][client_id]

        # Pick the first avatar for this client
        avatar = client_avatars[0]
        strategy = client_strategies[0] if client_strategies else None

        # Should NOT raise — all data belongs to the target client
        _assert_context_isolation(
            client=client,
            avatar=avatar,
            strategy=strategy,
            examples=client_examples,
            patterns=client_patterns,
        )


@settings(max_examples=200)
@given(scenario=multi_client_scenario())
def test_property_6_assert_context_isolation_raises_on_cross_client_edit_record(scenario):
    """**Validates: Requirements 5.3, 5.5, 5.6, 9.6**

    For any client C, if an EditRecord belonging to a different client D is included
    in the context, _assert_context_isolation SHALL raise RuntimeError.
    """
    # Need at least 2 clients
    clients = scenario["clients"]
    assume(len(clients) >= 2)

    target_client = clients[0]
    other_client = clients[1]

    # Ensure the other client has at least one edit record
    other_records = scenario["edit_records"][other_client.id]
    assume(len(other_records) > 0)

    target_avatars = scenario["avatars"][target_client.id]
    avatar = target_avatars[0]

    # Inject one record from the other client into target's context
    contaminated_examples = list(scenario["edit_records"][target_client.id]) + [other_records[0]]

    try:
        _assert_context_isolation(
            client=target_client,
            avatar=avatar,
            strategy=None,
            examples=contaminated_examples,
            patterns=scenario["correction_patterns"][target_client.id],
        )
        # If we get here, isolation was NOT enforced — that's a failure
        assert False, (
            f"_assert_context_isolation did not raise for cross-client EditRecord. "
            f"Target client: {target_client.id}, contaminating record client: {other_client.id}"
        )
    except RuntimeError:
        pass  # Expected — isolation correctly detected


@settings(max_examples=200)
@given(scenario=multi_client_scenario())
def test_property_6_assert_context_isolation_raises_on_cross_client_correction_pattern(scenario):
    """**Validates: Requirements 5.3, 5.5, 5.6, 9.6**

    For any client C, if a CorrectionPattern belonging to a different client D is
    included in the context, _assert_context_isolation SHALL raise RuntimeError.
    """
    clients = scenario["clients"]
    assume(len(clients) >= 2)

    target_client = clients[0]
    other_client = clients[1]

    # Ensure the other client has at least one correction pattern
    other_patterns = scenario["correction_patterns"][other_client.id]
    assume(len(other_patterns) > 0)

    target_avatars = scenario["avatars"][target_client.id]
    avatar = target_avatars[0]

    # Inject one pattern from the other client into target's context
    contaminated_patterns = list(scenario["correction_patterns"][target_client.id]) + [other_patterns[0]]

    try:
        _assert_context_isolation(
            client=target_client,
            avatar=avatar,
            strategy=None,
            examples=scenario["edit_records"][target_client.id],
            patterns=contaminated_patterns,
        )
        assert False, (
            f"_assert_context_isolation did not raise for cross-client CorrectionPattern. "
            f"Target client: {target_client.id}, contaminating pattern client: {other_client.id}"
        )
    except RuntimeError:
        pass  # Expected — isolation correctly detected


@settings(max_examples=200)
@given(scenario=multi_client_scenario())
def test_property_6_assert_context_isolation_raises_on_cross_client_strategy(scenario):
    """**Validates: Requirements 5.2, 5.6, 9.6**

    For any client C, if a strategy document is loaded for an avatar that does NOT
    belong to client C, _assert_context_isolation SHALL raise RuntimeError.
    """
    clients = scenario["clients"]
    assume(len(clients) >= 2)

    target_client = clients[0]
    other_client = clients[1]

    # Ensure the other client has at least one avatar with a strategy
    other_strategies = scenario["strategies"][other_client.id]
    assume(len(other_strategies) > 0)

    # Use an avatar from the OTHER client (not owned by target)
    other_avatar = scenario["avatars"][other_client.id][0]
    assume(str(target_client.id) not in other_avatar.client_ids)

    try:
        _assert_context_isolation(
            client=target_client,
            avatar=other_avatar,  # Avatar not owned by target client
            strategy=other_strategies[0],
            examples=[],
            patterns=[],
        )
        assert False, (
            f"_assert_context_isolation did not raise for cross-client strategy. "
            f"Target client: {target_client.id}, avatar owner: {other_client.id}"
        )
    except RuntimeError:
        pass  # Expected — isolation correctly detected


# ---------------------------------------------------------------------------
# Avatar accessibility checks (ownership + rental)
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    client_id=uuid_strategy,
    avatar_id=uuid_strategy,
)
def test_avatar_accessible_by_client_owned(client_id, avatar_id):
    """**Validates: Requirements 5.2, 5.7**

    For any avatar whose client_ids contains the target client_id,
    _avatar_accessible_by_client SHALL return True.
    """
    client = FakeClient(id=client_id)
    avatar = FakeAvatar(id=avatar_id, client_ids=[str(client_id)])

    # Mock the DB session — no rental query needed since ownership check passes first
    mock_db = MagicMock()

    result = _avatar_accessible_by_client(mock_db, avatar, client)
    assert result is True, (
        f"Avatar with client_ids containing {client_id} should be accessible"
    )


@settings(max_examples=200)
@given(
    client_id=uuid_strategy,
    other_client_id=uuid_strategy,
    avatar_id=uuid_strategy,
)
def test_avatar_not_accessible_by_unrelated_client(client_id, other_client_id, avatar_id):
    """**Validates: Requirements 5.2, 5.6**

    For any avatar whose client_ids does NOT contain the target client_id
    and has no active rental, _avatar_accessible_by_client SHALL return False.
    """
    assume(client_id != other_client_id)

    client = FakeClient(id=client_id)
    avatar = FakeAvatar(id=avatar_id, client_ids=[str(other_client_id)])

    # Mock DB session — rental query returns None (no rental)
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = None

    result = _avatar_accessible_by_client(mock_db, avatar, client)
    assert result is False, (
        f"Avatar owned by {other_client_id} should NOT be accessible by {client_id} "
        f"without an active rental"
    )


@settings(max_examples=200)
@given(
    client_id=uuid_strategy,
    other_client_id=uuid_strategy,
    avatar_id=uuid_strategy,
    rental_id=uuid_strategy,
)
def test_avatar_accessible_via_active_rental(client_id, other_client_id, avatar_id, rental_id):
    """**Validates: Requirements 5.7**

    For any avatar NOT owned by the client but with an active rental record,
    _avatar_accessible_by_client SHALL return True.
    """
    assume(client_id != other_client_id)

    client = FakeClient(id=client_id)
    avatar = FakeAvatar(id=avatar_id, client_ids=[str(other_client_id)])

    # Mock DB session — rental query returns an active rental
    mock_rental = FakeAvatarRental(
        id=rental_id,
        avatar_id=avatar_id,
        client_id=client_id,
        is_active=True,
        expires_at=None,
    )
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_db.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = mock_rental

    result = _avatar_accessible_by_client(mock_db, avatar, client)
    assert result is True, (
        f"Avatar with active rental to {client_id} should be accessible"
    )


# ---------------------------------------------------------------------------
# Learning service post-load assertion simulation
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(scenario=multi_client_scenario())
def test_property_6_no_cross_contamination_in_full_context_assembly(scenario):
    """**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 9.6**

    For any multi-client scenario, assembling context for one client using only
    that client's data SHALL pass isolation checks. Mixing in any other client's
    data SHALL be detected.

    This test simulates the full context assembly flow:
    1. Select target client
    2. Gather only target client's data
    3. Verify _assert_context_isolation passes
    4. Then verify that adding ANY single item from another client causes failure
    """
    clients = scenario["clients"]
    assume(len(clients) >= 2)

    target_client = clients[0]
    target_avatars = scenario["avatars"][target_client.id]
    avatar = target_avatars[0]

    target_examples = scenario["edit_records"][target_client.id]
    target_patterns = scenario["correction_patterns"][target_client.id]
    target_strategies = scenario["strategies"][target_client.id]
    strategy = target_strategies[0] if target_strategies else None

    # Step 1: Clean context passes
    _assert_context_isolation(
        client=target_client,
        avatar=avatar,
        strategy=strategy,
        examples=target_examples,
        patterns=target_patterns,
    )

    # Step 2: Any single cross-client item causes failure
    for other_client in clients[1:]:
        other_records = scenario["edit_records"][other_client.id]
        other_patterns = scenario["correction_patterns"][other_client.id]

        # Test cross-client edit record injection
        if other_records:
            try:
                _assert_context_isolation(
                    client=target_client,
                    avatar=avatar,
                    strategy=strategy,
                    examples=target_examples + [other_records[0]],
                    patterns=target_patterns,
                )
                assert False, (
                    f"Cross-client EditRecord from {other_client.id} was not detected "
                    f"in context for {target_client.id}"
                )
            except RuntimeError:
                pass  # Correctly detected

        # Test cross-client correction pattern injection
        if other_patterns:
            try:
                _assert_context_isolation(
                    client=target_client,
                    avatar=avatar,
                    strategy=strategy,
                    examples=target_examples,
                    patterns=target_patterns + [other_patterns[0]],
                )
                assert False, (
                    f"Cross-client CorrectionPattern from {other_client.id} was not detected "
                    f"in context for {target_client.id}"
                )
            except RuntimeError:
                pass  # Correctly detected
