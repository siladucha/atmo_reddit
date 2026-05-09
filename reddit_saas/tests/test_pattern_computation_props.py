"""Property-based tests for Pattern Computation Threshold and Limit.

Tests Property 7: get_correction_patterns returns empty list when fewer than 5
qualifying records exist, and at most 3 patterns when 5+ exist.

Uses Hypothesis with mocked database session.
"""

# Feature: self-learning-loop, Property 7: get_correction_patterns returns empty list when fewer than 5 qualifying records exist, and at most 3 patterns when 5+ exist

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.services.learning import LearningService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Number of qualifying edit records (approved with non-null edit_summary, non-archived)
qualifying_record_count = st.integers(min_value=0, max_value=50)

# Number of correction patterns stored in DB for this avatar-client pair
stored_pattern_count = st.integers(min_value=0, max_value=10)

# Pattern types
pattern_types = st.sampled_from([
    "length_adjustment",
    "tone_shift",
    "vocabulary_change",
    "structure_change",
    "content_removal",
    "content_addition",
])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_patterns(count: int, avatar_id: uuid.UUID, client_id: uuid.UUID) -> list:
    """Create a list of mock CorrectionPattern objects sorted by frequency descending."""
    patterns = []
    for i in range(count):
        pattern = MagicMock(spec=CorrectionPattern)
        pattern.id = uuid.uuid4()
        pattern.avatar_id = avatar_id
        pattern.client_id = client_id
        pattern.pattern_type = [
            "length_adjustment", "tone_shift", "vocabulary_change",
            "structure_change", "content_removal", "content_addition",
        ][i % 6]
        pattern.rule_text = f"Rule text for pattern {i}"[:100]
        pattern.frequency = count - i  # Descending frequency
        pattern.last_seen_at = datetime.now(timezone.utc)
        patterns.append(pattern)
    return patterns


def make_mock_db_for_get_patterns(
    qualifying_count: int,
    patterns: list,
):
    """Create a mock database session for get_correction_patterns.

    The mock simulates:
    1. A count query for qualifying edit records (approved, non-archived, with edit_summary)
    2. A query for CorrectionPattern objects ordered by frequency desc, limited to 3
    """
    db = MagicMock()

    # We need to handle two different db.query() calls:
    # 1. db.query(func.count(EditRecord.id)).filter(...).scalar() -> qualifying_count
    # 2. db.query(CorrectionPattern).filter(...).order_by(...).limit(3).all() -> patterns[:3]

    # Track call count to differentiate between the two queries
    call_count = {"value": 0}

    def mock_query(model):
        call_count["value"] += 1
        mock_q = MagicMock()

        if call_count["value"] == 1:
            # First call: count query for qualifying edit records
            mock_q.filter.return_value = mock_q
            mock_q.scalar.return_value = qualifying_count
        else:
            # Second call: pattern query
            mock_q.filter.return_value = mock_q
            mock_q.order_by.return_value = mock_q
            mock_q.limit.return_value = mock_q
            mock_q.all.return_value = patterns[:3]

        return mock_q

    db.query.side_effect = mock_query
    return db


# ---------------------------------------------------------------------------
# Property 7: Pattern computation threshold and limit
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    qualifying_count=qualifying_record_count,
    num_patterns=stored_pattern_count,
)
def test_property_7_pattern_threshold_and_limit(
    qualifying_count: int,
    num_patterns: int,
):
    """**Validates: Requirements 2.5, 3.1**

    For any avatar-client pair, get_correction_patterns SHALL return an empty list
    when fewer than 5 qualifying edit records exist, and at most 3 patterns when
    5 or more exist.

    "Qualifying" means: non-archived, final_status="approved", edit_summary is not null.
    """
    avatar_id = uuid.uuid4()
    client_id = uuid.uuid4()

    # Create mock patterns (simulating what's stored in DB)
    patterns = make_mock_patterns(num_patterns, avatar_id, client_id)

    # Create mock DB
    db = make_mock_db_for_get_patterns(qualifying_count, patterns)

    # Call the method under test
    service = LearningService()
    result = service.get_correction_patterns(db, avatar_id, client_id)

    # Property assertions:
    # 1. When fewer than 5 qualifying records exist, result MUST be empty
    if qualifying_count < 5:
        assert result == [], (
            f"Expected empty list when qualifying_count={qualifying_count} < 5, "
            f"but got {len(result)} patterns"
        )

    # 2. When 5+ qualifying records exist, result MUST have at most 3 patterns
    if qualifying_count >= 5:
        assert len(result) <= 3, (
            f"Expected at most 3 patterns when qualifying_count={qualifying_count} >= 5, "
            f"but got {len(result)} patterns"
        )

    # 3. Result is always a list (never None or other type)
    assert isinstance(result, list)


@settings(max_examples=100)
@given(
    num_patterns=st.integers(min_value=4, max_value=10),
)
def test_property_7_limit_enforced_with_many_patterns(
    num_patterns: int,
):
    """**Validates: Requirements 2.5, 3.1**

    When 5+ qualifying records exist and more than 3 patterns are stored,
    get_correction_patterns SHALL still return at most 3 patterns.
    """
    avatar_id = uuid.uuid4()
    client_id = uuid.uuid4()

    # Always have enough qualifying records (>= 5)
    qualifying_count = max(5, num_patterns + 5)

    # Create more patterns than the limit
    patterns = make_mock_patterns(num_patterns, avatar_id, client_id)

    # Create mock DB
    db = make_mock_db_for_get_patterns(qualifying_count, patterns)

    # Call the method under test
    service = LearningService()
    result = service.get_correction_patterns(db, avatar_id, client_id)

    # Must return at most 3 regardless of how many patterns exist
    assert len(result) <= 3, (
        f"Expected at most 3 patterns but got {len(result)} "
        f"(stored {num_patterns} patterns in DB)"
    )

    # Result should not be empty since we have qualifying records and patterns
    assert len(result) > 0, (
        f"Expected non-empty result with {qualifying_count} qualifying records "
        f"and {num_patterns} stored patterns"
    )


@settings(max_examples=100)
@given(
    qualifying_count=st.integers(min_value=0, max_value=4),
)
def test_property_7_threshold_below_5_always_empty(
    qualifying_count: int,
):
    """**Validates: Requirements 2.5, 3.1**

    When fewer than 5 qualifying edit records exist, get_correction_patterns
    SHALL always return an empty list, regardless of how many patterns are stored.
    """
    avatar_id = uuid.uuid4()
    client_id = uuid.uuid4()

    # Even if patterns exist in DB, they should not be returned
    patterns = make_mock_patterns(5, avatar_id, client_id)

    # Create mock DB with below-threshold qualifying count
    db = make_mock_db_for_get_patterns(qualifying_count, patterns)

    # Call the method under test
    service = LearningService()
    result = service.get_correction_patterns(db, avatar_id, client_id)

    # Must always be empty when below threshold
    assert result == [], (
        f"Expected empty list when qualifying_count={qualifying_count} < 5, "
        f"but got {len(result)} patterns"
    )
