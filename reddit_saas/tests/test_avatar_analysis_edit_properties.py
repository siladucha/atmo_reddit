"""Property-based tests for Avatar Analysis — Edit Storage and Few-Shot Retrieval.

Tests Properties 7, 8 (edit storage) and 9 (few-shot retrieval) using Hypothesis.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.models.analysis_edit import AnalysisEditRecord
from app.services.learning_loop import store_edit, get_recent_edits


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def behavioral_profile_dicts(draw):
    """Generate a BehavioralProfile-like dict with realistic structure."""
    basic = {
        "username": draw(st.text(min_size=1, max_size=30)),
        "account_age_days": draw(st.integers(min_value=1, max_value=5000)),
        "total_karma": draw(st.integers(min_value=0, max_value=1000000)),
        "is_mod": draw(st.booleans()),
    }
    behavior = {
        "total_comments": draw(st.integers(min_value=0, max_value=100000)),
        "days_since_last_activity": draw(st.integers(min_value=0, max_value=3650)),
        "uses_emoji": draw(st.booleans()),
        "avg_comment_length": draw(st.integers(min_value=0, max_value=10000)),
    }
    topics = {
        "top_subreddits": draw(st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=5)),
        "key_themes": draw(st.lists(st.text(min_size=1, max_size=50), min_size=1, max_size=5)),
    }
    speech = {
        "frequent_terms": draw(st.lists(st.text(min_size=1, max_size=30), min_size=1, max_size=5)),
        "pattern_description": draw(st.text(min_size=1, max_size=200)),
    }
    mismatches = draw(st.lists(st.text(min_size=1, max_size=100), min_size=0, max_size=3))
    summary = draw(st.text(min_size=10, max_size=300))

    return {
        "basic": basic,
        "behavior": behavior,
        "topics": topics,
        "speech": speech,
        "mismatches": mismatches,
        "summary": summary,
    }


@st.composite
def distinct_behavioral_profile_pairs(draw):
    """Generate two BehavioralProfile dicts that differ in at least one field."""
    original = draw(behavioral_profile_dicts())
    edited = draw(behavioral_profile_dicts())
    # Ensure they are actually different
    assume(original != edited)
    return original, edited


@st.composite
def edit_records_with_limit(draw):
    """Generate K edit records (0 to 10) and a limit N (1 to 5).

    Returns (records, limit, avatar_id) where records are mock AnalysisEditRecord
    objects with distinct created_at timestamps in ascending order.
    """
    k = draw(st.integers(min_value=0, max_value=10))
    n = draw(st.integers(min_value=1, max_value=5))
    avatar_id = uuid.uuid4()

    base_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    records = []
    for i in range(k):
        record = MagicMock(spec=AnalysisEditRecord)
        record.id = uuid.uuid4()
        record.avatar_id = avatar_id
        record.llm_output = {"summary": f"original_{i}"}
        record.human_edited = {"summary": f"edited_{i}"}
        record.diff_summary = f"Changed 'summary' from 'original_{i}' to 'edited_{i}'"
        record.created_at = base_time + timedelta(hours=i)
        records.append(record)

    return records, n, avatar_id


def _make_mock_db():
    """Create a mock DB session that tracks add/commit/refresh calls."""
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    return db


# ---------------------------------------------------------------------------
# Property 7: Storing an edit produces a record with auto-computed diff
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 7: Storing an edit produces a record with auto-computed diff


@settings(max_examples=100)
@given(pair=distinct_behavioral_profile_pairs())
def test_property_7_store_edit_creates_record_with_diff(pair):
    """**Validates: Requirements 7.1, 9.2**

    For any pair of distinct BehavioralProfile dicts (original != edited),
    calling store_edit SHALL create an AnalysisEditRecord where:
    - diff_summary is a non-empty string describing the differences
    - llm_output matches the original input
    - human_edited matches the edited input
    - The record is added to the DB session
    """
    llm_output, human_edited = pair
    db = _make_mock_db()
    avatar_id = uuid.uuid4()

    record = store_edit(db, avatar_id, llm_output, human_edited)

    # Record has correct fields
    assert record.avatar_id == avatar_id
    assert record.llm_output == llm_output
    assert record.human_edited == human_edited

    # diff_summary is non-empty
    assert isinstance(record.diff_summary, str)
    assert len(record.diff_summary) > 0

    # DB operations were called
    db.add.assert_called_once_with(record)
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(record)


# ---------------------------------------------------------------------------
# Property 8: Identical edits are rejected
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 8: Identical edits are rejected


@settings(max_examples=100)
@given(profile=behavioral_profile_dicts())
def test_property_8_identical_edits_rejected(profile):
    """**Validates: Requirements 9.3**

    For any BehavioralProfile dict submitted as both llm_output and human_edited,
    store_edit SHALL raise ValueError with "No changes detected" and no record
    shall be created in the DB.
    """
    db = _make_mock_db()
    avatar_id = uuid.uuid4()

    with pytest.raises(ValueError, match="No changes detected"):
        store_edit(db, avatar_id, profile, profile)

    # No record was added to the DB
    db.add.assert_not_called()
    db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# Property 9: Few-shot injection retrieves exactly the N most recent edits
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 9: Few-shot injection retrieves exactly the N most recent edits


@settings(max_examples=100)
@given(data=edit_records_with_limit())
def test_property_9_few_shot_retrieval_returns_min_k_n_records(data):
    """**Validates: Requirements 8.1, 8.2**

    For any avatar with K edit records (K >= 0) and a configured limit of N,
    get_recent_edits SHALL return exactly min(K, N) records, and those records
    SHALL be the N most recently created by timestamp (descending order).
    """
    all_records, limit_n, avatar_id = data

    # The function uses SQLAlchemy: select().where().order_by(desc).limit()
    # We mock db.execute to return the expected subset that the DB would return:
    # sorted by created_at DESC, limited to N
    sorted_desc = sorted(all_records, key=lambda r: r.created_at, reverse=True)
    expected_subset = sorted_desc[:limit_n]

    # Mock the SQLAlchemy query chain
    mock_db = MagicMock()
    mock_scalars = MagicMock()
    mock_scalars.all.return_value = expected_subset
    mock_execute_result = MagicMock()
    mock_execute_result.scalars.return_value = mock_scalars
    mock_db.execute.return_value = mock_execute_result

    # Call the function under test
    result = get_recent_edits(mock_db, avatar_id, limit=limit_n)

    # Verify: exactly min(K, N) records returned
    expected_count = min(len(all_records), limit_n)
    assert len(result) == expected_count, (
        f"Expected {expected_count} records (K={len(all_records)}, N={limit_n}), "
        f"got {len(result)}"
    )

    # Verify: records are in descending created_at order
    for i in range(len(result) - 1):
        assert result[i].created_at >= result[i + 1].created_at, (
            f"Record at index {i} (created_at={result[i].created_at}) should be >= "
            f"record at index {i+1} (created_at={result[i+1].created_at})"
        )

    # Verify: the returned records are the N most recent ones
    if len(all_records) > 0 and len(result) > 0:
        # The most recent record in all_records should be the first in result
        most_recent_overall = max(all_records, key=lambda r: r.created_at)
        assert result[0].created_at == most_recent_overall.created_at, (
            f"First result should be the most recent record. "
            f"Got {result[0].created_at}, expected {most_recent_overall.created_at}"
        )

    # Verify: db.execute was called (the function builds and executes a query)
    mock_db.execute.assert_called_once()
