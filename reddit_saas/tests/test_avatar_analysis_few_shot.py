"""Integration tests for few-shot injection into the avatar analysis prompt.

Tests cover:
- Analysis without edit records produces same prompt as Phase 1 (no few-shot section)
- Analysis with edit records injects correct number of examples
- Few-shot limit is respected (max N examples)

Requirements: 8.1, 8.2, 8.3, 8.4, 10.2
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.schemas.avatar_analysis import AvatarAnalysisRequest, BehavioralProfile
from app.services.avatar_analysis import analyze_avatar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def avatar_id():
    """A fixed avatar UUID for testing."""
    return uuid.uuid4()


@pytest.fixture
def valid_request():
    """A valid AvatarAnalysisRequest for testing."""
    return AvatarAnalysisRequest(
        reddit_username="test_avatar",
        active=True,
        voice_profile_md="A helpful tech enthusiast",
        profile_analytics={
            "recent_comments": [
                {"body": "Great post about Python!", "subreddit": "python", "score": 10}
            ],
            "recent_posts": [],
            "subreddits": ["python", "fastapi"],
            "account_age_days": 365,
            "total_karma": 1200,
        },
    )


@pytest.fixture
def mock_llm_success_result():
    """A successful LLM result dict matching call_llm_json return format."""
    return {
        "data": {
            "basic": {
                "username": "test_avatar",
                "account_age_days": 365,
                "total_karma": 1200,
                "is_mod": False,
            },
            "behavior": {
                "total_comments": 100,
                "days_since_last_activity": 1,
                "uses_emoji": False,
                "avg_comment_length": 50,
            },
            "topics": {
                "top_subreddits": ["python", "fastapi"],
                "key_themes": ["web development"],
            },
            "speech": {
                "frequent_terms": ["actually"],
                "pattern_description": "Concise technical style",
            },
            "mismatches": [],
            "summary": "A technically focused developer who engages in web framework discussions with concise helpful responses and occasional humor.",
        },
        "input_tokens": 1000,
        "output_tokens": 500,
        "cost_usd": 0.001,
        "model": "openai/gpt-4o-mini",
    }


@pytest.fixture
def mock_edit_records(avatar_id):
    """Create mock AnalysisEditRecord objects with known data."""
    records = []
    for i in range(5):
        record = MagicMock()
        record.id = uuid.uuid4()
        record.avatar_id = avatar_id
        record.llm_output = {
            "basic": {"username": f"user_{i}", "account_age_days": 100 + i},
            "summary": f"Original summary {i}",
        }
        record.human_edited = {
            "basic": {"username": f"user_{i}", "account_age_days": 100 + i},
            "summary": f"Corrected summary {i}",
        }
        record.diff_summary = f"Changed 'summary' from 'Original summary {i}' to 'Corrected summary {i}'"
        record.created_at = datetime(2025, 6, 1, 12, 0, i, tzinfo=timezone.utc)
        records.append(record)
    return records


@pytest.fixture
def mock_db():
    """A mock database session."""
    return MagicMock()


# ---------------------------------------------------------------------------
# Test: Analysis without edit records produces same prompt as Phase 1
# Requirement 8.4, 10.2
# ---------------------------------------------------------------------------


class TestNoEditRecords:
    """When no edit records exist, the prompt is identical to Phase 1."""

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_no_edits_produces_phase1_prompt(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result
    ):
        """When get_recent_edits returns empty list, no few-shot section in prompt."""
        # Configure mocks
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "3",
        }.get(key, "")

        mock_get_edits.return_value = []
        mock_call_llm.return_value = mock_llm_success_result

        # Execute
        analyze_avatar(mock_db, avatar_id, valid_request)

        # Verify call_llm_json was called
        mock_call_llm.assert_called_once()
        call_kwargs = mock_call_llm.call_args[1]
        messages = call_kwargs["messages"]

        # Verify the user prompt does NOT contain few-shot section
        user_prompt = messages[1]["content"]
        assert "Corrections from previous analyses" not in user_prompt
        assert "Example 1:" not in user_prompt
        assert "Original:" not in user_prompt
        assert "Corrected:" not in user_prompt
        assert "What changed:" not in user_prompt

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_no_edits_prompt_contains_avatar_data(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result
    ):
        """Phase 1 prompt still contains the avatar data (username, comments, etc.)."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "3",
        }.get(key, "")

        mock_get_edits.return_value = []
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        call_kwargs = mock_call_llm.call_args[1]
        messages = call_kwargs["messages"]

        # Verify system prompt exists
        system_prompt = messages[0]["content"]
        assert "behavioral analyst" in system_prompt

        # Verify user prompt contains avatar data
        user_prompt = messages[1]["content"]
        assert "test_avatar" in user_prompt
        assert "Great post about Python!" in user_prompt


# ---------------------------------------------------------------------------
# Test: Analysis with edit records injects correct number of examples
# Requirements 8.1, 8.2, 8.3
# ---------------------------------------------------------------------------


