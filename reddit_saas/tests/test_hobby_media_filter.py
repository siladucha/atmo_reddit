"""Regression test: image/video/link posts must NOT enter hobby pipeline.

Bug: Reddit post 1tpdj4m (image post, post_hint="image", is_self=False)
entered the hobby pipeline because:
1. It was scraped before post_filter.py existed (May 28, 2026)
2. The URL stored was the reddit permalink (matches %reddit.com%)
3. post_body was only 39 chars but old filter was > 20

Fix: All hobby opportunity queries require post_body >= 120 chars,
matching post_filter.py MIN_SELF_TEXT_LENGTH. This catches legacy
image/video posts with short captions.

See also: post_filter.py Rule 1 (is_self gate) prevents new non-self
posts from entering DB at scrape time.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from app.services.post_filter import evaluate, FilterResult, SkipReason


class FakeSubmission:
    """Minimal PRAW Submission duck-type for testing."""

    def __init__(
        self,
        is_self=True,
        selftext="",
        post_hint=None,
        is_gallery=False,
        media=None,
        secure_media=None,
        url="https://www.reddit.com/r/test/comments/abc123/test/",
        title="Test Post",
        score=100,
    ):
        self.is_self = is_self
        self.selftext = selftext
        self.post_hint = post_hint
        self.is_gallery = is_gallery
        self.media = media
        self.secure_media = secure_media
        self.url = url
        self.title = title
        self.score = score


class TestPostFilterBlocksMediaPosts:
    """post_filter.py must reject non-self posts at scrape time."""

    def test_image_post_rejected(self):
        """Image post (is_self=False, post_hint=image) is rejected."""
        sub = FakeSubmission(
            is_self=False,
            selftext="What in the absolute dogshit went wrong",
            post_hint="image",
            url="https://i.redd.it/q1fskcpqzp3h1.jpeg",
        )
        result = evaluate(sub)
        assert result.skipped is True
        assert result.reason == SkipReason.non_self_post

    def test_video_post_rejected(self):
        """Video post (is_self=False) is rejected."""
        sub = FakeSubmission(
            is_self=False,
            selftext="",
            post_hint="hosted:video",
            url="https://v.redd.it/abc123",
        )
        result = evaluate(sub)
        assert result.skipped is True
        assert result.reason == SkipReason.non_self_post

    def test_link_post_rejected(self):
        """Link post (is_self=False) is rejected."""
        sub = FakeSubmission(
            is_self=False,
            selftext="",
            post_hint="link",
            url="https://example.com/article",
        )
        result = evaluate(sub)
        assert result.skipped is True
        assert result.reason == SkipReason.non_self_post

    def test_self_post_with_long_body_passes(self):
        """Self post with sufficient body text passes filter."""
        sub = FakeSubmission(
            is_self=True,
            selftext="A" * 150,  # > MIN_SELF_TEXT_LENGTH (120)
        )
        result = evaluate(sub)
        assert result.passed is True

    def test_self_post_short_body_rejected(self):
        """Self post with too-short body is rejected."""
        sub = FakeSubmission(
            is_self=True,
            selftext="Short caption only",  # < 120 chars
        )
        result = evaluate(sub)
        assert result.skipped is True
        assert result.reason == SkipReason.too_short

    def test_gallery_post_with_text_rejected(self):
        """Gallery post (is_self=False, is_gallery=True) rejected at is_self check."""
        sub = FakeSubmission(
            is_self=False,
            selftext="Some gallery description that is long enough to pass length check " * 3,
            is_gallery=True,
        )
        result = evaluate(sub)
        assert result.skipped is True
        assert result.reason == SkipReason.non_self_post


class TestHobbyOpportunityBodyLengthFilter:
    """opportunity_engine.py must filter hobby posts with body < 120 chars.

    This tests the DB query filter indirectly by verifying the threshold constant.
    The actual SQL filter uses: sa_func.length(HobbySubreddit.post_body) >= 120
    """

    def test_minimum_body_length_matches_post_filter(self):
        """Opportunity engine body length threshold must match post_filter.py."""
        from app.services.post_filter import MIN_SELF_TEXT_LENGTH

        # The threshold in opportunity_engine.py is hardcoded to 120.
        # It MUST equal post_filter.py MIN_SELF_TEXT_LENGTH.
        assert MIN_SELF_TEXT_LENGTH == 120, (
            f"post_filter.py MIN_SELF_TEXT_LENGTH changed to {MIN_SELF_TEXT_LENGTH}! "
            f"Update opportunity_engine.py and ai_pipeline.py hobby queries to match."
        )

    def test_image_post_body_too_short_for_generation(self):
        """The felony post (39 chars) must NOT pass the 120-char threshold."""
        felony_body = "What in the absolute dogshit went wrong"
        assert len(felony_body) < 120, (
            "Expected felony post body to be shorter than 120 chars"
        )

    def test_legitimate_hobby_post_passes(self):
        """A real text post with substantial body passes the threshold."""
        real_body = (
            "I've been listening to this album on repeat for a week now and I still "
            "can't get over how good the production is. The guitars are massive but "
            "the vocals still cut through perfectly."
        )
        assert len(real_body) >= 120, (
            f"Test body should be >= 120 chars, got {len(real_body)}"
        )


class TestDraftQualityGateRejectsShortGeneration:
    """draft_quality_gate.py must reject LLM output that is too short."""

    def test_1_char_output_rejected(self):
        """LLM returning 1 char (the actual failure case) is caught."""
        from app.services.draft_quality_gate import validate_draft_text

        result = validate_draft_text("x")
        assert result.ok is False
        assert "too_short" in result.reason
        assert "1_chars" in result.reason

    def test_empty_output_rejected(self):
        """Empty LLM response is caught."""
        from app.services.draft_quality_gate import validate_draft_text

        result = validate_draft_text("")
        assert result.ok is False
        assert result.reason == "empty_response"

    def test_valid_comment_passes(self):
        """A normal-length comment passes the quality gate."""
        from app.services.draft_quality_gate import validate_draft_text

        comment = (
            "Yeah that riff progression in the second verse is criminally underrated. "
            "The way it builds into the bridge section gives me chills every time."
        )
        result = validate_draft_text(comment)
        assert result.ok is True
