"""Property-based tests for Avatar Analysis Service.

Tests schema validation (Properties 1, 2) and retry/fallback logic (Properties 3, 4, 5)
using Hypothesis.
"""

import uuid
from unittest.mock import MagicMock, patch, call

import litellm
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from pydantic import ValidationError

from app.schemas.avatar_analysis import (
    AvatarAnalysisRequest,
    BehavioralProfile,
    ProfileAnalyticsInput,
)
from app.services.avatar_analysis import AnalysisError, analyze_avatar


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

def _valid_comment():
    """Generate a valid comment dict."""
    return st.fixed_dictionaries({"body": st.text(min_size=5, max_size=100)})


def _valid_post():
    """Generate a valid post dict."""
    return st.fixed_dictionaries({"title": st.text(min_size=5, max_size=100)})


@st.composite
def valid_analysis_requests(draw):
    """Generate valid AvatarAnalysisRequest instances with at least one comment or post."""
    comments = draw(st.lists(_valid_comment(), min_size=1, max_size=5))
    posts = draw(st.lists(_valid_post(), min_size=0, max_size=3))
    subreddits = draw(st.lists(st.text(min_size=3, max_size=20), min_size=1, max_size=5))

    return AvatarAnalysisRequest(
        reddit_username=draw(st.text(min_size=3, max_size=20)),
        active=draw(st.booleans()),
        voice_profile_md=draw(st.text(min_size=0, max_size=50)),
        profile_analytics=ProfileAnalyticsInput(
            recent_comments=comments,
            recent_posts=posts,
            subreddits=subreddits,
            account_age_days=draw(st.integers(min_value=1, max_value=3650)),
            total_karma=draw(st.integers(min_value=0, max_value=1000000)),
        ),
    )


def _make_valid_profile_dict():
    """Return a valid BehavioralProfile dict for mocking LLM responses."""
    return {
        "basic": {
            "username": "test_user",
            "account_age_days": 365,
            "total_karma": 5000,
            "is_mod": False,
        },
        "behavior": {
            "total_comments": 100,
            "days_since_last_activity": 2,
            "uses_emoji": True,
            "avg_comment_length": 80,
        },
        "topics": {
            "top_subreddits": ["python", "programming"],
            "key_themes": ["coding", "open source"],
        },
        "speech": {
            "frequent_terms": ["actually", "basically"],
            "pattern_description": "Casual and informative tone",
        },
        "mismatches": [],
        "summary": "Active developer who engages in technical discussions with a casual tone and helpful attitude toward newcomers.",
    }


def _make_successful_llm_result():
    """Return a successful call_llm_json result dict."""
    return {
        "data": _make_valid_profile_dict(),
        "input_tokens": 1500,
        "output_tokens": 500,
        "cost_usd": 0.001,
        "duration_ms": 2000,
        "model": "openai/gpt-4o-mini",
    }


def _make_mock_db():
    """Create a mock DB session that supports required operations."""
    db = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    db.commit = MagicMock()
    db.refresh = MagicMock()
    db.execute = MagicMock()
    db.query = MagicMock()
    return db


def _mock_get_setting(key_values: dict):
    """Return a get_setting mock that returns values from the provided dict."""
    def _get_setting(db, key):
        return key_values.get(key, "")
    return _get_setting


# Default settings for all tests
_DEFAULT_SETTINGS = {
    "avatar_analysis_primary_model": "openai/gpt-4o-mini",
    "avatar_analysis_fallback_model": "anthropic/claude-sonnet-4-20250514",
    "avatar_analysis_max_retries": "2",
    "avatar_analysis_few_shot_limit": "3",
}


# ---------------------------------------------------------------------------
# Property 1: Valid input always produces schema-valid output
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 1: Valid input always produces schema-valid output


@st.composite
def valid_behavioral_profile_dicts(draw):
    """Generate a well-formed dict that should pass BehavioralProfile.model_validate()."""
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


@settings(max_examples=100)
@given(request=valid_analysis_requests())
def test_property_1_valid_input_produces_valid_request(request):
    """**Validates: Requirements 1.1, 1.2, 1.3, 2.1, 2.3**

    For any valid AvatarAnalysisRequest (non-empty username, non-empty comments or posts),
    the schema accepts the input without error and the check_sufficient_data validator passes.
    """
    # The request was constructed successfully — confirms schema accepts valid input
    assert request.reddit_username
    assert request.profile_analytics is not None
    # At least one of comments or posts must be non-empty (check_sufficient_data passed)
    assert (
        request.profile_analytics.recent_comments
        or request.profile_analytics.recent_posts
    )


