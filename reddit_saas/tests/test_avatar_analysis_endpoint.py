"""Unit tests for the avatar analysis REST endpoint.

Tests cover:
- Successful analysis returns 200 with valid BehavioralProfile
- Missing avatar returns 404
- Invalid payload returns 422 with field descriptions
- All-failures returns 502 with structured error
- Unauthenticated request returns 303 redirect (auth middleware)

Requirements: 6.1, 6.2, 6.3, 6.4, 6.5
"""

import uuid
from unittest.mock import patch

import pytest

from app.models.avatar import Avatar
from app.services.avatar_analysis import AnalysisError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_avatar(db):
    """Create a real avatar in the DB and return it."""
    avatar = Avatar(
        reddit_username="analysis_test_avatar",
        active=True,
        voice_profile_md="A helpful tech enthusiast",
    )
    db.add(avatar)
    db.flush()
    return avatar


@pytest.fixture
def valid_payload():
    """A valid AvatarAnalysisRequest payload."""
    return {
        "reddit_username": "analysis_test_avatar",
        "active": True,
        "voice_profile_md": "A helpful tech enthusiast",
        "profile_analytics": {
            "recent_comments": [
                {"body": "Great post!", "subreddit": "python", "score": 5}
            ],
            "recent_posts": [],
            "subreddits": ["python", "fastapi"],
            "account_age_days": 365,
            "total_karma": 1200,
        },
    }


@pytest.fixture
def mock_behavioral_profile():
    """A valid BehavioralProfile dict that the mocked service returns."""
    from app.schemas.avatar_analysis import BehavioralProfile

    return BehavioralProfile(
        basic={
            "username": "analysis_test_avatar",
            "account_age_days": 365,
            "total_karma": 1200,
            "is_mod": False,
        },
        behavior={
            "total_comments": 150,
            "days_since_last_activity": 1,
            "uses_emoji": False,
            "avg_comment_length": 45,
        },
        topics={
            "top_subreddits": ["python", "fastapi"],
            "key_themes": ["web development", "APIs"],
        },
        speech={
            "frequent_terms": ["actually", "basically"],
            "pattern_description": "Concise technical explanations with occasional humor",
        },
        mismatches=["Voice profile mentions enthusiasm but comments are neutral in tone"],
        summary="A technically focused Python developer who engages primarily in web framework discussions with concise helpful responses.",
    )


# ---------------------------------------------------------------------------
# Test: Successful analysis returns 200 with valid BehavioralProfile
# Requirement 6.2
# ---------------------------------------------------------------------------


class TestSuccessfulAnalysis:
    """POST /api/avatars/{avatar_id}/analyze with valid payload returns 200."""

    @patch("app.routes.avatar_analysis.analyze_avatar")
    def test_returns_200_with_behavioral_profile(
        self, mock_analyze, admin_client, test_avatar, valid_payload, mock_behavioral_profile
    ):
        """Successful analysis returns 200 with a valid BehavioralProfile JSON."""
        mock_analyze.return_value = mock_behavioral_profile

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=valid_payload,
        )

        assert response.status_code == 200
        data = response.json()
        assert "basic" in data
        assert "behavior" in data
        assert "topics" in data
        assert "speech" in data
        assert "mismatches" in data
        assert "summary" in data
        assert data["basic"]["username"] == "analysis_test_avatar"
        assert data["behavior"]["total_comments"] == 150
        assert data["topics"]["top_subreddits"] == ["python", "fastapi"]

    @patch("app.routes.avatar_analysis.analyze_avatar")
    def test_calls_analyze_avatar_with_correct_args(
        self, mock_analyze, admin_client, db, test_avatar, valid_payload, mock_behavioral_profile
    ):
        """The endpoint passes db, avatar_id, and parsed request to analyze_avatar."""
        mock_analyze.return_value = mock_behavioral_profile

        admin_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=valid_payload,
        )

        mock_analyze.assert_called_once()
        call_args = mock_analyze.call_args
        # First positional arg is db session, second is avatar_id, third is request
        assert call_args[0][1] == test_avatar.id


# ---------------------------------------------------------------------------
# Test: Missing avatar returns 404
# Requirement 6.1
# ---------------------------------------------------------------------------


