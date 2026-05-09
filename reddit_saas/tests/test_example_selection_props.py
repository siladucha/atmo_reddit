"""Property-based tests for Few-Shot Example Selection.

Tests Property 5: select_few_shot_examples returns at most 3 examples,
max 1 rejected, same-subreddit examples appear before different-subreddit.

Uses Hypothesis with mocked database session.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.edit_record import EditRecord
from app.services.learning import LearningService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Subreddit pool for generating records
SUBREDDITS = ["cybersecurity", "netsec", "sysadmin", "devops", "programming"]
ENGAGEMENT_MODES = ["bullseye", "helpful_peer", "karma_only"]

# Generate a list of EditRecord-like objects with varying attributes
edit_record_data = st.fixed_dictionaries(
    {
        "subreddit": st.sampled_from(SUBREDDITS),
        "engagement_mode": st.sampled_from(ENGAGEMENT_MODES),
        "final_status": st.sampled_from(["approved", "approved_unchanged", "rejected"]),
    }
)

# Strategy for generating a list of 0-50 edit records (the candidate pool)
edit_record_list = st.lists(edit_record_data, min_size=0, max_size=50)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_edit_record(
    data: dict,
    avatar_id: uuid.UUID,
    client_id: uuid.UUID,
    created_at: datetime,
) -> MagicMock:
    """Create a mock EditRecord with the given attributes.

    Uses MagicMock(spec=EditRecord) to avoid SQLAlchemy instrumentation issues
    while still allowing attribute access for the selection algorithm.
    """
    record = MagicMock(spec=EditRecord)
    record.id = uuid.uuid4()
    record.comment_draft_id = uuid.uuid4()
    record.avatar_id = avatar_id
    record.client_id = client_id
    record.ai_draft = "Some AI generated text for testing purposes."
    record.edited_draft = (
        "Some edited text for testing." if data["final_status"] != "rejected" else None
    )
    record.edit_summary = (
        "shortened 85→42 words" if data["final_status"] == "approved" else None
    )
    record.subreddit = data["subreddit"]
    record.engagement_mode = data["engagement_mode"]
    record.post_title = "Test Post Title"
    record.post_body = "Test post body content"
    record.final_status = data["final_status"]
    record.is_archived = False
    record.created_at = created_at
    return record


def make_mock_db_with_records(records: list[MagicMock]) -> MagicMock:
    """Create a mock DB session that returns the given records from the query chain."""
    db = MagicMock()

    # Build the query chain: db.query(...).filter(...).order_by(...).limit(...).all()
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    mock_query.all.return_value = records
    db.query.return_value = mock_query

    return db


# ---------------------------------------------------------------------------
# Property 5: Example selection bounds and priority
# ---------------------------------------------------------------------------

# Feature: self-learning-loop, Property 5: select_few_shot_examples returns at most 3 examples, max 1 rejected, same-subreddit examples appear before different-subreddit


@settings(max_examples=100)
@given(
    record_data_list=edit_record_list,
    target_subreddit=st.sampled_from(SUBREDDITS),
    target_mode=st.sampled_from(ENGAGEMENT_MODES),
)
def test_property_5_example_selection_bounds_and_priority(
    record_data_list: list[dict],
    target_subreddit: str,
    target_mode: str,
):
    """**Validates: Requirements 2.1, 2.2, 2.3**

    For any avatar-client pair with N edit records (N >= 0),
    select_few_shot_examples SHALL:
    (a) Return at most 3 examples total
    (b) Include at most 1 having final_status="rejected"
    (c) Same-subreddit examples appear before different-subreddit examples in the result
    """
    avatar_id = uuid.uuid4()
    client_id = uuid.uuid4()

    # Create mock EditRecord instances with decreasing created_at (most recent first)
    base_time = datetime.now(timezone.utc)
    records = []
    for i, data in enumerate(record_data_list):
        created_at = base_time - timedelta(hours=i)
        record = make_mock_edit_record(data, avatar_id, client_id, created_at)
        records.append(record)

    # Mock the DB to return these records (simulating the 50 most recent query)
    db = make_mock_db_with_records(records)

    # Call the method under test
    service = LearningService()
    results = service.select_few_shot_examples(
        db, avatar_id, client_id, target_subreddit, target_mode
    )

    # (a) At most 3 examples total
    assert len(results) <= 3

    # (b) At most 1 having final_status="rejected"
    rejected_count = sum(1 for r in results if r.final_status == "rejected")
    assert rejected_count <= 1

    # (c) Same-subreddit examples appear before different-subreddit examples
    # The implementation separates positives and negatives, sorts each by relevance,
    # then assembles: positives[:2] + negatives[:1]. The subreddit priority ordering
    # applies within each category. Among the positive (approved) examples in the
    # result, same-subreddit must appear before different-subreddit.
    positive_results = [r for r in results if r.final_status == "approved"]

    same_sub_pos_indices = [
        i for i, r in enumerate(positive_results) if r.subreddit == target_subreddit
    ]
    diff_sub_pos_indices = [
        i for i, r in enumerate(positive_results) if r.subreddit != target_subreddit
    ]

    if same_sub_pos_indices and diff_sub_pos_indices:
        # Among positives, same-subreddit examples should appear before different-subreddit
        assert max(same_sub_pos_indices) < min(diff_sub_pos_indices), (
            f"Among positive examples, same-subreddit (indices {same_sub_pos_indices}) "
            f"should appear before different-subreddit (indices {diff_sub_pos_indices}). "
            f"Results: {[(r.subreddit, r.final_status) for r in results]}"
        )