@settings(max_examples=100)
@given(profile_dict=valid_behavioral_profile_dicts())
def test_property_1_behavioral_profile_validates_well_formed_dicts(profile_dict):
    """**Validates: Requirements 2.1, 2.3, 6.2**

    For any well-formed BehavioralProfile dict, model_validate() accepts it without error
    and all fields round-trip correctly.
    """
    profile = BehavioralProfile.model_validate(profile_dict)
    assert profile.basic.username == profile_dict["basic"]["username"]
    assert profile.basic.account_age_days == profile_dict["basic"]["account_age_days"]
    assert profile.basic.total_karma == profile_dict["basic"]["total_karma"]
    assert profile.basic.is_mod == profile_dict["basic"]["is_mod"]
    assert profile.behavior.total_comments == profile_dict["behavior"]["total_comments"]
    assert profile.behavior.uses_emoji == profile_dict["behavior"]["uses_emoji"]
    assert profile.behavior.avg_comment_length == profile_dict["behavior"]["avg_comment_length"]
    assert profile.topics.top_subreddits == profile_dict["topics"]["top_subreddits"]
    assert profile.topics.key_themes == profile_dict["topics"]["key_themes"]
    assert profile.speech.frequent_terms == profile_dict["speech"]["frequent_terms"]
    assert profile.speech.pattern_description == profile_dict["speech"]["pattern_description"]
    assert profile.mismatches == profile_dict["mismatches"]
    assert profile.summary == profile_dict["summary"]


# ---------------------------------------------------------------------------
# Property 2: Invalid input always rejected with field descriptions
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 2: Invalid input always rejected with field descriptions


@settings(max_examples=100)
@given(
    active=st.booleans(),
    voice=st.text(max_size=50),
)
def test_property_2_missing_reddit_username_rejected(active, voice):
    """**Validates: Requirements 1.2, 6.3**

    When reddit_username field is absent from payload, validation error references it.
    """
    payload = {
        "active": active,
        "voice_profile_md": voice,
        "profile_analytics": {
            "recent_comments": [{"body": "test", "subreddit": "r/test", "score": 1}],
            "recent_posts": [],
            "subreddits": ["test"],
            "account_age_days": 100,
            "total_karma": 500,
        },
    }
    with pytest.raises(ValidationError) as exc_info:
        AvatarAnalysisRequest.model_validate(payload)
    error_fields = [e["loc"][-1] for e in exc_info.value.errors()]
    assert "reddit_username" in error_fields


@settings(max_examples=100)
@given(
    username=st.text(min_size=3, max_size=20),
    active=st.booleans(),
)
def test_property_2_missing_profile_analytics_rejected(username, active):
    """**Validates: Requirements 1.2, 6.3**

    When profile_analytics is missing, validation error references the field.
    """
    payload = {
        "reddit_username": username,
        "active": active,
    }
    with pytest.raises(ValidationError) as exc_info:
        AvatarAnalysisRequest.model_validate(payload)
    error_fields = [e["loc"][-1] for e in exc_info.value.errors()]
    assert "profile_analytics" in error_fields


@settings(max_examples=100)
@given(
    username=st.text(min_size=3, max_size=20),
    subreddits=st.lists(st.text(min_size=1, max_size=20), min_size=1, max_size=3),
    account_age=st.integers(min_value=1, max_value=5000),
    karma=st.integers(min_value=0, max_value=1000000),
)
def test_property_2_empty_comments_and_posts_rejected(username, subreddits, account_age, karma):
    """**Validates: Requirements 1.3, 6.3**

    When both recent_comments and recent_posts are empty, the check_sufficient_data
    validator rejects the request with an error referencing the insufficient data.
    """
    with pytest.raises(ValidationError) as exc_info:
        AvatarAnalysisRequest(
            reddit_username=username,
            active=True,
            profile_analytics=ProfileAnalyticsInput(
                recent_comments=[],
                recent_posts=[],
                subreddits=subreddits,
                account_age_days=account_age,
                total_karma=karma,
            ),
        )
    # The error should reference the insufficient data condition
    error_messages = str(exc_info.value)
    assert "recent_comments" in error_messages or "recent_posts" in error_messages or "Insufficient" in error_messages


# ---------------------------------------------------------------------------
# Property 3: Transient failures trigger retry with exponential backoff
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 3: Transient failures trigger retry with exponential backoff