class TestMissingAvatar:
    """POST /api/avatars/{avatar_id}/analyze with non-existent avatar returns 404."""

    def test_nonexistent_avatar_returns_404(self, admin_client, valid_payload):
        """A random UUID that doesn't exist in the DB returns 404."""
        fake_id = uuid.uuid4()

        response = admin_client.post(
            f"/api/avatars/{fake_id}/analyze",
            json=valid_payload,
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Test: Invalid payload returns 422 with field descriptions
# Requirement 6.3
# ---------------------------------------------------------------------------


class TestInvalidPayload:
    """POST /api/avatars/{avatar_id}/analyze with invalid payload returns 422."""

    def test_missing_reddit_username_returns_422(self, admin_client, test_avatar):
        """Missing reddit_username field triggers 422 with field info."""
        payload = {
            "active": True,
            "profile_analytics": {
                "recent_comments": [{"body": "test"}],
                "recent_posts": [],
                "subreddits": ["python"],
                "account_age_days": 100,
                "total_karma": 500,
            },
        }

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=payload,
        )

        assert response.status_code == 422
        data = response.json()
        # FastAPI returns validation errors in detail
        assert "detail" in data
        # Check that the error references the missing field
        errors = data["detail"]
        field_names = [e.get("loc", [])[-1] for e in errors if "loc" in e]
        assert "reddit_username" in field_names

    def test_missing_profile_analytics_returns_422(self, admin_client, test_avatar):
        """Missing profile_analytics field triggers 422."""
        payload = {
            "reddit_username": "test_user",
            "active": True,
        }

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=payload,
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        errors = data["detail"]
        field_names = [e.get("loc", [])[-1] for e in errors if "loc" in e]
        assert "profile_analytics" in field_names

    def test_empty_comments_and_posts_returns_422(self, admin_client, test_avatar):
        """Empty recent_comments AND recent_posts triggers check_sufficient_data validator."""
        payload = {
            "reddit_username": "test_user",
            "active": True,
            "profile_analytics": {
                "recent_comments": [],
                "recent_posts": [],
                "subreddits": ["python"],
                "account_age_days": 100,
                "total_karma": 500,
            },
        }

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=payload,
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data
        # The error should mention insufficient data
        detail_str = str(data["detail"]).lower()
        assert "insufficient" in detail_str or "empty" in detail_str


# ---------------------------------------------------------------------------
# Test: All-failures returns 502 with structured error
# Requirement 6.4
# ---------------------------------------------------------------------------


class TestAnalysisFailure:
    """POST /api/avatars/{avatar_id}/analyze when all attempts fail returns 502."""

    @patch("app.routes.avatar_analysis.analyze_avatar")
    def test_analysis_error_returns_502(
        self, mock_analyze, admin_client, test_avatar, valid_payload
    ):
        """When analyze_avatar raises AnalysisError, endpoint returns 502."""
        mock_analyze.side_effect = AnalysisError(
            attempts=4,
            last_failure_reason="Timeout after 60s on fallback model anthropic/claude-sonnet-4-20250514",
        )

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=valid_payload,
        )

        assert response.status_code == 502

    @patch("app.routes.avatar_analysis.analyze_avatar")
    def test_502_contains_structured_error(
        self, mock_analyze, admin_client, test_avatar, valid_payload
    ):
        """502 response contains error, attempts, and last_failure_reason."""
        mock_analyze.side_effect = AnalysisError(
            attempts=4,
            last_failure_reason="Timeout after 60s on fallback model",
        )

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=valid_payload,
        )

        data = response.json()["detail"]
        assert data["error"] == "All analysis attempts failed"
        assert data["attempts"] == 4
        assert data["last_failure_reason"] == "Timeout after 60s on fallback model"


# ---------------------------------------------------------------------------
# Test: Unauthenticated request returns 303 (auth middleware redirect)
# Requirement 6.5
# ---------------------------------------------------------------------------


class TestUnauthenticated:
    """POST /api/avatars/{avatar_id}/analyze without auth returns 303 redirect."""

    def test_no_auth_token_returns_303(self, db, test_avatar, valid_payload):
        """Request without auth cookie gets redirected to login (303)."""
        from fastapi.testclient import TestClient
        from app.main import app
        from app.database import get_db

        def override_get_db():
            yield db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with TestClient(app, follow_redirects=False) as c:
                response = c.post(
                    f"/api/avatars/{test_avatar.id}/analyze",
                    json=valid_payload,
                )

            # Auth middleware returns 303 redirect to /login
            assert response.status_code == 303
            assert "/login" in response.headers.get("location", "")
        finally:
            app.dependency_overrides.clear()

    def test_non_superuser_returns_403(self, regular_client, test_avatar, valid_payload):
        """Authenticated non-superuser gets 403 Forbidden."""
        response = regular_client.post(
            f"/api/avatars/{test_avatar.id}/analyze",
            json=valid_payload,
        )

        assert response.status_code == 403
