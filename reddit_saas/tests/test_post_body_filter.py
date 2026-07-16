"""Tests for post body URL filter in opportunity_engine.

Production bug: posts with embedded images/videos/external links pass the
url-level filter (their post URL is reddit.com/...) but the body contains
media/links that LLM cannot access → comments are off-topic.

Rule: ANY URL in post_body = skip. Only pure text posts have complete context.
"""

import pytest

from app.services.opportunity_engine import _has_embedded_images


class TestHasEmbeddedImages:
    """Unit tests for _has_embedded_images() filter."""

    # --- Should SKIP (return True) ---

    def test_preview_redd_it_image(self):
        body = "Check my recovery stats https://preview.redd.it/abc123.png pretty good right?"
        assert _has_embedded_images(body) is True

    def test_i_redd_it_image(self):
        body = "Here's my graph https://i.redd.it/xyz789.jpg"
        assert _has_embedded_images(body) is True

    def test_imgur_image(self):
        body = "Screenshot: https://i.imgur.com/AbCdEf.png"
        assert _has_embedded_images(body) is True

    def test_youtube_video(self):
        body = "Watch this explanation https://youtu.be/dQw4w9WgXcQ"
        assert _has_embedded_images(body) is True

    def test_youtube_full_url(self):
        body = "See video https://youtube.com/watch?v=abc123"
        assert _has_embedded_images(body) is True

    def test_v_redd_it_video(self):
        body = "Video proof https://v.redd.it/some_video_id"
        assert _has_embedded_images(body) is True

    def test_external_article_link(self):
        body = "All details in this article https://medium.com/some-long-article-title"
        assert _has_embedded_images(body) is True

    def test_twitter_link(self):
        body = "This tweet explains it https://twitter.com/user/status/123456"
        assert _has_embedded_images(body) is True

    def test_reddit_crosspost_link(self):
        """Reddit internal links are also skipped — LLM can't read the linked thread."""
        body = "Related discussion https://www.reddit.com/r/fitness/comments/abc/some_post"
        assert _has_embedded_images(body) is True

    def test_generic_external_url(self):
        body = "More info here https://example.com/research-paper.pdf"
        assert _has_embedded_images(body) is True

    def test_link_with_long_text_around_it(self):
        """Even with 200+ chars of text, if there's a URL — skip.
        We can't know if the link is essential context or just a reference."""
        body = (
            "I have been testing different recovery protocols for three months now "
            "and documenting everything in a spreadsheet. The key finding is that "
            "cold exposure after training reduces inflammation markers significantly. "
            "Full data: https://docs.google.com/spreadsheets/d/abc123"
        )
        assert _has_embedded_images(body) is True

    def test_multiple_urls(self):
        body = "See https://imgur.com/a/gallery and also https://youtu.be/video"
        assert _has_embedded_images(body) is True

    # --- Should KEEP (return False) ---

    def test_pure_text_post(self):
        body = (
            "I take 2mg melatonin before bed and my HRV went from 45 to 62 "
            "in two weeks. Has anyone else experienced this? I'm wondering if "
            "it's the melatonin or just better sleep hygiene overall."
        )
        assert _has_embedded_images(body) is False

    def test_short_text_post(self):
        body = "Anyone else having issues with the latest Whoop update?"
        assert _has_embedded_images(body) is False

    def test_long_discussion_post(self):
        body = (
            "After 6 months of tracking with Whoop, here are my takeaways:\n\n"
            "1. Sleep consistency matters more than sleep duration\n"
            "2. Alcohol impact is real but varies person to person\n"
            "3. Strain score correlates with how I feel the next day\n"
            "4. Recovery score is most useful as a 7-day trend, not daily\n\n"
            "What patterns have you noticed in your data?"
        )
        assert _has_embedded_images(body) is False

    def test_none_body(self):
        assert _has_embedded_images(None) is False

    def test_empty_body(self):
        assert _has_embedded_images("") is False

    def test_body_with_just_whitespace(self):
        assert _has_embedded_images("   \n\n  ") is False

    def test_body_with_markdown_no_links(self):
        body = "**Bold text** and *italic* and `code` but no links"
        assert _has_embedded_images(body) is False

    def test_body_with_reddit_formatting_no_urls(self):
        body = (
            "> This is a quote from someone\n\n"
            "I agree with this take. The key point is that consistency beats intensity."
        )
        assert _has_embedded_images(body) is False
