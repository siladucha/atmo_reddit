"""Tests for app/services/engineering_memory.py"""

import pytest
from unittest.mock import MagicMock, patch

from app.services.engineering_memory import (
    _build_problem_text,
    _build_reporter,
    _truncate_title,
    create_incident,
)


class TestTruncateTitle:
    def test_short_title_unchanged(self):
        assert _truncate_title("Something broke") == "Something broke"

    def test_exactly_100_chars(self):
        title = "x" * 100
        assert _truncate_title(title) == title

    def test_long_title_truncates_at_sentence(self):
        title = "This is the first sentence. This is more text that goes beyond one hundred characters and should not appear."
        result = _truncate_title(title)
        assert result == "This is the first sentence."
        assert len(result) <= 100

    def test_long_title_no_sentence_boundary_hard_truncates(self):
        title = "A" * 150
        result = _truncate_title(title)
        assert len(result) == 100
        assert result.endswith("...")

    def test_strips_whitespace(self):
        assert _truncate_title("  hello  ") == "hello"

    def test_exclamation_mark_as_sentence_end(self):
        title = "Something exploded! And then more text goes here that is over one hundred characters for sure definitely."
        result = _truncate_title(title)
        assert result == "Something exploded!"


class TestBuildProblemText:
    def test_all_fields(self):
        form_data = {
            "what_happened": "It broke",
            "where": "Dashboard",
            "expected": "It should work",
            "actual_result": "500 error",
        }
        result = _build_problem_text(form_data)
        assert "What happened: It broke" in result
        assert "Where: Dashboard" in result
        assert "Expected: It should work" in result
        assert "Actual result: 500 error" in result

    def test_with_screenshot(self):
        form_data = {
            "what_happened": "Bug",
            "where": "Page",
            "expected": "X",
            "actual_result": "Y",
            "screenshot_url": "/static/uploads/bugs/abc123.png",
        }
        result = _build_problem_text(form_data)
        assert "[Screenshot: /static/uploads/bugs/abc123.png]" in result

    def test_empty_fields_skipped(self):
        form_data = {
            "what_happened": "Bug",
            "where": "",
            "expected": "X",
            "actual_result": "",
        }
        result = _build_problem_text(form_data)
        assert "Where:" not in result
        assert "Actual result:" not in result

    def test_no_screenshot_when_missing(self):
        form_data = {"what_happened": "Bug", "where": "Page", "expected": "X", "actual_result": "Y"}
        result = _build_problem_text(form_data)
        assert "Screenshot" not in result


class TestBuildReporter:
    def test_email_only(self):
        assert _build_reporter({"email": "user@example.com"}) == "user@example.com"

    def test_name_and_email(self):
        result = _build_reporter({"email": "user@example.com", "reporter_name": "Alice"})
        assert "Alice" in result
        assert "user@example.com" in result

    def test_name_email_and_role(self):
        result = _build_reporter({
            "email": "user@example.com",
            "reporter_name": "Alice",
            "reporter_role": "QA",
        })
        assert "Alice" in result
        assert "user@example.com" in result
        assert "[QA]" in result

    def test_empty_email_defaults_to_client(self):
        assert _build_reporter({"email": ""}) == "Client"

    def test_no_email_key_defaults_to_client(self):
        assert _build_reporter({}) == "Client"

    def test_whitespace_email_defaults_to_client(self):
        assert _build_reporter({"email": "   "}) == "Client"


class TestCreateIncident:
    def _make_db(self):
        """Return a mock DB session that satisfies create_incident."""
        mock_db = MagicMock()
        # _get_next_bug_id calls db.execute(...).scalar() — return None → BUG-001
        mock_db.execute.return_value.scalar.return_value = None
        # db.refresh() sets attributes on the bug — patch it as no-op
        mock_db.refresh = MagicMock()
        mock_db.commit = MagicMock()
        return mock_db

    def test_creates_bug_report(self):
        mock_db = self._make_db()
        form_data = {
            "what_happened": "Button is broken",
            "where": "/admin/dashboard",
            "expected": "Button should submit form",
            "actual_result": "Nothing happens on click",
            "email": "tester@example.com",
        }
        result = create_incident(mock_db, form_data)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        # The added object should be a BugReport with correct fields
        bug = mock_db.add.call_args[0][0]
        assert bug.status == "Reported"
        assert bug.bug_id == "BUG-001"
        assert "Button is broken" in bug.title
        assert "tester@example.com" in bug.reporter

    def test_reporter_defaults_to_client(self):
        mock_db = self._make_db()
        form_data = {
            "what_happened": "Something",
            "where": "Somewhere",
            "expected": "A",
            "actual_result": "B",
        }
        create_incident(mock_db, form_data)
        bug = mock_db.add.call_args[0][0]
        assert bug.reporter == "Client"

    def test_screenshot_url_stored(self):
        mock_db = self._make_db()
        form_data = {
            "what_happened": "Visual bug",
            "screenshot_url": "/static/uploads/bugs/test.png",
        }
        create_incident(mock_db, form_data)
        bug = mock_db.add.call_args[0][0]
        assert bug.screenshot_url == "/static/uploads/bugs/test.png"
        assert "[Screenshot: /static/uploads/bugs/test.png]" in bug.problem

    def test_sequential_bug_id(self):
        mock_db = self._make_db()
        mock_db.execute.return_value.scalar.return_value = "BUG-005"
        create_incident(mock_db, {"what_happened": "test"})
        bug = mock_db.add.call_args[0][0]
        assert bug.bug_id == "BUG-006"

    def test_environment_defaults_to_prod(self):
        mock_db = self._make_db()
        create_incident(mock_db, {"what_happened": "test"})
        bug = mock_db.add.call_args[0][0]
        assert bug.environment == "prod"

    def test_environment_from_form(self):
        mock_db = self._make_db()
        create_incident(mock_db, {"what_happened": "test", "environment": "staging"})
        bug = mock_db.add.call_args[0][0]
        assert bug.environment == "staging"
