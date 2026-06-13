"""Post content filter — deterministic text-quality gate for ingestion.

Evaluates raw PRAW Submission objects against text-quality rules.
Returns FilterResult with pass/skip decision and reason.
Pure function: no DB, no network, no side effects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class SkipReason(str, Enum):
    """Why a submission was filtered out during ingestion."""

    non_self_post = "non_self_post"
    deleted_or_removed = "deleted_or_removed"
    empty_selftext = "empty_selftext"
    too_short = "too_short"
    media_post = "media_post"
    mostly_urls = "mostly_urls"


@dataclass(frozen=True, slots=True)
class FilterResult:
    """Result of evaluating a submission against ingestion filters."""

    passed: bool
    reason: SkipReason | None = None

    @property
    def skipped(self) -> bool:
        return not self.passed

    @classmethod
    def pass_result(cls) -> FilterResult:
        return cls(passed=True, reason=None)

    @classmethod
    def skip(cls, reason: SkipReason) -> FilterResult:
        return cls(passed=False, reason=reason)


# Configuration
MIN_SELF_TEXT_LENGTH: int = 120
URL_RATIO_THRESHOLD: float = 0.50

# Precompiled regex for URL detection
_URL_PATTERN: re.Pattern = re.compile(r"https?://\S+")

# Media post_hint values that always trigger skip
_MEDIA_HINTS: frozenset[str] = frozenset({"image", "hosted:video", "rich:video"})


def evaluate(submission: Any) -> FilterResult:
    """Evaluate a PRAW Submission against ingestion filter rules.

    Rules are evaluated in fixed order (cheapest to most expensive):
    1. is_self check
    2. deleted/removed check
    3. empty selftext check
    4. minimum length check
    5. media post check
    6. URL-dominated text check

    Args:
        submission: A praw.models.Submission object (or duck-typed equivalent).

    Returns:
        FilterResult indicating pass or skip with reason.
    """
    # Rule 1: Self-post gate
    is_self = getattr(submission, "is_self", None)
    if not is_self:  # False or None
        return FilterResult.skip(SkipReason.non_self_post)

    # Rule 2: Deleted/removed detection
    selftext = getattr(submission, "selftext", None)
    if selftext in ("[deleted]", "[removed]"):
        return FilterResult.skip(SkipReason.deleted_or_removed)

    # Rule 3: Empty selftext
    if selftext is None or selftext.strip() == "":
        return FilterResult.skip(SkipReason.empty_selftext)

    # Rule 4: Minimum length
    stripped_text = selftext.strip()
    if len(stripped_text) < MIN_SELF_TEXT_LENGTH:
        return FilterResult.skip(SkipReason.too_short)

    # Rule 5: Media post detection
    media_result = _check_media(submission, selftext)
    if media_result is not None:
        return media_result

    # Rule 6: URL-dominated text
    if _is_mostly_urls(stripped_text):
        return FilterResult.skip(SkipReason.mostly_urls)

    return FilterResult.pass_result()


def _check_media(submission: Any, selftext: str) -> FilterResult | None:
    """Check media-related conditions. Returns FilterResult if skip, None if pass."""
    post_hint = getattr(submission, "post_hint", None)

    # 5.1-5.3: Known media hints
    if post_hint in _MEDIA_HINTS:
        return FilterResult.skip(SkipReason.media_post)

    # 5.4: post_hint "link" with empty selftext
    selftext_empty = selftext is None or selftext.strip() == ""
    if post_hint == "link" and selftext_empty:
        return FilterResult.skip(SkipReason.media_post)

    # 5.5: Gallery post
    is_gallery = getattr(submission, "is_gallery", None)
    if is_gallery is True:
        return FilterResult.skip(SkipReason.media_post)

    # 5.6: media field present with empty selftext
    media = getattr(submission, "media", None)
    if media is not None and selftext_empty:
        return FilterResult.skip(SkipReason.media_post)

    # 5.7: secure_media field present with empty selftext
    secure_media = getattr(submission, "secure_media", None)
    if secure_media is not None and selftext_empty:
        return FilterResult.skip(SkipReason.media_post)

    return None


def _is_mostly_urls(text: str) -> bool:
    """Check if more than 50% of non-whitespace characters are part of URLs."""
    non_ws_total = len(text.replace(" ", "").replace("\t", "").replace("\n", "").replace("\r", ""))
    if non_ws_total == 0:
        return False

    url_chars = sum(len(m.group()) for m in _URL_PATTERN.finditer(text))
    return (url_chars / non_ws_total) > URL_RATIO_THRESHOLD
