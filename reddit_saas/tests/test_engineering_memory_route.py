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


class TestBugConditionExploration:
    """Bug condition exploration tests — EXPECTED TO FAIL on unfixed code.

    These tests encode the CORRECT behavior described in the bugfix spec.
    Failure confirms the bugs exist in the current implementation.
    When the fix is applied, these tests should pass.

    **Validates: Requirements 1.1, 1.4**
    """

    def test_1a_optional_expected_field_accepted(self, public_client):
        """Bug 1: Empty 'expected' field should be accepted (field is optional).

        Currently FAILS because server rejects with "'Expected?' is required".
        """
        import time

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Login button unresponsive after page load",
                "where": "https://app.example.com/login",
                "expected": "",  # intentionally empty — should be optional
                "actual_result": "Button does not respond to clicks for 5 seconds",
                "email": "tester@example.com",
                "reporter_role": "client_admin",
                "reporter_name": "Test User",
                "environment": "prod",
                "website": "",  # honeypot empty
                "form_ts": str(int(time.time()) - 10),  # opened 10s ago
                "human_check": "91",  # JS challenge answer (7×13)
            },
        )
        assert resp.status_code == 200
        # The validation error for 'Expected?' should NOT appear — field is optional
        assert "'Expected?' is required" not in resp.text
        # Submission should succeed (show success confirmation, not re-render form with errors)
        assert "success" in resp.text.lower() or "bug_id" in resp.text.lower() or "BUG-" in resp.text

    def test_1b_source_url_populated_from_where_field(self, public_client, db):
        """Bug 4: source_url should be populated from the 'where' form field.

        Currently FAILS because route never puts 'source_url' in form_data dict,
        so BugReport.source_url is always NULL even when 'where' is filled.
        """
        import time
        from app.models.bug_report import BugReport

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Settings page crashes on save",
                "where": "https://app.example.com/settings",
                "expected": "Settings saved successfully",
                "actual_result": "500 error on save",
                "email": "reporter@test.com",
                "reporter_role": "client_admin",
                "reporter_name": "QA Reporter",
                "environment": "staging",
                "website": "",  # honeypot empty
                "form_ts": str(int(time.time()) - 10),  # opened 10s ago
                "human_check": "91",  # JS challenge answer (7×13)
            },
        )
        assert resp.status_code == 200

        # Query the most recently created bug report
        bug = db.query(BugReport).order_by(BugReport.id.desc()).first()
        assert bug is not None, "BugReport should have been created"

        # source_url should be populated from the 'where' field
        assert bug.source_url == "https://app.example.com/settings", (
            f"Expected source_url='https://app.example.com/settings', got '{bug.source_url}'"
        )

    def test_1c_reporter_email_stored_separately(self, public_client, db):
        """Bug 4: reporter_email should be stored as a separate field.

        Currently FAILS because the reporter_email column doesn't exist on
        the BugReport model — email is only embedded in the 'reporter' string.
        """
        import time
        from app.models.bug_report import BugReport

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Dashboard widget not loading",
                "where": "https://app.example.com/dashboard",
                "expected": "Widget loads with data",
                "actual_result": "Spinner shown indefinitely",
                "email": "reporter@test.com",
                "reporter_role": "client_viewer",
                "reporter_name": "Email Test User",
                "environment": "prod",
                "website": "",  # honeypot empty
                "form_ts": str(int(time.time()) - 10),  # opened 10s ago
                "human_check": "91",  # JS challenge answer (7×13)
            },
        )
        assert resp.status_code == 200

        # Query the most recently created bug report
        bug = db.query(BugReport).order_by(BugReport.id.desc()).first()
        assert bug is not None, "BugReport should have been created"

        # reporter_email should be stored as a separate field
        assert hasattr(bug, "reporter_email"), (
            "BugReport model should have a 'reporter_email' column"
        )
        assert bug.reporter_email == "reporter@test.com", (
            f"Expected reporter_email='reporter@test.com', got '{bug.reporter_email}'"
        )


