"""Tests for app/routes/engineering_memory.py."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


@pytest.fixture
def public_client(db):
    """TestClient without auth — for public routes."""
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestGetReportIssue:
    """GET /report-issue — renders the form page."""

    def test_returns_200(self, public_client):
        resp = public_client.get("/report-issue")
        assert resp.status_code == 200

    def test_returns_html(self, public_client):
        resp = public_client.get("/report-issue")
        assert "text/html" in resp.headers["content-type"]


class TestPostReportIssue:
    """POST /api/report-issue — processes form submission."""

    def test_honeypot_rejects_bot(self, public_client):
        """If hidden 'website' field is filled, silently reject (bot)."""
        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Something broke",
                "where": "Dashboard",
                "expected": "It should work",
                "actual_result": "It crashed",
                "website": "http://spam.bot",  # honeypot filled
            },
        )
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @patch("app.services.engineering_memory.create_incident", new_callable=AsyncMock)
    def test_successful_submission(self, mock_create, public_client):
        """Valid submission calls create_incident and returns success."""
        import time
        mock_create.return_value = "fake-page-id-123"

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Button does not respond",
                "where": "Client portal settings page",
                "expected": "Button saves settings",
                "actual_result": "Nothing happens on click",
                "email": "reporter@example.com",
                "website": "",  # honeypot empty
                "form_ts": str(int(time.time()) - 10),  # opened 10s ago
                "human_check": "91",  # JS challenge answer
            },
        )
        assert resp.status_code == 200
        mock_create.assert_called_once()
        call_args = mock_create.call_args
        form_data = call_args[0][1]  # second positional arg
        assert form_data["what_happened"] == "Button does not respond"
        assert form_data["where"] == "Client portal settings page"
        assert form_data["email"] == "reporter@example.com"

    @patch("app.services.engineering_memory.create_incident", new_callable=AsyncMock)
    def test_notion_api_failure_shows_error(self, mock_create, public_client):
        """If Notion API fails, show user-friendly error."""
        import time
        mock_create.side_effect = Exception("Notion API timeout")

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Something broke",
                "where": "Dashboard",
                "expected": "It should work",
                "actual_result": "It crashed",
                "website": "",
                "form_ts": str(int(time.time()) - 10),
                "human_check": "91",
            },
        )
        assert resp.status_code == 200
        assert "Something went wrong" in resp.text or "error" in resp.text.lower()
