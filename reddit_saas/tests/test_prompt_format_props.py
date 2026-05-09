"""Property-based tests for Prompt Formatting.

Tests Property 6: For any non-empty list of examples, format_learning_context output
contains "Learned corrections from past reviews" and BEFORE/AFTER text for each example.

Uses Hypothesis with MagicMock objects for EditRecord and CorrectionPattern.
"""

# Feature: self-learning-loop, Property 6: For any non-empty list of examples, format_learning_context output contains "Learned corrections from past reviews" and BEFORE/AFTER text for each example

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.correction_pattern import CorrectionPattern
from app.models.edit_record import EditRecord
from app.services.learning import LearningService


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate realistic text for drafts (non-empty, printable)
draft_text = st.text(
    min_size=5,
    max_size=200,
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
).filter(lambda s: s.strip())

# Generate rule text for correction patterns (non-empty, max 100 chars)
rule_text = st.text(
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

# Strategy for a single mock EditRecord
edit_record_strategy = st.fixed_dictionaries(
    {
        "ai_draft": draft_text,
        "edited_draft": draft_text,
        "final_status": st.sampled_from(["approved", "rejected"]),
    }
)

# Strategy for a non-empty list of edit records (1-5 examples)
edit_record_list = st.lists(edit_record_strategy, min_size=1, max_size=5)

# Strategy for a single mock CorrectionPattern
correction_pattern_strategy = st.fixed_dictionaries(
    {
        "pattern_type": st.sampled_from(PATTERN_TYPES),
        "rule_text": rule_text,
        "frequency": st.integers(min_value=1, max_value=50),
    }
)

# Strategy for a list of correction patterns (0-3)
correction_pattern_list = st.lists(correction_pattern_strategy, min_size=0, max_size=3)


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

    if data["final_status"] == "rejected":
        record.edited_draft = None
    else:
        record.edited_draft = data["edited_draft"]

    record.created_at = datetime.now(timezone.utc)
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


# ---------------------------------------------------------------------------
# Property 6: Prompt formatting contains required sections
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    record_data_list=edit_record_list,
    pattern_data_list=correction_pattern_list,
)
def test_property_6_prompt_formatting_contains_required_sections(
    record_data_list: list[dict],
    pattern_data_list: list[dict],
):
    """**Validates: Requirements 2.4**

    For any non-empty list of Few_Shot_Examples, format_learning_context SHALL
    produce output containing:
    (a) The label "Learned corrections from past reviews" (case-insensitive)
    (b) For each approved example: both BEFORE and AFTER text
    (c) For each rejected example: BEFORE text and rejection indicator
    """
    # Create mock objects
    examples = [make_mock_edit_record(data) for data in record_data_list]
    patterns = [make_mock_correction_pattern(data) for data in pattern_data_list]

    # Call the method under test
    service = LearningService()
    result = service.format_learning_context(examples, patterns)

    # (a) Output contains "Learned corrections from past reviews"
    assert "learned corrections from past reviews" in result.lower(), (
        f"Output must contain 'Learned corrections from past reviews'. Got:\n{result}"
    )

    # (b) For each approved example: both BEFORE and AFTER text present
    for data, example in zip(record_data_list, examples):
        if example.final_status == "approved":
            assert example.ai_draft in result, (
                f"BEFORE text (ai_draft) for approved example must appear in output. "
                f"Expected: {example.ai_draft!r}"
            )
            expected_after = example.edited_draft if example.edited_draft else example.ai_draft
            assert expected_after in result, (
                f"AFTER text (edited_draft) for approved example must appear in output. "
                f"Expected: {expected_after!r}"
            )

    # (c) For each rejected example: BEFORE text and rejection indicator
    for data, example in zip(record_data_list, examples):
        if example.final_status == "rejected":
            assert example.ai_draft in result, (
                f"BEFORE text (ai_draft) for rejected example must appear in output. "
                f"Expected: {example.ai_draft!r}"
            )
            # Check for rejection indicator — the implementation uses
            # "rejected" in the label and "(This was rejected by the reviewer)"
            assert "rejected" in result.lower(), (
                "Output must contain a rejection indicator for rejected examples."
            )
