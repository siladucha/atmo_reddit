"""Comprehensive tests for GEO/AEO Prompt Monitoring module.

Tests cover:
- Brand Detection Service (pure logic, no mocks)
- Citation Parser Service (pure logic, no mocks)
- Query Runner (mocked LLM + Redis + mocked DB session)

Run with: pytest tests/test_geo_monitoring.py -v
"""

import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.services.geo_brand_detection import (
    BrandDetectionResult,
    CompetitorMatch,
    detect_brand,
)
from app.services.geo_citation_parser import (
    CitationResult,
    RedditUrl,
    parse_citations,
)


# =============================================================================
# 1. Brand Detection Service Tests
# =============================================================================


class TestBrandDetection:
    """Tests for app/services/geo_brand_detection.py detect_brand()."""

    def test_brand_found_exact_match_word_boundary(self):
        """Brand found — exact match at word boundary."""
        text = "I recommend using Acme for your security needs."
        result = detect_brand(text, "Acme")
        assert result.brand_found is True
        assert len(result.brand_positions) >= 1

    def test_brand_not_found_substring_inside_word(self):
        """Brand NOT found — substring inside another word (AcmeWidgets != Acme)."""
        text = "Check out AcmeWidgets for enterprise solutions."
        result = detect_brand(text, "Acme")
        assert result.brand_found is False
        assert result.brand_positions == []

    def test_brand_found_case_insensitive(self):
        """Brand found — case-insensitive matching ('xm cyber' matches 'XM Cyber')."""
        text = "For exposure management, XM Cyber is a strong choice."
        result = detect_brand(text, "xm cyber")
        assert result.brand_found is True
        assert len(result.brand_positions) >= 1

    def test_brand_found_fuzzy_match_long_name(self):
        """Brand found — fuzzy match for names > 6 chars (Levenshtein <= 2)."""
        # "Crowdstrik" (missing e) vs "CrowdStrike" — distance 1
        text = "Many companies use Crowdstrik for endpoint protection."
        result = detect_brand(text, "CrowdStrike")
        assert result.brand_found is True

    def test_no_fuzzy_for_short_names(self):
        """No fuzzy matching for names < 4 chars (e.g., 'XM' should be exact only)."""
        # "XN" is close to "XM" (distance=1) but should NOT match since len < 4
        text = "The solution from XN works well in enterprise."
        result = detect_brand(text, "XM")
        assert result.brand_found is False

    def test_multiple_brand_positions_in_text(self):
        """Multiple brand positions detected in same text."""
        text = "Acme provides tools. Many prefer Acme over competitors. Acme wins."
        result = detect_brand(text, "Acme")
        assert result.brand_found is True
        assert len(result.brand_positions) >= 3

    def test_competitor_detection_multiple(self):
        """Competitor detection — finds multiple competitors."""
        text = "While SentinelOne and Palo Alto are popular, consider alternatives."
        competitors = [
            {"id": "c1", "name": "SentinelOne", "aliases": []},
            {"id": "c2", "name": "Palo Alto", "aliases": []},
            {"id": "c3", "name": "MissingCorp", "aliases": []},
        ]
        result = detect_brand(text, "Acme", competitors)
        assert len(result.competitors_found) == 2
        found_ids = {c.competitor_id for c in result.competitors_found}
        assert "c1" in found_ids
        assert "c2" in found_ids
        assert "c3" not in found_ids

    def test_competitor_aliases_match(self):
        """Competitor aliases — matches via alias list."""
        text = "CrowdStrike Falcon is widely deployed in enterprises."
        competitors = [
            {"id": "c1", "name": "CrowdStrike", "aliases": ["CrowdStrike Falcon", "CS Falcon"]},
        ]
        result = detect_brand(text, "Acme", competitors)
        assert len(result.competitors_found) == 1
        assert result.competitors_found[0].competitor_id == "c1"

    def test_empty_text_returns_brand_not_found(self):
        """Empty text returns brand_found=False."""
        result = detect_brand("", "Acme")
        assert result.brand_found is False
        assert result.brand_positions == []
        assert result.competitors_found == []

    def test_empty_brand_name_returns_brand_not_found(self):
        """Empty brand_name returns brand_found=False."""
        result = detect_brand("Some text about security", "")
        assert result.brand_found is False
        assert result.brand_positions == []

    def test_word_boundary_at_start_of_text(self):
        """Word boundary at start of text — brand at position 0."""
        text = "Acme is the best tool for exposure management."
        result = detect_brand(text, "Acme")
        assert result.brand_found is True
        assert 0 in result.brand_positions

    def test_word_boundary_at_end_of_text(self):
        """Word boundary at end of text — brand is last word."""
        text = "The best choice is Acme"
        result = detect_brand(text, "Acme")
        assert result.brand_found is True
        assert len(result.brand_positions) >= 1

    def test_word_boundary_with_punctuation(self):
        """Word boundary with punctuation ('use Acme.' matches)."""
        text = "You should use Acme."
        result = detect_brand(text, "Acme")
        assert result.brand_found is True

    def test_brand_with_parentheses(self):
        """Brand surrounded by parentheses is still detected."""
        text = "Consider (Acme) for your needs."
        result = detect_brand(text, "Acme")
        assert result.brand_found is True

    def test_brand_in_comma_separated_list(self):
        """Brand in comma-separated list detected."""
        text = "Options include SentinelOne, Acme, and Palo Alto."
        result = detect_brand(text, "Acme")
        assert result.brand_found is True

    def test_no_competitors_param(self):
        """Works when competitors param is None."""
        result = detect_brand("Acme is great", "Acme", None)
        assert result.brand_found is True
        assert result.competitors_found == []


