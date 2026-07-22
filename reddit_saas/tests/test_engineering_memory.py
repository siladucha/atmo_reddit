"""Tests for app/services/engineering_memory.py"""

import asyncio

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.engineering_memory import (
    create_incident,
    _truncate_title,
    _build_problem_text,
    _build_reporter,
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


class TestBuildReporter:
    def test_email_provided(self):
        assert _build_reporter({"email": "user@example.com"}) == "user@example.com"

    def test_empty_email(self):
        assert _build_reporter({"email": ""}) == "Client"

    def test_no_email_key(self):
        assert _build_reporter({}) == "Client"

    def test_whitespace_email(self):
        assert _build_reporter({"email": "   "}) == "Client"


class TestCreateIncident:
    def test_creates_incident_successfully(self):
        mock_db = MagicMock()
        # Mock get_setting to return token and database_id
        with patch("app.services.engineering_memory.get_setting") as mock_get_setting:
            mock_get_setting.side_effect = lambda db, key: {
                "notion_engineering_memory_token": "ntn_test_token",
                "notion_engineering_memory_database_id": "db-123-456",
            }.get(key, "")

            mock_response = MagicMock()
            mock_response.json.return_value = {"id": "page-abc-123"}
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                form_data = {
                    "what_happened": "Button is broken",
                    "where": "/admin/dashboard",
                    "expected": "Button should submit form",
                    "actual_result": "Nothing happens on click",
                    "email": "tester@example.com",
                }

                page_id = asyncio.run(create_incident(mock_db, form_data))

                assert page_id == "page-abc-123"
                mock_client.post.assert_called_once()

                # Verify the payload structure
                call_args = mock_client.post.call_args
                payload = call_args.kwargs.get("json") or call_args[1].get("json")
                props = payload["properties"]
                assert props["Status"]["select"]["name"] == "Reported"
                assert "Category" not in props
                assert props["Reporter"]["rich_text"][0]["text"]["content"] == "tester@example.com"

    def test_raises_on_missing_token(self):
        mock_db = MagicMock()
        with patch("app.services.engineering_memory.get_setting") as mock_get_setting:
            mock_get_setting.return_value = ""

            with pytest.raises(ValueError, match="token"):
                asyncio.run(create_incident(mock_db, {"what_happened": "test"}))

    def test_raises_on_missing_database_id(self):
        mock_db = MagicMock()
        with patch("app.services.engineering_memory.get_setting") as mock_get_setting:
            mock_get_setting.side_effect = lambda db, key: {
                "notion_engineering_memory_token": "token123",
                "notion_engineering_memory_database_id": "",
            }.get(key, "")

            with pytest.raises(ValueError, match="database ID"):
                asyncio.run(create_incident(mock_db, {"what_happened": "test"}))

    def test_reporter_defaults_to_client(self):
        mock_db = MagicMock()
        with patch("app.services.engineering_memory.get_setting") as mock_get_setting:
            mock_get_setting.side_effect = lambda db, key: {
                "notion_engineering_memory_token": "token",
                "notion_engineering_memory_database_id": "db-id",
            }.get(key, "")

            mock_response = MagicMock()
            mock_response.json.return_value = {"id": "page-xyz"}
            mock_response.raise_for_status = MagicMock()

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.post.return_value = mock_response
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=False)
                mock_client_cls.return_value = mock_client

                form_data = {
                    "what_happened": "Something",
                    "where": "Somewhere",
                    "expected": "A",
                    "actual_result": "B",
                }

                asyncio.run(create_incident(mock_db, form_data))

                call_args = mock_client.post.call_args
                payload = call_args.kwargs.get("json") or call_args[1].get("json")
                reporter = payload["properties"]["Reporter"]["rich_text"][0]["text"]["content"]
                assert reporter == "Client"
