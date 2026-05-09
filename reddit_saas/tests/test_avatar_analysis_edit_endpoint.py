"""Unit tests for the avatar analysis edit submission endpoint.

Tests cover:
- Valid edit returns 201 with {"status": "stored", "id": "..."}
- Identical edit returns 422 with "No changes detected"
- Unauthenticated request returns 303 redirect (auth middleware)
- Non-existent avatar returns 404

Requirements: 9.1, 9.2, 9.3, 9.4
"""

import uuid
from unittest.mock import patch, MagicMock

import pytest

from app.models.avatar import Avatar


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_avatar(db):
    """Create a real avatar in the DB and return it."""
    avatar = Avatar(
        reddit_username="edit_test_avatar",
        active=True,
        voice_profile_md="A helpful tech enthusiast",
    )
    db.add(avatar)
    db.flush()
    return avatar


@pytest.fixture
def valid_edit_payload():
    """A valid AnalysisEditSubmission payload with distinct dicts."""
    return {
        "llm_output": {
            "basic": {"username": "edit_test_avatar", "account_age_days": 365},
            "summary": "Original LLM summary of the avatar behavior.",
        },
        "human_edited": {
            "basic": {"username": "edit_test_avatar", "account_age_days": 365},
            "summary": "Corrected human summary with better insights.",
        },
    }


@pytest.fixture
def identical_edit_payload():
    """An AnalysisEditSubmission payload where both dicts are identical."""
    same_data = {
        "basic": {"username": "edit_test_avatar", "account_age_days": 365},
        "summary": "Identical summary for both fields.",
    }
    return {
        "llm_output": same_data,
        "human_edited": same_data,
    }


# ---------------------------------------------------------------------------
# Test: Valid edit returns 201
# Requirement 9.1, 9.2
# ---------------------------------------------------------------------------


class TestValidEditSubmission:
    """POST /api/avatars/{avatar_id}/analysis-edits with valid distinct dicts returns 201."""

    @patch("app.routes.avatar_analysis.store_edit")
    def test_returns_201_with_stored_status(
        self, mock_store, admin_client, test_avatar, valid_edit_payload
    ):
        """Valid edit submission returns 201 with status and id."""
        fake_record = MagicMock()
        fake_record.id = uuid.uuid4()
        mock_store.return_value = fake_record

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analysis-edits",
            json=valid_edit_payload,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "stored"
        assert data["id"] == str(fake_record.id)

    @patch("app.routes.avatar_analysis.store_edit")
    def test_calls_store_edit_with_correct_args(
        self, mock_store, admin_client, db, test_avatar, valid_edit_payload
    ):
        """The endpoint passes db, avatar_id, llm_output, and human_edited to store_edit."""
        fake_record = MagicMock()
        fake_record.id = uuid.uuid4()
        mock_store.return_value = fake_record

        admin_client.post(
            f"/api/avatars/{test_avatar.id}/analysis-edits",
            json=valid_edit_payload,
        )

        mock_store.assert_called_once()
        call_args = mock_store.call_args
        # Positional args: db, avatar_id, llm_output, human_edited
        assert call_args[0][1] == test_avatar.id
        assert call_args[0][2] == valid_edit_payload["llm_output"]
        assert call_args[0][3] == valid_edit_payload["human_edited"]


# ---------------------------------------------------------------------------
# Test: Identical edit returns 422
# Requirement 9.3
# ---------------------------------------------------------------------------


class TestIdenticalEditRejection:
    """POST /api/avatars/{avatar_id}/analysis-edits with identical dicts returns 422."""

    @patch("app.routes.avatar_analysis.store_edit")
    def test_identical_edit_returns_422(
        self, mock_store, admin_client, test_avatar, identical_edit_payload
    ):
        """When store_edit raises ValueError, endpoint returns 422."""
        mock_store.side_effect = ValueError("No changes detected")

        response = admin_client.post(
            f"/api/avatars/{test_avatar.id}/analysis-edits",
            json=identical_edit_payload,
        )

        assert response.status_code == 422
        assert "No changes detected" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Test: Unauthenticated request returns 303 (auth middleware redirect)
# Requirement 9.4
# ---------------------------------------------------------------------------


class TestUnauthenticated:
    """POST /api/avatars/{avatar_id}/analysis-edits without auth returns 303 redirect."""

    def test_no_auth_token_returns_303(self, db, test_avatar, valid_edit_payload):
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
                    f"/api/avatars/{test_avatar.id}/analysis-edits",
                    json=valid_edit_payload,
                )

            # Auth middleware returns 303 redirect to /login
            assert response.status_code == 303
            assert "/login" in response.headers.get("location", "")
        finally:
            app.dependency_overrides.clear()

    def test_non_superuser_returns_403(self, regular_client, test_avatar, valid_edit_payload):
        """Authenticated non-superuser gets 403 Forbidden."""
        response = regular_client.post(
            f"/api/avatars/{test_avatar.id}/analysis-edits",
            json=valid_edit_payload,
        )

        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Test: Non-existent avatar returns 404
# Requirement 9.1
# ---------------------------------------------------------------------------


class TestNonExistentAvatar:
    """POST /api/avatars/{avatar_id}/analysis-edits with non-existent avatar returns 404."""

    def test_nonexistent_avatar_returns_404(self, admin_client, valid_edit_payload):
        """A random UUID that doesn't exist in the DB returns 404."""
        fake_id = uuid.uuid4()

        response = admin_client.post(
            f"/api/avatars/{fake_id}/analysis-edits",
            json=valid_edit_payload,
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()