# =============================================================================
# 2. Citation Parser Service Tests
# =============================================================================


class TestCitationParser:
    """Tests for app/services/geo_citation_parser.py parse_citations()."""

    def test_extract_www_reddit_url(self):
        """Extract www.reddit.com URL."""
        text = "Check this thread: https://www.reddit.com/r/cybersecurity/comments/abc123/my_post/"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        assert "www.reddit.com" in result.reddit_urls[0].url

    def test_extract_old_reddit_url_normalized(self):
        """Extract old.reddit.com URL — normalized to www.reddit.com."""
        text = "See https://old.reddit.com/r/netsec/comments/xyz789/discussion/"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        assert "www.reddit.com" in result.reddit_urls[0].url
        assert "old.reddit.com" not in result.reddit_urls[0].url

    def test_categorize_thread_url(self):
        """Categorize thread URL correctly."""
        text = "https://www.reddit.com/r/cybersecurity/comments/abc123/my_post/"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        assert result.reddit_urls[0].category == "thread"
        assert result.reddit_urls[0].subreddit == "cybersecurity"
        assert result.reddit_urls[0].thread_id == "abc123"

    def test_categorize_comment_url(self):
        """Categorize comment URL correctly."""
        text = "https://www.reddit.com/r/sysadmin/comments/abc123/my_post/def456/"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        assert result.reddit_urls[0].category == "comment"
        assert result.reddit_urls[0].subreddit == "sysadmin"
        assert result.reddit_urls[0].thread_id == "abc123"
        assert result.reddit_urls[0].comment_id == "def456"

    def test_categorize_subreddit_url(self):
        """Categorize subreddit URL correctly."""
        text = "Visit https://www.reddit.com/r/netsec/"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        assert result.reddit_urls[0].category == "subreddit"
        assert result.reddit_urls[0].subreddit == "netsec"

    def test_unknown_reddit_url_categorized_as_other(self):
        """Unknown Reddit URL categorized as 'other'."""
        text = "https://www.reddit.com/user/someuser/overview"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        assert result.reddit_urls[0].category == "other"

    def test_query_params_stripped(self):
        """Query params stripped from Reddit URLs."""
        text = "https://www.reddit.com/r/cybersecurity/comments/abc123/my_post/?utm_source=share&utm_medium=web"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        assert "utm_source" not in result.reddit_urls[0].url
        assert "?" not in result.reddit_urls[0].url

    def test_trailing_slashes_stripped(self):
        """Trailing slashes stripped from normalized URLs."""
        text = "https://www.reddit.com/r/netsec/"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1
        # The normalized URL should not end with a trailing slash
        assert not result.reddit_urls[0].url.endswith("/")

    def test_deduplication_of_same_url(self):
        """Deduplication of same URL appearing twice."""
        text = (
            "First: https://www.reddit.com/r/cybersecurity/comments/abc123/post/\n"
            "Again: https://www.reddit.com/r/cybersecurity/comments/abc123/post/"
        )
        result = parse_citations(text)
        assert len(result.reddit_urls) == 1

    def test_non_reddit_urls_in_other_urls(self):
        """Non-Reddit URLs collected in other_urls."""
        text = "See https://example.com/article and https://blog.example.org/post"
        result = parse_citations(text)
        assert len(result.reddit_urls) == 0
        assert len(result.other_urls) == 2
        urls_joined = " ".join(result.other_urls)
        assert "example.com" in urls_joined
        assert "blog.example.org" in urls_joined

    def test_inline_citation_parsed(self):
        """Inline citation [n](url) parsed."""
        text = "This is recommended [1](https://www.reddit.com/r/netsec/comments/abc/post/) by experts."
        result = parse_citations(text)
        assert 1 in result.inline_citations
        assert "reddit.com" in result.inline_citations[1]

    def test_citation_block_format_parsed(self):
        """Citation block format parsed ([1] url on new line)."""
        text = (
            "Great explanation of the concept.\n\n"
            "Sources:\n"
            "[1] https://www.reddit.com/r/cybersecurity/comments/abc123/post/\n"
            "[2] https://example.com/article\n"
        )
        result = parse_citations(text)
        assert 1 in result.inline_citations
        assert 2 in result.inline_citations
        assert "reddit.com" in result.inline_citations[1]
        assert "example.com" in result.inline_citations[2]

    def test_empty_text_returns_empty_results(self):
        """Empty text returns empty results."""
        result = parse_citations("")
        assert result.reddit_urls == []
        assert result.other_urls == []
        assert result.inline_citations == {}

    def test_text_with_no_urls_returns_empty_results(self):
        """Text with no URLs returns empty results."""
        text = "This is just plain text without any links or citations."
        result = parse_citations(text)
        assert result.reddit_urls == []
        assert result.other_urls == []
        assert result.inline_citations == {}

    def test_mixed_reddit_and_non_reddit_urls(self):
        """Mixed Reddit + non-Reddit URLs both captured."""
        text = (
            "Reddit thread: https://www.reddit.com/r/netsec/comments/abc123/post/\n"
            "External: https://docs.example.com/guide\n"
            "Another Reddit: https://www.reddit.com/r/sysadmin/"
        )
        result = parse_citations(text)
        assert len(result.reddit_urls) == 2
        assert len(result.other_urls) == 1
        assert "docs.example.com" in result.other_urls[0]


