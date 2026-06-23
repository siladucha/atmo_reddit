"""Tests for rule_extractor service.

Tests Pydantic models, LLM response parsing, extraction logic,
and batch refresh behavior with mocks for external dependencies.
"""

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

from prawcore.exceptions import Forbidden, NotFound, Redirect
import pytest
from pydantic import ValidationError

from app.services.rule_extractor import (
    ExtractedRule,
    ExtractionResult,
    _ExtractionFailure,
    _fetch_sidebar_content,
    _parse_llm_response,
    extract_subreddit_rules,
    refresh_all_subreddit_rules,
    MAX_RULES_PER_SUBREDDIT,
    MAX_SIDEBAR_CHARS,
    RULE_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Pydantic Model Tests
# ---------------------------------------------------------------------------


class TestExtractedRule:
    """Tests for ExtractedRule Pydantic model."""

    def test_valid_rule(self):
        rule = ExtractedRule(
            category="min_karma",
            description="Must have 500 comment karma",
            threshold_value="500",
        )
        assert rule.category == "min_karma"
        assert rule.description == "Must have 500 comment karma"
        assert rule.threshold_value == "500"

    def test_null_threshold(self):
        rule = ExtractedRule(
            category="no_self_promo",
            description="No self-promotion allowed",
            threshold_value=None,
        )
        assert rule.threshold_value is None

    def test_missing_threshold_defaults_none(self):
        rule = ExtractedRule(
            category="content_restriction",
            description="No memes allowed",
        )
        assert rule.threshold_value is None

    def test_description_truncation(self):
        long_desc = "A" * 250
        rule = ExtractedRule(category="other", description=long_desc)
        assert len(rule.description) == 200

    def test_description_at_limit(self):
        desc_200 = "B" * 200
        rule = ExtractedRule(category="other", description=desc_200)
        assert len(rule.description) == 200

    def test_all_valid_categories(self):
        for category in RULE_CATEGORIES:
            rule = ExtractedRule(category=category, description="test")
            assert rule.category == category

    def test_invalid_category_rejected(self):
        with pytest.raises(ValidationError):
            ExtractedRule(category="invalid_category", description="test")

    def test_model_dump(self):
        rule = ExtractedRule(
            category="min_account_age",
            description="30 day minimum account age",
            threshold_value="30 days",
        )
        dumped = rule.model_dump()
        assert dumped == {
            "category": "min_account_age",
            "description": "30 day minimum account age",
            "threshold_value": "30 days",
        }


class TestExtractionResult:
    """Tests for ExtractionResult Pydantic model."""

    def test_valid_result(self):
        result = ExtractionResult(
            rules=[
                {"category": "min_karma", "description": "Need 500 karma", "threshold_value": "500"},
                {"category": "no_self_promo", "description": "No promo", "threshold_value": None},
            ]
        )
        assert len(result.rules) == 2
        assert result.rules[0].category == "min_karma"

    def test_empty_rules(self):
        result = ExtractionResult(rules=[])
        assert len(result.rules) == 0

    def test_rules_capped_at_20(self):
        rules = [
            {"category": "other", "description": f"Rule {i}", "threshold_value": None}
            for i in range(25)
        ]
        result = ExtractionResult(rules=rules)
        assert len(result.rules) == MAX_RULES_PER_SUBREDDIT

    def test_exactly_20_rules_not_trimmed(self):
        rules = [
            {"category": "other", "description": f"Rule {i}", "threshold_value": None}
            for i in range(20)
        ]
        result = ExtractionResult(rules=rules)
        assert len(result.rules) == 20


# ---------------------------------------------------------------------------
# LLM Response Parsing Tests
# ---------------------------------------------------------------------------


class TestParseLlmResponse:
    """Tests for _parse_llm_response function."""

    def test_parse_json_array(self):
        response = json.dumps([
            {"category": "min_karma", "description": "Need 100 karma", "threshold_value": "100"}
        ])
        result = _parse_llm_response(response)
        assert len(result.rules) == 1
        assert result.rules[0].category == "min_karma"

    def test_parse_json_object_with_rules_key(self):
        response = json.dumps({
            "rules": [
                {"category": "no_self_promo", "description": "No ads", "threshold_value": None}
            ]
        })
        result = _parse_llm_response(response)
        assert len(result.rules) == 1

    def test_parse_markdown_code_block(self):
        response = '```json\n[{"category": "required_flair", "description": "Must use flair", "threshold_value": null}]\n```'
        result = _parse_llm_response(response)
        assert len(result.rules) == 1
        assert result.rules[0].category == "required_flair"

    def test_parse_generic_code_block(self):
        response = '```\n[{"category": "other", "description": "Test", "threshold_value": null}]\n```'
        result = _parse_llm_response(response)
        assert len(result.rules) == 1

    def test_parse_empty_array(self):
        result = _parse_llm_response("[]")
        assert len(result.rules) == 0

    def test_parse_with_surrounding_text(self):
        response = 'Here are the rules I found:\n[{"category": "min_karma", "description": "500 karma required", "threshold_value": "500"}]\nEnd of rules.'
        result = _parse_llm_response(response)
        assert len(result.rules) == 1

    def test_parse_empty_string_raises(self):
        with pytest.raises(ValueError, match="Empty LLM response"):
            _parse_llm_response("")

    def test_parse_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Empty LLM response"):
            _parse_llm_response("   \n  ")

    def test_parse_invalid_json_raises(self):
        with pytest.raises(ValueError):
            _parse_llm_response("This is not JSON at all")

    def test_parse_invalid_category_raises(self):
        """Invalid category in data should raise ValidationError via Pydantic."""
        response = json.dumps([
            {"category": "bad_category", "description": "test", "threshold_value": None}
        ])
        with pytest.raises(ValidationError):
            _parse_llm_response(response)

    def test_parse_multiple_rules(self):
        rules = [
            {"category": "min_karma", "description": "500 karma", "threshold_value": "500"},
            {"category": "min_account_age", "description": "30 days old", "threshold_value": "30 days"},
            {"category": "no_self_promo", "description": "No promo", "threshold_value": None},
            {"category": "posting_frequency_limit", "description": "Max 3/day", "threshold_value": "3"},
        ]
        result = _parse_llm_response(json.dumps(rules))
        assert len(result.rules) == 4
        assert result.rules[0].threshold_value == "500"
        assert result.rules[3].category == "posting_frequency_limit"


# ---------------------------------------------------------------------------
# extract_subreddit_rules Tests (with mocks)
# ---------------------------------------------------------------------------


class TestExtractSubredditRules:
    """Tests for extract_subreddit_rules with mocked PRAW and LLM."""

    @patch("app.services.rule_extractor.call_llm")
    @patch("app.services.rule_extractor._fetch_sidebar_content")
    def test_success(self, mock_fetch, mock_llm):
        mock_fetch.return_value = "Rules: minimum 500 karma required"
        mock_llm.return_value = {
            "content": json.dumps([
                {"category": "min_karma", "description": "500 karma required", "threshold_value": "500"}
            ]),
            "input_tokens": 100,
            "output_tokens": 50,
            "cost_usd": 0.001,
            "duration_ms": 500,
            "model": "gemini/gemini-2.0-flash",
        }

        result = extract_subreddit_rules("sysadmin")
        assert isinstance(result, ExtractionResult)
        assert len(result.rules) == 1
        assert result.rules[0].category == "min_karma"
        mock_llm.assert_called_once()

    @patch("app.services.rule_extractor._fetch_sidebar_content")
    def test_no_content_returns_none(self, mock_fetch):
        mock_fetch.return_value = None
        result = extract_subreddit_rules("private_sub")
        assert result is None

    @patch("app.services.rule_extractor.time.sleep")
    @patch("app.services.rule_extractor.call_llm")
    @patch("app.services.rule_extractor._fetch_sidebar_content")
    def test_retry_on_first_failure(self, mock_fetch, mock_llm, mock_sleep):
        mock_fetch.return_value = "Some sidebar text"
        # First call fails, second succeeds
        mock_llm.side_effect = [
            {"content": "invalid json", "input_tokens": 0, "output_tokens": 0, "cost_usd": 0, "duration_ms": 0, "model": "gemini/gemini-2.0-flash"},
            {"content": json.dumps([{"category": "other", "description": "test rule", "threshold_value": None}]), "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "duration_ms": 500, "model": "gemini/gemini-2.0-flash"},
        ]

        result = extract_subreddit_rules("test_sub")
        assert isinstance(result, ExtractionResult)
        assert len(result.rules) == 1
        assert mock_llm.call_count == 2
        mock_sleep.assert_called_once_with(5)  # LLM_RETRY_DELAY_SECONDS

    @patch("app.services.rule_extractor.time.sleep")
    @patch("app.services.rule_extractor.call_llm")
    @patch("app.services.rule_extractor._fetch_sidebar_content")
    def test_both_attempts_fail_returns_extraction_failure(self, mock_fetch, mock_llm, mock_sleep):
        mock_fetch.return_value = "Some sidebar text"
        mock_llm.return_value = {
            "content": "not json at all",
            "input_tokens": 0,
            "output_tokens": 0,
            "cost_usd": 0,
            "duration_ms": 0,
            "model": "gemini/gemini-2.0-flash",
        }

        result = extract_subreddit_rules("test_sub")
        assert isinstance(result, _ExtractionFailure)
        assert "No JSON array" in result.reason or "Cannot" in result.reason


# ---------------------------------------------------------------------------
# _fetch_sidebar_content Tests (with mocks)
# ---------------------------------------------------------------------------


class TestFetchSidebarContent:
    """Tests for _fetch_sidebar_content with mocked PRAW."""

    @patch("app.services.rule_extractor.get_reddit_client")
    def test_sidebar_only(self, mock_get_client):
        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_subreddit.description = "This is the sidebar with rules."
        mock_wiki = MagicMock()
        mock_wiki.content_md = ""
        mock_subreddit.wiki.__getitem__ = MagicMock(side_effect=NotFound(MagicMock()))
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_get_client.return_value = mock_reddit


        result = _fetch_sidebar_content("test_sub")
        assert result == "This is the sidebar with rules."

    @patch("app.services.rule_extractor.get_reddit_client")
    def test_sidebar_and_wiki(self, mock_get_client):
        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_subreddit.description = "Sidebar text"
        mock_wiki_page = MagicMock()
        mock_wiki_page.content_md = "Wiki rules text"
        mock_subreddit.wiki.__getitem__ = MagicMock(return_value=mock_wiki_page)
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_get_client.return_value = mock_reddit

        result = _fetch_sidebar_content("test_sub")
        assert "Sidebar text" in result
        assert "Wiki rules text" in result

    @patch("app.services.rule_extractor.get_reddit_client")
    def test_truncation_at_4000_chars(self, mock_get_client):
        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_subreddit.description = "X" * 5000
        mock_subreddit.wiki.__getitem__ = MagicMock(side_effect=NotFound(MagicMock()))
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_get_client.return_value = mock_reddit

        result = _fetch_sidebar_content("test_sub")
        assert len(result) == MAX_SIDEBAR_CHARS

    @patch("app.services.rule_extractor.get_reddit_client")
    def test_empty_sidebar_and_no_wiki_returns_none(self, mock_get_client):
        mock_reddit = MagicMock()
        mock_subreddit = MagicMock()
        mock_subreddit.description = ""
        mock_subreddit.wiki.__getitem__ = MagicMock(side_effect=NotFound(MagicMock()))
        mock_reddit.subreddit.return_value = mock_subreddit
        mock_get_client.return_value = mock_reddit

        result = _fetch_sidebar_content("test_sub")
        assert result is None

    @patch("app.services.rule_extractor.get_reddit_client")
    def test_forbidden_subreddit_returns_none(self, mock_get_client):
        mock_reddit = MagicMock()
        mock_reddit.subreddit.side_effect = Forbidden(MagicMock())
        mock_get_client.return_value = mock_reddit

        result = _fetch_sidebar_content("private_sub")
        assert result is None


# ---------------------------------------------------------------------------
# refresh_all_subreddit_rules Tests (with DB + mocks)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("os").environ.get("RUN_DB_TESTS"),
    reason="Requires local DB with risk_profile migrations applied (set RUN_DB_TESTS=1)"
)

class TestRefreshAllSubredditRules:
    """Tests for refresh_all_subreddit_rules batch function."""

    @patch("app.services.rule_extractor.time.sleep")
    @patch("app.services.rule_extractor.extract_subreddit_rules")
    def test_success_updates_profile(self, mock_extract, mock_sleep, db):
        """Successful extraction updates the profile correctly."""
        from app.models.subreddit import Subreddit, ClientSubredditAssignment
        from app.models.subreddit_risk_profile import SubredditRiskProfile
        from app.models.client import Client

        # Create test data
        client = Client(client_name="Test Client", brand_name="TestBrand")
        db.add(client)
        db.flush()

        subreddit = Subreddit(subreddit_name="sysadmin", is_active=True)
        db.add(subreddit)
        db.flush()

        assignment = ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=subreddit.id,
            is_active=True,
        )
        db.add(assignment)
        db.flush()

        # Mock extraction success
        mock_extract.return_value = ExtractionResult(
            rules=[
                ExtractedRule(category="min_karma", description="Need 500", threshold_value="500")
            ]
        )

        result = refresh_all_subreddit_rules(db)

        assert result["total"] == 1
        assert result["success"] == 1
        assert result["failures"] == 0

        # Verify profile was created/updated
        profile = db.query(SubredditRiskProfile).filter(
            SubredditRiskProfile.subreddit_id == subreddit.id
        ).first()
        assert profile is not None
        assert profile.extraction_status == "success"
        assert len(profile.extracted_rules) == 1
        assert profile.extracted_rules[0]["category"] == "min_karma"
        assert profile.last_rule_extraction_at is not None

    @patch("app.services.rule_extractor.time.sleep")
    @patch("app.services.rule_extractor.extract_subreddit_rules")
    def test_no_content_marks_profile(self, mock_extract, mock_sleep, db):
        """No content returns marks profile as no_content."""
        from app.models.subreddit import Subreddit, ClientSubredditAssignment
        from app.models.subreddit_risk_profile import SubredditRiskProfile
        from app.models.client import Client

        client = Client(client_name="Test Client", brand_name="TestBrand")
        db.add(client)
        db.flush()

        subreddit = Subreddit(subreddit_name="private_sub", is_active=True)
        db.add(subreddit)
        db.flush()

        assignment = ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=subreddit.id,
            is_active=True,
        )
        db.add(assignment)
        db.flush()

        mock_extract.return_value = None

        result = refresh_all_subreddit_rules(db)

        assert result["no_content"] == 1

        profile = db.query(SubredditRiskProfile).filter(
            SubredditRiskProfile.subreddit_id == subreddit.id
        ).first()
        assert profile.extraction_status == "no_content"

    @patch("app.services.rule_extractor.time.sleep")
    @patch("app.services.rule_extractor.extract_subreddit_rules")
    def test_extraction_failure_preserves_previous_rules(self, mock_extract, mock_sleep, db):
        """Extraction failure preserves existing rules (Req 1.8)."""
        from app.models.subreddit import Subreddit, ClientSubredditAssignment
        from app.models.subreddit_risk_profile import SubredditRiskProfile
        from app.models.client import Client

        client = Client(client_name="Test Client", brand_name="TestBrand")
        db.add(client)
        db.flush()

        subreddit = Subreddit(subreddit_name="failing_sub", is_active=True)
        db.add(subreddit)
        db.flush()

        # Pre-existing profile with rules
        existing_rules = [
            {"category": "min_karma", "description": "Old rule", "threshold_value": "100"}
        ]
        profile = SubredditRiskProfile(
            subreddit_id=subreddit.id,
            extracted_rules=existing_rules,
            extraction_status="success",
        )
        db.add(profile)
        db.flush()

        assignment = ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=subreddit.id,
            is_active=True,
        )
        db.add(assignment)
        db.flush()

        # Mock extraction failure
        mock_extract.return_value = _ExtractionFailure(reason="LLM returned garbage")

        result = refresh_all_subreddit_rules(db)

        assert result["failures"] == 1

        # Rules should be preserved
        db.refresh(profile)
        assert profile.extraction_status == "extraction_failed"
        assert profile.extracted_rules == existing_rules  # Preserved!

    @patch("app.services.rule_extractor.time.sleep")
    @patch("app.services.rule_extractor.extract_subreddit_rules")
    def test_only_active_assignments_processed(self, mock_extract, mock_sleep, db):
        """Only subreddits with active assignments are processed."""
        from app.models.subreddit import Subreddit, ClientSubredditAssignment
        from app.models.client import Client

        client = Client(client_name="Test Client", brand_name="TestBrand")
        db.add(client)
        db.flush()

        active_sub = Subreddit(subreddit_name="active_sub", is_active=True)
        inactive_sub = Subreddit(subreddit_name="inactive_sub", is_active=True)
        db.add_all([active_sub, inactive_sub])
        db.flush()

        # Active assignment
        db.add(ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=active_sub.id,
            is_active=True,
        ))
        # Inactive assignment
        db.add(ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=inactive_sub.id,
            is_active=False,
        ))
        db.flush()

        mock_extract.return_value = ExtractionResult(rules=[])

        result = refresh_all_subreddit_rules(db)

        assert result["total"] == 1
        mock_extract.assert_called_once_with("active_sub")

    @patch("app.services.rule_extractor.time.sleep")
    @patch("app.services.rule_extractor.extract_subreddit_rules")
    def test_inactive_subreddit_not_processed(self, mock_extract, mock_sleep, db):
        """Inactive subreddits (is_active=False) are skipped."""
        from app.models.subreddit import Subreddit, ClientSubredditAssignment
        from app.models.client import Client

        client = Client(client_name="Test Client", brand_name="TestBrand")
        db.add(client)
        db.flush()

        subreddit = Subreddit(subreddit_name="disabled_sub", is_active=False)
        db.add(subreddit)
        db.flush()

        db.add(ClientSubredditAssignment(
            client_id=client.id,
            subreddit_id=subreddit.id,
            is_active=True,
        ))
        db.flush()

        mock_extract.return_value = ExtractionResult(rules=[])

        result = refresh_all_subreddit_rules(db)

        assert result["total"] == 0
        mock_extract.assert_not_called()
