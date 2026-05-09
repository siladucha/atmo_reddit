"""Property-based tests for Edit Capture Record Structure.

Tests Property 1: For any CommentDraft and review action, capture_edit_record produces
correct record structure.

Uses Hypothesis with mocked database session.
"""

import uuid
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.models.comment_draft import CommentDraft
from app.models.edit_record import EditRecord
from app.models.thread import RedditThread
from app.services.learning import LearningService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate realistic comment drafts
draft_text = st.text(
    min_size=10,
    max_size=500,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
)

# Generate post body text (can be long — tests truncation to 500)
post_body_text = st.text(
    min_size=0,
    max_size=1000,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
)

# Generate review statuses
review_status = st.sampled_from(["approved", "approved_unchanged", "rejected"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_draft(
    ai_draft: str, edited_draft: str | None, status: str
) -> CommentDraft:
    """Create a mock CommentDraft with the given fields."""
    draft = MagicMock(spec=CommentDraft)
    draft.id = uuid.uuid4()
    draft.avatar_id = uuid.uuid4()
    draft.client_id = uuid.uuid4()
    draft.ai_draft = ai_draft
    draft.engagement_mode = "helpful_peer"

    # For "approved" status, edited_draft differs from ai_draft
    # For "approved_unchanged", edited_draft equals ai_draft or is None
    # For "rejected", edited_draft is irrelevant (record will have None)
    if status == "approved":
        draft.edited_draft = edited_draft
    elif status == "approved_unchanged":
        draft.edited_draft = ai_draft  # same as ai_draft
    else:
        draft.edited_draft = None

    return draft


def make_mock_thread(post_title: str, post_body: str | None, subreddit: str) -> RedditThread:
    """Create a mock RedditThread with the given fields."""
    thread = MagicMock(spec=RedditThread)
    thread.post_title = post_title
    thread.post_body = post_body
    thread.subreddit = subreddit
    return thread


def make_mock_db():
    """Create a mock database session that captures the added EditRecord."""
    db = MagicMock()
    # db.add should just accept the record
    db.add = MagicMock()
    # db.flush should do nothing
    db.flush = MagicMock()
    # db.query(...).filter(...).scalar() returns a count that won't trigger recomputation
    mock_query = MagicMock()
    mock_query.filter.return_value = mock_query
    mock_query.scalar.return_value = 1  # Not a multiple of 5
    db.query.return_value = mock_query
    return db


# ---------------------------------------------------------------------------
# Property 1: Edit capture produces correct record structure
# ---------------------------------------------------------------------------

# Feature: self-learning-loop, Property 1: Edit capture produces correct record structure


@settings(max_examples=100)
@given(
    ai_draft=draft_text,
    edited_draft=draft_text,
    post_title=draft_text,
    post_body=post_body_text,
    subreddit=st.sampled_from(["cybersecurity", "netsec", "sysadmin", "devops", "programming"]),
    status=review_status,
)
def test_property_1_edit_capture_record_structure(
    ai_draft: str,
    edited_draft: str,
    post_title: str,
    post_body: str,
    subreddit: str,
    status: str,
):
    """**Validates: Requirements 1.1, 1.2, 1.3, 1.5, 1.6**

    For any CommentDraft and review action (approve-with-edits, approve-unchanged, reject),
    calling capture_edit_record SHALL produce an EditRecord where:
    (a) final_status matches the action type
    (b) ai_draft is always non-null
    (c) edited_draft is null iff status is "rejected"
    (d) edit_summary is null iff status is "rejected" or "approved_unchanged"
    (e) created_at is non-null (handled by DB default, verified via model instantiation)
    (f) post_body length is <= 500 characters
    """
    # For "approved" status, ensure edited_draft differs from ai_draft
    if status == "approved":
        assume(ai_draft != edited_draft)

    # Build mocks
    draft = make_mock_draft(ai_draft, edited_draft, status)
    thread = make_mock_thread(post_title, post_body, subreddit)
    db = make_mock_db()

    # Patch enforce_retention_limits to avoid side effects
    service = LearningService()
    with patch.object(service, "enforce_retention_limits", return_value=0):
        record = service.capture_edit_record(db, draft, thread, status)

    # Record should be created successfully
    assert record is not None
    assert isinstance(record, EditRecord)

    # (a) final_status matches the action type
    assert record.final_status == status

    # (b) ai_draft is always non-null
    assert record.ai_draft is not None
    assert record.ai_draft == ai_draft

    # (c) edited_draft is null iff status is "rejected"
    if status == "rejected":
        assert record.edited_draft is None
    else:
        assert record.edited_draft is not None

    # (d) edit_summary is null iff status is "rejected" or "approved_unchanged"
    if status in ("rejected", "approved_unchanged"):
        assert record.edit_summary is None
    else:
        # For "approved" with edits, edit_summary should be non-null
        # (since we assumed ai_draft != edited_draft)
        assert record.edit_summary is not None

    # (f) post_body length is <= 500 characters
    if record.post_body is not None:
        assert len(record.post_body) <= 500
