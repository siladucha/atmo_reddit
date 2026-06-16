"""Property-based tests for Generation Provenance Storage.

Tests Property 11: When learning context is used, CommentDraft.learning_metadata
contains IDs of used EditRecords and text of applied CorrectionPatterns.

Uses Hypothesis with mocked DB, LLM calls, and LearningService to test the
provenance storage logic in isolation.
"""

# Feature: self-learning-loop, Property 11: When learning context is used, CommentDraft.learning_metadata contains IDs of used EditRecords and text of applied CorrectionPatterns

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.models.thread import RedditThread
from app.services.generation import generate_comment


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate realistic text for drafts (non-empty, printable)
draft_text = st.text(
    min_size=5,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

# Rule text for correction patterns (non-empty, max 100 chars)
rule_text_strategy = st.text(
    min_size=3,
    max_size=100,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

# Pattern types
PATTERN_TYPES = [
    "length_adjustment",
    "tone_shift",
    "vocabulary_change",
    "structure_change",
    "content_removal",
    "content_addition",
]

# Strategy for generating a list of EditRecord-like data (1-3 examples)
edit_record_data_strategy = st.fixed_dictionaries(
    {
        "ai_draft": draft_text,
        "edited_draft": draft_text,
        "final_status": st.sampled_from(["approved", "rejected"]),
        "subreddit": st.sampled_from(["cybersecurity", "netsec", "sysadmin", "devops"]),
        "engagement_mode": st.sampled_from(["bullseye", "helpful_peer", "karma_only"]),
    }
)

# Non-empty list of edit records (at least 1 to ensure learning context is used)
edit_record_list_strategy = st.lists(edit_record_data_strategy, min_size=1, max_size=3)

# Strategy for correction pattern data (0-3 patterns)
correction_pattern_data_strategy = st.fixed_dictionaries(
    {
        "pattern_type": st.sampled_from(PATTERN_TYPES),
        "rule_text": rule_text_strategy,
        "frequency": st.integers(min_value=1, max_value=50),
    }
)

correction_pattern_list_strategy = st.lists(
    correction_pattern_data_strategy, min_size=0, max_size=3
)

# Strategy for persona selection data
persona_selection_strategy = st.fixed_dictionaries(
    {
        "mode": st.sampled_from(["bullseye", "helpful_peer", "karma_only"]),
        "thread_angle": draft_text,
        "pov_opportunity": st.one_of(draft_text, st.none()),
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_edit_record(data: dict) -> MagicMock:
    """Create a mock EditRecord with the given attributes."""
    record = MagicMock(spec=EditRecord)
    record.id = uuid.uuid4()
    record.avatar_id = uuid.uuid4()
    record.client_id = uuid.uuid4()
    record.ai_draft = data["ai_draft"]
    record.final_status = data["final_status"]
    record.subreddit = data["subreddit"]
    record.engagement_mode = data["engagement_mode"]
    record.created_at = datetime.now(timezone.utc)

    if data["final_status"] == "rejected":
        record.edited_draft = None
    else:
        record.edited_draft = data["edited_draft"]

    return record


def make_mock_correction_pattern(data: dict) -> MagicMock:
    """Create a mock CorrectionPattern with the given attributes."""
    pattern = MagicMock(spec=CorrectionPattern)
    pattern.id = uuid.uuid4()
    pattern.avatar_id = uuid.uuid4()
    pattern.client_id = uuid.uuid4()
    pattern.pattern_type = data["pattern_type"]
    pattern.rule_text = data["rule_text"]
    pattern.frequency = data["frequency"]
    pattern.last_seen_at = datetime.now(timezone.utc)
    return pattern


def make_mock_thread() -> MagicMock:
    """Create a mock RedditThread."""
    thread = MagicMock(spec=RedditThread)
    thread.id = uuid.uuid4()
    thread.subreddit = "cybersecurity"
    thread.post_title = "Test post title"
    thread.post_body = "Test post body"
    thread.comments_json = None
    thread.type = "professional"
    thread.alert = "engage"
    return thread


def make_mock_client() -> MagicMock:
    """Create a mock Client."""
    client = MagicMock(spec=Client)
    client.id = uuid.uuid4()
    client.brand_name = "TestBrand"
    client.company_worldview = "Test worldview"
    client.company_problem = "Test problem"
    client.client_name = "TestClient"
    return client


def make_mock_avatar(client_id: uuid.UUID) -> MagicMock:
    """Create a mock Avatar that belongs to the given client."""
    avatar = MagicMock(spec=Avatar)
    avatar.id = uuid.uuid4()
    avatar.reddit_username = "test_avatar"
    avatar.voice_profile_md = "Casual, direct voice"
    avatar.hill_i_die_on = None
    avatar.helpful_mode_topics = None
    avatar.hobby_subreddits = []
    avatar.karma_comment = 100
    avatar.client_ids = [str(client_id)]
    return avatar


def make_mock_db(draft_to_capture: MagicMock | None = None) -> MagicMock:
    """Create a mock database session.

    The mock db.add captures the CommentDraft being added, and db.commit/refresh
    are no-ops. This allows us to inspect the draft's learning_metadata after
    generate_comment completes.
    """
    db = MagicMock()
    added_objects: list = []

    def capture_add(obj):
        added_objects.append(obj)

    db.add = MagicMock(side_effect=capture_add)
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.rollback = MagicMock()
    db._added_objects = added_objects
    return db


# ---------------------------------------------------------------------------
# Property 11: Generation provenance storage
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    record_data_list=edit_record_list_strategy,
    pattern_data_list=correction_pattern_list_strategy,
    persona_selection=persona_selection_strategy,
)
def test_property_11_generation_provenance_storage(
    record_data_list: list[dict],
    pattern_data_list: list[dict],
    persona_selection: dict,
):
    """**Validates: Requirements 5.1**

    When learning context is used (examples or patterns exist), the resulting
    CommentDraft's learning_metadata SHALL contain:
    (a) IDs of all used EditRecords (as strings)
    (b) Text of all applied CorrectionPatterns (rule_text values)
    (c) A learning_token_count integer >= 0
    """
    # Set up mocks
    client = make_mock_client()
    avatar = make_mock_avatar(client.id)
    thread = make_mock_thread()
    db = make_mock_db()

    # Create mock objects — assign correct client_id for isolation checks
    examples = [make_mock_edit_record(data) for data in record_data_list]
    for ex in examples:
        ex.client_id = client.id
    patterns = [make_mock_correction_pattern(data) for data in pattern_data_list]
    for pat in patterns:
        pat.client_id = client.id

    # Mock LLM response
    mock_llm_response = {
        "data": {
            "comment": "test generated comment",
            "comment_to": "post",
            "location_depth": 0,
            "location_reasoning": "top level",
            "comment_approach": "reframe_drop",
            "strategic_angle": "reframe",
        },
        "usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }

    # Patch all external dependencies
    with (
        patch("app.services.generation.call_llm_json", return_value=mock_llm_response),
        patch("app.services.generation.log_ai_usage"),
        patch("app.services.generation.get_config", return_value="claude-sonnet"),
        patch(
            "app.services.learning.LearningService.select_few_shot_examples",
            return_value=examples,
        ),
        patch(
            "app.services.learning.LearningService.get_correction_patterns",
            return_value=patterns,
        ),
        patch("app.services.audit.log_system_action"),
    ):
        draft = generate_comment(
            db=db,
            thread=thread,
            client=client,
            avatar=avatar,
            persona_selection=persona_selection,
        )

    # Since we have at least 1 example (edit_record_list_strategy min_size=1),
    # learning context should always be used
    assert draft.learning_metadata is not None, (
        "learning_metadata should not be None when learning context is used"
    )

    metadata = draft.learning_metadata

    # (a) IDs of all used EditRecords are stored
    assert "edit_record_ids" in metadata, (
        "learning_metadata must contain 'edit_record_ids' key"
    )
    stored_ids = metadata["edit_record_ids"]
    expected_ids = [str(ex.id) for ex in examples]
    assert stored_ids == expected_ids, (
        f"edit_record_ids mismatch.\n"
        f"Expected: {expected_ids}\n"
        f"Got: {stored_ids}"
    )

    # (b) Text of all applied CorrectionPatterns
    assert "correction_patterns" in metadata, (
        "learning_metadata must contain 'correction_patterns' key"
    )
    stored_patterns = metadata["correction_patterns"]
    expected_patterns = [p.rule_text for p in patterns]
    assert stored_patterns == expected_patterns, (
        f"correction_patterns mismatch.\n"
        f"Expected: {expected_patterns}\n"
        f"Got: {stored_patterns}"
    )

    # (c) learning_token_count is a non-negative integer
    assert "learning_token_count" in metadata, (
        "learning_metadata must contain 'learning_token_count' key"
    )
    token_count = metadata["learning_token_count"]
    assert isinstance(token_count, int), (
        f"learning_token_count must be an integer, got {type(token_count)}"
    )
    assert token_count >= 0, (
        f"learning_token_count must be non-negative, got {token_count}"
    )