class TestWithEditRecords:
    """When edit records exist, they are injected as few-shot examples."""

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_edit_records_injected_into_prompt(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result, mock_edit_records
    ):
        """When edit records exist, the prompt contains the few-shot section."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "3",
        }.get(key, "")

        # Return 3 edit records (respecting the limit)
        mock_get_edits.return_value = mock_edit_records[:3]
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        call_kwargs = mock_call_llm.call_args[1]
        messages = call_kwargs["messages"]
        user_prompt = messages[1]["content"]

        # Verify few-shot section is present
        assert "Corrections from previous analyses" in user_prompt
        assert "Learn from these to avoid repeating the same mistakes" in user_prompt

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_correct_number_of_examples_injected(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result, mock_edit_records
    ):
        """The number of examples in the prompt matches the number of edit records."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "3",
        }.get(key, "")

        mock_get_edits.return_value = mock_edit_records[:3]
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        call_kwargs = mock_call_llm.call_args[1]
        messages = call_kwargs["messages"]
        user_prompt = messages[1]["content"]

        # Verify exactly 3 examples are present
        assert "Example 1:" in user_prompt
        assert "Example 2:" in user_prompt
        assert "Example 3:" in user_prompt
        assert "Example 4:" not in user_prompt

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_example_content_matches_edit_records(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result, mock_edit_records
    ):
        """Each example contains the Original, Corrected, and What changed fields."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "3",
        }.get(key, "")

        mock_get_edits.return_value = mock_edit_records[:2]
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        call_kwargs = mock_call_llm.call_args[1]
        messages = call_kwargs["messages"]
        user_prompt = messages[1]["content"]

        # Verify each example has the expected structure
        assert "Original:" in user_prompt
        assert "Corrected:" in user_prompt
        assert "What changed:" in user_prompt

        # Verify actual content from mock records is present
        assert "Original summary 0" in user_prompt
        assert "Corrected summary 0" in user_prompt
        assert "Changed 'summary'" in user_prompt

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_single_edit_record_injected(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result, mock_edit_records
    ):
        """A single edit record produces exactly one example in the prompt."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "3",
        }.get(key, "")

        mock_get_edits.return_value = mock_edit_records[:1]
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        call_kwargs = mock_call_llm.call_args[1]
        messages = call_kwargs["messages"]
        user_prompt = messages[1]["content"]

        assert "Example 1:" in user_prompt
        assert "Example 2:" not in user_prompt
        assert "Corrections from previous analyses" in user_prompt


# ---------------------------------------------------------------------------
# Test: Few-shot limit is respected (max N examples)
# Requirements 8.1, 8.2
# ---------------------------------------------------------------------------


class TestFewShotLimit:
    """The few-shot limit from SystemSettings is passed to get_recent_edits."""

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_default_limit_passed_to_get_recent_edits(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result
    ):
        """Default few_shot_limit of 3 is passed to get_recent_edits."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "3",
        }.get(key, "")

        mock_get_edits.return_value = []
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        # Verify get_recent_edits was called with limit=3
        mock_get_edits.assert_called_once_with(mock_db, avatar_id, limit=3)

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_custom_limit_passed_to_get_recent_edits(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result
    ):
        """Custom few_shot_limit of 5 is passed to get_recent_edits."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "5",
        }.get(key, "")

        mock_get_edits.return_value = []
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        # Verify get_recent_edits was called with limit=5
        mock_get_edits.assert_called_once_with(mock_db, avatar_id, limit=5)

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_limit_of_1_passed_to_get_recent_edits(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result, mock_edit_records
    ):
        """When limit is 1, only 1 example is injected."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": "1",
        }.get(key, "")

        mock_get_edits.return_value = mock_edit_records[:1]
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        # Verify get_recent_edits was called with limit=1
        mock_get_edits.assert_called_once_with(mock_db, avatar_id, limit=1)

        # Verify only 1 example in prompt
        call_kwargs = mock_call_llm.call_args[1]
        messages = call_kwargs["messages"]
        user_prompt = messages[1]["content"]
        assert "Example 1:" in user_prompt
        assert "Example 2:" not in user_prompt

    @patch("app.services.avatar_analysis.call_llm_json")
    @patch("app.services.avatar_analysis.get_recent_edits")
    @patch("app.services.avatar_analysis.get_setting")
    def test_fallback_limit_when_setting_not_configured(
        self, mock_get_setting, mock_get_edits, mock_call_llm, mock_db, avatar_id, valid_request, mock_llm_success_result
    ):
        """When avatar_analysis_few_shot_limit is not set, defaults to 3."""
        mock_get_setting.side_effect = lambda db, key: {
            "avatar_analysis_primary_model": "openai/gpt-4o-mini",
            "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
            "avatar_analysis_max_retries": "2",
            "avatar_analysis_few_shot_limit": None,  # Not configured
        }.get(key, "")

        mock_get_edits.return_value = []
        mock_call_llm.return_value = mock_llm_success_result

        analyze_avatar(mock_db, avatar_id, valid_request)

        # Default limit of 3 should be used
        mock_get_edits.assert_called_once_with(mock_db, avatar_id, limit=3)