@settings(max_examples=100)
@given(
    request=valid_analysis_requests(),
    num_failures=st.integers(min_value=0, max_value=2),
)
def test_property_3_transient_failures_trigger_retry_with_backoff(request, num_failures):
    """**Validates: Requirements 2.2, 5.1**

    For any valid analysis request, when the LLM call fails with a transient error
    N times (0-2) before succeeding, the service SHALL retry and eventually succeed,
    with exponential backoff delays between retries.
    """
    db = _make_mock_db()
    avatar_id = uuid.uuid4()

    # Build side effects: N failures then success
    failures = [
        litellm.exceptions.Timeout(
            message="timeout",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )
        for _ in range(num_failures)
    ]
    success = _make_successful_llm_result()
    side_effects = failures + [success]

    with (
        patch("app.services.avatar_analysis.get_setting", side_effect=_mock_get_setting(_DEFAULT_SETTINGS)),
        patch("app.services.avatar_analysis.get_recent_edits", return_value=[]),
        patch("app.services.avatar_analysis.call_llm_json", side_effect=side_effects) as mock_llm,
        patch("app.services.avatar_analysis.time.sleep") as mock_sleep,
    ):
        result = analyze_avatar(db, avatar_id, request)

        # Verify the result is a valid BehavioralProfile
        assert isinstance(result, BehavioralProfile)

        # Verify total LLM calls = num_failures + 1 (the successful one)
        assert mock_llm.call_count == num_failures + 1

        # Verify exponential backoff delays
        # Delays should be: 2^0 * 2 = 2s, 2^1 * 2 = 4s (for attempts before the last retry)
        expected_delays = [2 * (2 ** i) for i in range(num_failures)]
        actual_delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert actual_delays == expected_delays


# ---------------------------------------------------------------------------
# Property 4: Exhausted retries trigger exactly one fallback attempt
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 4: Exhausted retries trigger exactly one fallback attempt


@settings(max_examples=100)
@given(request=valid_analysis_requests())
def test_property_4_exhausted_retries_trigger_one_fallback(request):
    """**Validates: Requirements 3.2, 5.2**

    For any valid analysis request where all primary model attempts (initial + 2 retries)
    fail, the service SHALL make exactly one call to the configured fallback model.
    """
    db = _make_mock_db()
    avatar_id = uuid.uuid4()

    # 3 primary failures (1 initial + 2 retries), then fallback succeeds
    primary_failures = [
        litellm.exceptions.Timeout(
            message="timeout",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )
        for _ in range(3)
    ]
    fallback_success = _make_successful_llm_result()
    fallback_success["model"] = "anthropic/claude-sonnet-4-20250514"

    side_effects = primary_failures + [fallback_success]

    with (
        patch("app.services.avatar_analysis.get_setting", side_effect=_mock_get_setting(_DEFAULT_SETTINGS)),
        patch("app.services.avatar_analysis.get_recent_edits", return_value=[]),
        patch("app.services.avatar_analysis.call_llm_json", side_effect=side_effects) as mock_llm,
        patch("app.services.avatar_analysis.time.sleep"),
    ):
        result = analyze_avatar(db, avatar_id, request)

        # Verify the result is valid
        assert isinstance(result, BehavioralProfile)

        # Total calls: 3 primary + 1 fallback = 4
        assert mock_llm.call_count == 4

        # Verify the last call used the fallback model
        last_call_kwargs = mock_llm.call_args_list[-1]
        assert last_call_kwargs.kwargs.get("model") or last_call_kwargs[1].get("model") == "anthropic/claude-sonnet-4-20250514"

        # Verify exactly 1 fallback call (the 4th call uses fallback model)
        fallback_calls = [
            c for c in mock_llm.call_args_list
            if (c.kwargs.get("model") or c[1].get("model")) == "anthropic/claude-sonnet-4-20250514"
        ]
        assert len(fallback_calls) == 1


# ---------------------------------------------------------------------------
# Property 5: Total failure returns structured error with correct attempt count
# ---------------------------------------------------------------------------

# Feature: avatar-analysis, Property 5: Total failure returns structured error with correct attempt count


@settings(max_examples=100)
@given(request=valid_analysis_requests())
def test_property_5_total_failure_returns_structured_error(request):
    """**Validates: Requirements 5.3, 6.4**

    For any valid analysis request where all attempts (primary retries + fallback) fail,
    the returned error SHALL contain attempts=4 and a non-empty last_failure_reason.
    """
    db = _make_mock_db()
    avatar_id = uuid.uuid4()

    # All 4 attempts fail (3 primary + 1 fallback)
    all_failures = [
        litellm.exceptions.Timeout(
            message="connection timed out",
            model="openai/gpt-4o-mini",
            llm_provider="openai",
        )
        for _ in range(4)
    ]

    with (
        patch("app.services.avatar_analysis.get_setting", side_effect=_mock_get_setting(_DEFAULT_SETTINGS)),
        patch("app.services.avatar_analysis.get_recent_edits", return_value=[]),
        patch("app.services.avatar_analysis.call_llm_json", side_effect=all_failures) as mock_llm,
        patch("app.services.avatar_analysis.time.sleep"),
    ):
        with pytest.raises(AnalysisError) as exc_info:
            analyze_avatar(db, avatar_id, request)

        error = exc_info.value

        # Verify attempt count: 1 initial + 2 retries + 1 fallback = 4
        assert error.attempts == 4

        # Verify last_failure_reason is non-empty
        assert error.last_failure_reason
        assert len(error.last_failure_reason) > 0

        # Verify total LLM calls made
        assert mock_llm.call_count == 4
