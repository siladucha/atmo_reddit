"""Property-based test for AIUsageLog entries in avatar analysis.

Feature: avatar-analysis, Property 6: Every LLM attempt produces an AIUsageLog entry

Validates: Requirements 4.1, 4.2, 4.3, 5.4
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.models.ai_usage import AIUsageLog
from app.schemas.avatar_analysis import (
    AvatarAnalysisRequest,
    BehavioralProfile,
    ProfileAnalyticsInput,
)
from app.services.avatar_analysis import AnalysisError, analyze_avatar


# --- Strategies ---

def _valid_analysis_request() -> st.SearchStrategy[AvatarAnalysisRequest]:
    """Generate valid AvatarAnalysisRequest instances with at least one comment."""
    return st.builds(
        AvatarAnalysisRequest,
        reddit_username=st.text(min_size=3, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789_"),
        active=st.booleans(),
        voice_profile_md=st.text(min_size=0, max_size=50),
        profile_analytics=st.builds(
            ProfileAnalyticsInput,
            recent_comments=st.lists(
                st.fixed_dictionaries({"body": st.text(min_size=5, max_size=50)}),
                min_size=1,
                max_size=5,
            ),
            recent_posts=st.lists(
                st.fixed_dictionaries({"title": st.text(min_size=5, max_size=50)}),
                min_size=0,
                max_size=3,
            ),
            subreddits=st.lists(st.text(min_size=3, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz"), min_size=1, max_size=5),
            account_age_days=st.integers(min_value=1, max_value=3650),
            total_karma=st.integers(min_value=0, max_value=1000000),
        ),
    )


def _valid_llm_result(model: str = "openai/gpt-4o-mini") -> dict:
    """Return a valid call_llm_json result dict."""
    return {
        "data": {
            "basic": {
                "username": "testuser",
                "account_age_days": 365,
                "total_karma": 5000,
                "is_mod": False,
            },
            "behavior": {
                "total_comments": 100,
                "days_since_last_activity": 1,
                "uses_emoji": True,
                "avg_comment_length": 80,
            },
            "topics": {
                "top_subreddits": ["python", "programming"],
                "key_themes": ["coding", "tech"],
            },
            "speech": {
                "frequent_terms": ["actually", "basically"],
                "pattern_description": "Casual and informative tone",
            },
            "mismatches": [],
            "summary": "Active technical contributor with consistent engagement patterns across programming communities and helpful disposition toward newcomers.",
        },
        "input_tokens": 3200,
        "output_tokens": 800,
        "cost_usd": 0.0012,
        "duration_ms": 2500,
        "model": model,
    }


# --- Property 6 Test ---


@settings(max_examples=100)
@given(
    request=_valid_analysis_request(),
    num_failures=st.integers(min_value=0, max_value=3),
)
def test_property_6_every_llm_attempt_produces_usage_log_entry(
    request: AvatarAnalysisRequest,
    num_failures: int,
):
    """**Validates: Requirements 4.1, 4.2, 4.3, 5.4**

    Property 6: Every LLM attempt produces an AIUsageLog entry.

    For any analysis execution (regardless of outcome), each LLM call attempt
    SHALL produce exactly one AIUsageLog entry with operation="avatar_analysis",
    the correct avatar_id, model name, and duration_ms > 0.
    """
    avatar_id = uuid.uuid4()
    primary_model = "openai/gpt-4o-mini"
    fallback_model = "anthropic/claude-sonnet-4-20250514"

    # Track all db.add() calls to count AIUsageLog entries
    added_logs: list[AIUsageLog] = []

    # Create a mock DB session
    mock_db = MagicMock()

    def track_add(obj):
        if isinstance(obj, AIUsageLog):
            added_logs.append(obj)

    mock_db.add.side_effect = track_add
    mock_db.flush.return_value = None
    mock_db.commit.return_value = None

    # Build the call_llm_json mock behavior:
    # - num_failures=0: immediate success (1 call total)
    # - num_failures=1: 1 failure + success on retry (2 calls total)
    # - num_failures=2: 2 failures + success on retry (3 calls total)
    # - num_failures=3: 3 primary failures + fallback attempt (4 calls total)
    call_count = [0]
    import litellm.exceptions

    def mock_call_llm_json(**kwargs):
        call_count[0] += 1
        current_call = call_count[0]

        if current_call <= num_failures:
            # Simulate transient failure
            raise litellm.exceptions.Timeout(
                message="Request timed out",
                model=kwargs.get("model", primary_model),
                llm_provider="openai",
            )

        # Success - return valid result
        model_used = kwargs.get("model", primary_model)
        return _valid_llm_result(model=model_used)

    # For num_failures=3, all primary attempts fail, then fallback succeeds
    # Total calls: 3 primary + 1 fallback = 4
    # For num_failures < 3, success happens during primary attempts
    # Total calls: num_failures + 1

    if num_failures == 3:
        # All 3 primary attempts fail, fallback succeeds
        expected_total_calls = 4  # 3 primary + 1 fallback
    else:
        # Success on attempt (num_failures + 1)
        expected_total_calls = num_failures + 1

    # Mock time.time() to simulate elapsed time for each call.
    # Each call to time.time() advances by 0.5s so duration_ms is always > 0.
    time_counter = [1000.0]

    def mock_time():
        time_counter[0] += 0.5
        return time_counter[0]

    with patch("app.services.avatar_analysis.call_llm_json", side_effect=mock_call_llm_json), \
         patch("app.services.avatar_analysis.get_setting") as mock_get_setting, \
         patch("app.services.avatar_analysis.get_recent_edits", return_value=[]), \
         patch("app.services.avatar_analysis.time.sleep"), \
         patch("app.services.avatar_analysis.time.time", side_effect=mock_time):

        # Configure settings
        def setting_side_effect(db, key):
            settings_map = {
                "avatar_analysis_primary_model": primary_model,
                "avatar_analysis_fallback_model": fallback_model,
                "avatar_analysis_max_retries": "2",
                "avatar_analysis_few_shot_limit": "3",
            }
            return settings_map.get(key, "")

        mock_get_setting.side_effect = setting_side_effect

        # Run analysis
        try:
            result = analyze_avatar(mock_db, avatar_id, request)
            # Should succeed for num_failures <= 3
            assert isinstance(result, BehavioralProfile)
        except AnalysisError:
            # This shouldn't happen since we always have a success path
            # (fallback succeeds for num_failures=3)
            pytest.fail("AnalysisError raised unexpectedly")

    # --- Verify Property 6 ---

    # 1. Number of AIUsageLog entries == number of LLM call attempts
    assert len(added_logs) == expected_total_calls, (
        f"Expected {expected_total_calls} AIUsageLog entries, got {len(added_logs)}. "
        f"num_failures={num_failures}, call_count={call_count[0]}"
    )

    # 2. Each entry has correct fields
    for i, log in enumerate(added_logs):
        # operation must be "avatar_analysis"
        assert log.operation == "avatar_analysis", (
            f"Log entry {i}: expected operation='avatar_analysis', got '{log.operation}'"
        )

        # avatar_id must match
        assert log.avatar_id == avatar_id, (
            f"Log entry {i}: expected avatar_id={avatar_id}, got {log.avatar_id}"
        )

        # model must be non-empty string
        assert log.model and len(log.model) > 0, (
            f"Log entry {i}: model must be non-empty, got '{log.model}'"
        )

        # duration_ms must be > 0
        assert log.duration_ms > 0, (
            f"Log entry {i}: expected duration_ms > 0, got {log.duration_ms}"
        )

    # 3. Verify model names are correct
    for i, log in enumerate(added_logs):
        if num_failures == 3 and i == 3:
            # Last entry is fallback model
            assert log.model == fallback_model, (
                f"Fallback log entry should use model '{fallback_model}', got '{log.model}'"
            )
        elif i < num_failures:
            # Failed primary attempts use primary model
            assert log.model == primary_model, (
                f"Failed primary log entry {i} should use model '{primary_model}', got '{log.model}'"
            )