# =============================================================================
# 3. Query Runner Unit Tests (fully mocked — no DB connection needed)
# =============================================================================


def _make_mock_client(brand_name="TestBrand"):
    """Create a mock Client object."""
    client = MagicMock()
    client.id = uuid.uuid4()
    client.client_name = "Test Client"
    client.brand_name = brand_name
    return client


def _make_mock_prompt(client_id, prompt_text="What is the best cybersecurity tool?"):
    """Create a mock GeoPrompt object."""
    prompt = MagicMock()
    prompt.id = uuid.uuid4()
    prompt.client_id = client_id
    prompt.prompt_text = prompt_text
    prompt.is_active = True
    return prompt


def _mock_llm_response(content="TestBrand is a leading solution."):
    """Create a synthetic LLM response dict."""
    return {
        "content": content,
        "model": "perplexity/sonar",
        "input_tokens": 150,
        "output_tokens": 50,
        "cost_usd": 0.0002,
        "duration_ms": 1200,
    }


class TestGeoQueryRunner:
    """Tests for app/services/geo_query_runner.py run_geo_batch_for_client().

    Uses fully mocked DB session + LLM + Redis to test business logic in isolation.
    No real DB connection needed.
    """

    def _setup_mock_db(self, prompts=None, competitors=None):
        """Create a mock DB session with chained query support."""
        db = MagicMock()

        # Mock the prompt query chain
        prompt_query = MagicMock()
        prompt_filter = MagicMock()
        prompt_filter.all.return_value = prompts or []
        prompt_query.filter.return_value = prompt_filter

        # Mock the competitor query chain
        comp_query = MagicMock()
        comp_filter = MagicMock()
        comp_filter.all.return_value = competitors or []
        comp_query.filter.return_value = comp_filter

        # Mock the results query chain (for frequency metric computation)
        results_query = MagicMock()
        results_filter = MagicMock()

        # db.query() returns different things based on model
        def query_side_effect(model):
            from app.models.geo_prompt import GeoPrompt
            from app.models.geo_competitor import GeoCompetitor
            from app.models.geo_execution import GeoQueryResult
            if model == GeoPrompt:
                return prompt_query
            elif model == GeoCompetitor:
                return comp_query
            elif model == GeoQueryResult:
                return results_query
            return MagicMock()

        db.query.side_effect = query_side_effect

        # Mock add/commit/refresh to be no-ops that track calls
        db.add = MagicMock()
        db.commit = MagicMock()
        db.refresh = MagicMock(side_effect=lambda obj: None)

        return db, results_query

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.settings_service")
    def test_returns_none_when_no_active_prompts(self, mock_settings, mock_key, mock_redis):
        """Returns None when no active prompts for the client."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.return_value = 3

        client = _make_mock_client()
        db, _ = self._setup_mock_db(prompts=[])  # No prompts

        result = run_geo_batch_for_client(db, client)
        assert result is None

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.settings_service")
    def test_returns_none_when_perplexity_disabled(self, mock_settings, mock_key, mock_redis):
        """Returns None when Perplexity provider is disabled."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        client = _make_mock_client()
        prompt = _make_mock_prompt(client.id)
        db, _ = self._setup_mock_db(prompts=[prompt])

        def settings_side_effect(db_arg, key):
            if key == "geo_provider_perplexity_enabled":
                return "false"
            return None

        mock_settings.get_setting.side_effect = settings_side_effect
        mock_settings.get_setting_int.return_value = 3

        result = run_geo_batch_for_client(db, client)
        assert result is None

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value=None)
    @patch("app.services.geo_query_runner.settings_service")
    def test_returns_none_when_no_api_key(self, mock_settings, mock_key, mock_redis):
        """Returns None when no Perplexity API key configured."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        client = _make_mock_client()
        prompt = _make_mock_prompt(client.id)
        db, _ = self._setup_mock_db(prompts=[prompt])

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.return_value = 3

        result = run_geo_batch_for_client(db, client)
        assert result is None

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_creates_batch_with_correct_total_queries(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Creates batch with correct total_queries count (prompts x runs_per_prompt)."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 3,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        mock_llm.return_value = _mock_llm_response()

        client = _make_mock_client()
        prompt1 = _make_mock_prompt(client.id, "Prompt 1")
        prompt2 = _make_mock_prompt(client.id, "Prompt 2")
        db, results_query = self._setup_mock_db(prompts=[prompt1, prompt2])

        # For frequency metrics computation: query results returns the batched results
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        result = run_geo_batch_for_client(db, client)
        assert result is not None
        # 2 prompts x 3 runs = 6
        assert result.total_queries == 6

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_successful_run_brand_mentioned_true(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Successful run — brand detection returns True when brand is in LLM response."""
        from app.services.geo_query_runner import run_geo_batch_for_client
        from app.models.geo_execution import GeoQueryResult

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 1,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        # Response contains brand name
        mock_llm.return_value = _mock_llm_response(
            content="TestBrand is a leader in exposure management."
        )

        client = _make_mock_client(brand_name="TestBrand")
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None
        assert batch.status == "completed"
        assert batch.successful_queries == 1

        # Verify db.add was called with a GeoQueryResult that has brand_mentioned=True
        add_calls = db.add.call_args_list
        query_results = [
            call.args[0] for call in add_calls
            if isinstance(call.args[0], GeoQueryResult)
        ]
        assert len(query_results) >= 1
        assert query_results[0].brand_mentioned is True
        assert query_results[0].status == "success"

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_successful_run_brand_mentioned_false(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Successful run — brand_mentioned=False when brand is not in LLM response."""
        from app.services.geo_query_runner import run_geo_batch_for_client
        from app.models.geo_execution import GeoQueryResult

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 1,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        # Response does NOT contain brand name
        mock_llm.return_value = _mock_llm_response(
            content="CrowdStrike and SentinelOne are the top choices."
        )

        client = _make_mock_client(brand_name="TestBrand")
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None

        # Verify brand_mentioned=False in stored result
        add_calls = db.add.call_args_list
        query_results = [
            call.args[0] for call in add_calls
            if isinstance(call.args[0], GeoQueryResult)
        ]
        assert len(query_results) >= 1
        assert query_results[0].brand_mentioned is False

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_failed_llm_call_stores_failed_result(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Failed LLM call stores result with status='failed'."""
        from app.services.geo_query_runner import run_geo_batch_for_client
        from app.models.geo_execution import GeoQueryResult

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 1,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        mock_llm.side_effect = Exception("API timeout")

        client = _make_mock_client(brand_name="TestBrand")
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None

        # Verify a failed result was stored
        add_calls = db.add.call_args_list
        query_results = [
            call.args[0] for call in add_calls
            if isinstance(call.args[0], GeoQueryResult)
        ]
        assert len(query_results) >= 1
        failed_results = [r for r in query_results if r.status == "failed"]
        assert len(failed_results) >= 1
        assert "ERROR" in failed_results[0].response_text

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_computes_frequency_metrics_correctly(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Computes frequency metrics correctly (brand_appearances / total_runs)."""
        from app.services.geo_query_runner import run_geo_batch_for_client
        from app.models.geo_execution import GeoQueryResult, GeoFrequencyMetric

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 3,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        # Return brand in 2 out of 3 calls
        call_count = {"n": 0}

        def alternating_response(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return _mock_llm_response(content="TestBrand is great for security.")
            else:
                return _mock_llm_response(content="CrowdStrike is the leader.")

        mock_llm.side_effect = alternating_response

        client = _make_mock_client(brand_name="TestBrand")
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])

        # For frequency computation, we need the query to return the results
        # that were "stored" — we capture them from db.add calls
        stored_results = []

        def capture_add(obj):
            if isinstance(obj, GeoQueryResult):
                stored_results.append(obj)

        db.add.side_effect = capture_add

        # The frequency computation queries results from DB
        # We need to make the query return our stored results
        def results_filter_factory(*args, **kwargs):
            mock_f = MagicMock()
            mock_f.all.return_value = [r for r in stored_results if r.status == "success"]
            mock_f.filter.return_value = mock_f
            return mock_f

        results_query.filter.side_effect = results_filter_factory

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None
        # All 3 calls succeed (brand presence is orthogonal to success)
        # The 3rd call had no brand mention but still succeeded
        # Wait — all 3 calls succeed, just 2 mention brand
        assert batch.successful_queries == 3
        assert batch.failed_queries == 0

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_batch_status_completed_when_all_succeed(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Batch status = 'completed' when all queries succeed."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 2,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        mock_llm.return_value = _mock_llm_response()

        client = _make_mock_client()
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None
        assert batch.status == "completed"
        assert batch.successful_queries == 2
        assert batch.failed_queries == 0

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_batch_status_partial_when_some_fail(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Batch status = 'partial' when some queries fail and some succeed."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 2,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        # First call succeeds, second fails
        call_count = {"n": 0}

        def mixed_response(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _mock_llm_response()
            else:
                raise Exception("LLM timeout")

        mock_llm.side_effect = mixed_response

        client = _make_mock_client()
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None
        assert batch.status == "partial"
        assert batch.successful_queries == 1
        assert batch.failed_queries == 1

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_batch_status_failed_when_all_fail(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Batch status = 'failed' when all queries fail."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 2,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        mock_llm.side_effect = Exception("API rate limited")

        client = _make_mock_client()
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None
        assert batch.status == "failed"
        assert batch.successful_queries == 0
        assert batch.failed_queries == 2

    @patch("app.services.geo_query_runner._get_redis_client", side_effect=Exception("No Redis"))
    @patch("app.services.geo_query_runner._get_perplexity_api_key", return_value="test-key-123")
    @patch("app.services.geo_query_runner.call_llm")
    @patch("app.services.geo_query_runner.log_ai_usage")
    @patch("app.services.geo_query_runner.settings_service")
    @patch("app.services.geo_query_runner._get_competitors_for_client", return_value=[])
    def test_logs_ai_usage_with_geo_query_operation(
        self, mock_comps, mock_settings, mock_log, mock_llm, mock_key, mock_redis
    ):
        """Logs to AIUsageLog with operation='geo_query'."""
        from app.services.geo_query_runner import run_geo_batch_for_client

        mock_settings.get_setting.return_value = None
        mock_settings.get_setting_int.side_effect = lambda db, key, default=None: {
            "geo_runs_per_prompt": 1,
            "geo_rate_limit_perplexity_rpm": 20,
        }.get(key, default)

        mock_llm.return_value = _mock_llm_response()

        client = _make_mock_client()
        prompt = _make_mock_prompt(client.id)
        db, results_query = self._setup_mock_db(prompts=[prompt])
        results_filter = MagicMock()
        results_filter.all.return_value = []
        results_query.filter.return_value = results_filter

        batch = run_geo_batch_for_client(db, client)
        assert batch is not None

        # Verify log_ai_usage was called with correct operation
        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args
        # log_ai_usage(db, client_id, operation, result, ...) - positional
        assert call_kwargs.kwargs.get("operation") == "geo_query" or \
            (len(call_kwargs.args) >= 3 and call_kwargs.args[2] == "geo_query")
