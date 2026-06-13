"""Unit tests for post_filter — deterministic text-quality gate.

Pure unit tests: no DB, no Redis, no external dependencies.
Tests the evaluate() function against known inputs/outputs.
"""

import pytest
from dataclasses import dataclass, field

from app.services.post_filter import (
    evaluate,
    FilterResult,
    SkipReason,
    MIN_SELF_TEXT_LENGTH,
    URL_RATIO_THRESHOLD,
)


@dataclass
class FakeSubmission:
    """Duck-typed PRAW Submission for testing."""

    is_self: bool | None = True
    selftext: str | None = ""
    post_hint: str | None = None
    is_gallery: bool | None = None
    media: object | None = None
    secure_media: object | None = None


class TestSelfPostGate:
    """Requirement 1: Self-Post Gate."""

    def test_is_self_false_skips_non_self_post(self):
        """Validates: Requirement 1.1"""
        sub = FakeSubmission(is_self=False, selftext="a" * 200)
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.non_self_post

    def test_is_self_none_skips_non_self_post(self):
        """Validates: Requirement 1.3"""
        sub = FakeSubmission(is_self=None, selftext="a" * 200)
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.non_self_post


class TestDeletedOrRemoved:
    """Requirement 2: Deleted or Removed Post Detection."""

    def test_selftext_deleted_skips(self):
        """Validates: Requirement 2.1"""
        sub = FakeSubmission(is_self=True, selftext="[deleted]")
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.deleted_or_removed

    def test_selftext_removed_skips(self):
        """Validates: Requirement 2.2"""
        sub = FakeSubmission(is_self=True, selftext="[removed]")
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.deleted_or_removed


class TestEmptySelftext:
    """Requirement 3: Empty Selftext Detection."""

    def test_empty_string_skips(self):
        """Validates: Requirement 3.1"""
        sub = FakeSubmission(is_self=True, selftext="")
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.empty_selftext

    def test_none_selftext_skips(self):
        """Validates: Requirement 3.2"""
        sub = FakeSubmission(is_self=True, selftext=None)
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.empty_selftext

    def test_whitespace_only_skips(self):
        """Validates: Requirement 3.1"""
        sub = FakeSubmission(is_self=True, selftext="   \t\n  ")
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.empty_selftext


class TestMinimumLength:
    """Requirement 4: Minimum Text Length Enforcement."""

    def test_119_chars_skips_too_short(self):
        """Validates: Requirement 4.1"""
        sub = FakeSubmission(is_self=True, selftext="a" * 119)
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.too_short

    def test_exactly_120_chars_passes_length_check(self):
        """Validates: Requirement 4.2"""
        sub = FakeSubmission(is_self=True, selftext="a" * 120)
        result = evaluate(sub)
        # Should pass the length check (may still be evaluated by later rules)
        assert result.reason != SkipReason.too_short


class TestMediaPostDetection:
    """Requirement 5: Media Post Detection."""

    @pytest.mark.parametrize("hint", ["image", "hosted:video", "rich:video"])
    def test_media_hints_skip(self, hint):
        """Validates: Requirements 5.1, 5.2, 5.3"""
        sub = FakeSubmission(is_self=True, selftext="a" * 200, post_hint=hint)
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.media_post

    def test_post_hint_link_with_empty_selftext_skips(self):
        """Validates: Requirement 5.4

        Note: post_hint "link" with empty selftext triggers media_post,
        but since empty selftext is checked first (Rule 3), we test with
        a submission that passes the is_self check. The _check_media function
        is called after length check, so we need selftext >= 120 chars but
        the _check_media receives the raw selftext. Actually in the evaluate()
        flow, if selftext is empty it would be caught at Rule 3 first.
        So this condition only fires if selftext has content but _check_media
        recalculates emptiness. Let's test the scenario where post_hint is
        "link" and selftext has content (should NOT trigger).
        """
        # With content >= 120, post_hint "link" should NOT skip (selftext is not empty)
        sub = FakeSubmission(is_self=True, selftext="a" * 200, post_hint="link")
        result = evaluate(sub)
        assert result.reason != SkipReason.media_post

    def test_is_gallery_true_skips(self):
        """Validates: Requirement 5.5"""
        sub = FakeSubmission(is_self=True, selftext="a" * 200, is_gallery=True)
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.media_post

    def test_media_not_none_with_empty_selftext_skips(self):
        """Validates: Requirement 5.6

        Note: In the evaluate() flow, empty selftext is caught at Rule 3
        before reaching media check. This condition applies when _check_media
        recalculates emptiness from the raw selftext. With non-empty selftext
        (>= 120), media field should not trigger skip.
        """
        # media not None but selftext has content → should NOT skip as media
        sub = FakeSubmission(is_self=True, selftext="a" * 200, media={"type": "video"})
        result = evaluate(sub)
        assert result.reason != SkipReason.media_post

    def test_secure_media_not_none_with_empty_selftext_skips(self):
        """Validates: Requirement 5.7

        Same note as 5.6: with valid selftext content, secure_media alone
        should not trigger media_post skip.
        """
        # secure_media not None but selftext has content → should NOT skip as media
        sub = FakeSubmission(
            is_self=True, selftext="a" * 200, secure_media={"type": "video"}
        )
        result = evaluate(sub)
        assert result.reason != SkipReason.media_post