class TestPreservation:
    """Preservation tests — assert CURRENT behavior that must be preserved through the fix.

    All tests PASS on unfixed code. They capture baseline behavior for:
    - Form submission with expected field filled → expected value in problem blob
    - Anti-bot protection (honeypot, JS challenge, timing) → silent 200 rejection
    - Required field validation (what_happened, where, actual_result) → error messages

    **Validates: Requirements 3.1, 3.2, 3.5, 3.6, 3.7**
    """

    def test_2a_expected_field_included_in_problem_when_filled(self, public_client, db):
        """Preservation: when 'expected' IS filled, its value appears in problem text.

        **Validates: Requirements 3.1, 3.7**
        """
        import time
        from app.models.bug_report import BugReport

        # Count existing bugs before submission
        count_before = db.query(BugReport).count()

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Save button not working on settings page",
                "where": "https://app.example.com/settings",
                "expected": "Button should save",
                "actual_result": "Nothing happens when clicking save",
                "email": "qa@test.com",
                "reporter_role": "client_admin",
                "reporter_name": "QA Tester",
                "environment": "prod",
                "website": "",  # honeypot empty
                "form_ts": str(int(time.time()) - 10),  # opened 10s ago
                "human_check": "91",  # JS challenge answer (7×13)
            },
        )
        assert resp.status_code == 200

        # Verify a new bug was created
        count_after = db.query(BugReport).count()
        assert count_after > count_before, "A new BugReport should have been created"

        # Query the newly created bug report (the one with our specific title)
        bug = db.query(BugReport).filter(
            BugReport.title.contains("Save button not working")
        ).order_by(BugReport.id.desc()).first()
        assert bug is not None, "BugReport with our title should have been created"

        # The expected value should appear in the problem text blob
        assert "Expected: Button should save" in bug.problem, (
            f"Expected 'Expected: Button should save' in problem text, got:\n{bug.problem}"
        )

    def test_2b_honeypot_filled_returns_200_success(self, public_client):
        """Preservation: honeypot filled → 200 success page (silent bot rejection).

        **Validates: Requirements 3.2**
        """
        import time

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Something broke",
                "where": "Dashboard",
                "expected": "It should work",
                "actual_result": "It crashed",
                "email": "bot@spam.com",
                "website": "http://spam.bot",  # honeypot FILLED — bot detected
                "form_ts": str(int(time.time()) - 10),
                "human_check": "91",
            },
        )
        # Silent rejection: returns 200 success page (no error shown to bot)
        assert resp.status_code == 200
        # Should NOT contain validation error messages
        assert "is required" not in resp.text

    def test_2c_js_challenge_wrong_returns_200_success(self, public_client):
        """Preservation: wrong JS challenge answer → 200 success page (silent bot rejection).

        **Validates: Requirements 3.2**
        """
        import time

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Something broke",
                "where": "Dashboard",
                "expected": "It should work",
                "actual_result": "It crashed",
                "email": "user@test.com",
                "website": "",  # honeypot empty
                "form_ts": str(int(time.time()) - 10),
                "human_check": "wrong",  # JS challenge WRONG — bot detected
            },
        )
        # Silent rejection: returns 200 success page (no error shown to bot)
        assert resp.status_code == 200
        # Should NOT contain validation error messages
        assert "is required" not in resp.text

    def test_2d_timing_too_fast_returns_200_success(self, public_client):
        """Preservation: form submitted too fast (<3s) → 200 success page (silent bot rejection).

        **Validates: Requirements 3.2**
        """
        import time

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Something broke",
                "where": "Dashboard",
                "expected": "It should work",
                "actual_result": "It crashed",
                "email": "user@test.com",
                "website": "",  # honeypot empty
                "form_ts": str(int(time.time()) - 1),  # opened only 1s ago — too fast
                "human_check": "91",
            },
        )
        # Silent rejection: returns 200 success page (no error shown to bot)
        assert resp.status_code == 200
        # Should NOT contain validation error messages
        assert "is required" not in resp.text

    def test_2e_empty_what_happened_returns_error(self, public_client):
        """Preservation: empty what_happened → error message returned.

        **Validates: Requirements 3.5**
        """
        import time

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "",  # EMPTY — required field
                "where": "Dashboard",
                "expected": "It should work",
                "actual_result": "It crashed",
                "email": "user@test.com",
                "website": "",
                "form_ts": str(int(time.time()) - 10),
                "human_check": "91",
            },
        )
        assert resp.status_code == 200
        # Template HTML-encodes single quotes as &#39;
        assert "What happened?" in resp.text and "is required" in resp.text

    def test_2f_empty_where_returns_error(self, public_client):
        """Preservation: empty where → error message returned.

        **Validates: Requirements 3.5**
        """
        import time

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Something broke",
                "where": "",  # EMPTY — required field
                "expected": "It should work",
                "actual_result": "It crashed",
                "email": "user@test.com",
                "website": "",
                "form_ts": str(int(time.time()) - 10),
                "human_check": "91",
            },
        )
        assert resp.status_code == 200
        # Template HTML-encodes single quotes as &#39;
        assert "Where?" in resp.text and "is required" in resp.text

    def test_2g_empty_actual_result_returns_error(self, public_client):
        """Preservation: empty actual_result → error message returned.

        **Validates: Requirements 3.5**
        """
        import time

        resp = public_client.post(
            "/api/report-issue",
            data={
                "what_happened": "Something broke",
                "where": "Dashboard",
                "expected": "It should work",
                "actual_result": "",  # EMPTY — required field
                "email": "user@test.com",
                "website": "",
                "form_ts": str(int(time.time()) - 10),
                "human_check": "91",
            },
        )
        assert resp.status_code == 200
        # Template HTML-encodes single quotes as &#39;
        assert "Actual result?" in resp.text and "is required" in resp.text