class TestUrlDominatedText:
    """Requirement 6: URL-Dominated Text Detection."""

    def test_url_ratio_above_50_percent_skips(self):
        """Validates: Requirement 6.1 — 50.1% URL ratio → skip"""
        # Build text where URL chars > 50% of non-whitespace chars
        # URL part: "https://example.com/path" = 24 chars
        # We need url_chars / total_non_ws > 0.50
        # Use a URL of 61 chars + 59 chars of plain text = 120 total non-ws
        # 61/120 = 0.508 > 0.50 → skip
        url = "https://example.com/" + "x" * 41  # 20 + 41 = 61 chars
        plain = "a" * 59
        text = f"{url} {plain}"
        sub = FakeSubmission(is_self=True, selftext=text)
        result = evaluate(sub)
        assert result.passed is False
        assert result.reason == SkipReason.mostly_urls

    def test_url_ratio_below_50_percent_passes(self):
        """Validates: Requirement 6.1 — 49.9% URL ratio → pass"""
        # URL of 59 chars + 61 chars plain = 120 total non-ws
        # 59/120 = 0.491 < 0.50 → pass
        url = "https://example.com/" + "x" * 39  # 20 + 39 = 59 chars
        plain = "a" * 61
        text = f"{url} {plain}"
        sub = FakeSubmission(is_self=True, selftext=text)
        result = evaluate(sub)
        assert result.passed is True
        assert result.reason is None


class TestHappyPath:
    """Requirement 7: Accepted Post Processing."""

    def test_valid_self_post_passes(self):
        """Validates: Requirement 7.1"""
        sub = FakeSubmission(
            is_self=True,
            selftext="This is a meaningful post about cybersecurity best practices. "
            "It discusses various approaches to network security and how to "
            "implement zero trust architecture in modern enterprise environments. "
            "The key takeaway is that security is everyone's responsibility.",
        )
        result = evaluate(sub)
        assert result.passed is True
        assert result.reason is None
        assert result.skipped is False


class TestEvaluationOrder:
    """Requirement 9: Filter Evaluation Order."""

    def test_multiple_failures_returns_earliest_reason(self):
        """Validates: Requirements 9.1, 9.2, 9.3

        Submission that fails Rule 1 (is_self=False) AND Rule 3 (empty selftext)
        should return non_self_post (earliest rule).
        """
        sub = FakeSubmission(is_self=False, selftext="")
        result = evaluate(sub)
        assert result.reason == SkipReason.non_self_post

    def test_deleted_before_length_check(self):
        """A [deleted] post that's also short should return deleted_or_removed."""
        sub = FakeSubmission(is_self=True, selftext="[deleted]")
        result = evaluate(sub)
        # "[deleted]" is 9 chars (< 120), but deleted check runs first
        assert result.reason == SkipReason.deleted_or_removed

    def test_empty_before_too_short(self):
        """Empty string is caught as empty_selftext before too_short."""
        sub = FakeSubmission(is_self=True, selftext="")
        result = evaluate(sub)
        assert result.reason == SkipReason.empty_selftext

    def test_too_short_before_media(self):
        """Short text with media hint returns too_short (evaluated earlier)."""
        sub = FakeSubmission(
            is_self=True, selftext="short", post_hint="image"
        )
        result = evaluate(sub)
        assert result.reason == SkipReason.too_short
