"""Pre-filter service — deterministic keyword-based thread filtering.

Eliminates obviously irrelevant threads BEFORE sending to LLM scoring.
This is free (no API calls) and reduces LLM costs by 60-80%.

Two outputs:
1. Candidates — threads that match keywords/competitors/heuristics → send to LLM
2. Growth opportunities — threads good for avatar karma building (no LLM needed)
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.thread import RedditThread

logger = logging.getLogger(__name__)


@dataclass
class PreFilterResult:
    """Result of pre-filtering threads."""

    candidates: list[RedditThread] = field(default_factory=list)
    growth_opportunities: list[RedditThread] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # [{thread, reason}]

    @property
    def total_input(self) -> int:
        return len(self.candidates) + len(self.growth_opportunities) + len(self.skipped)

    @property
    def candidates_count(self) -> int:
        return len(self.candidates)

    @property
    def growth_count(self) -> int:
        return len(self.growth_opportunities)

    @property
    def skipped_count(self) -> int:
        return len(self.skipped)


def pre_filter_threads(
    threads: list[RedditThread],
    client: Client,
    *,
    max_candidates: int = 20,
    max_growth: int = 10,
    growth_max_age_hours: int = 6,
) -> PreFilterResult:
    """Filter threads into candidates (for LLM scoring) and growth opportunities.

    Candidates criteria (any match → candidate):
    - Contains high-priority keyword
    - Contains medium-priority keyword
    - Contains competitor name
    - Thread in target subreddit with 5+ comments and decent engagement

    Growth opportunities criteria (all must match):
    - Fresh thread (< growth_max_age_hours)
    - Has 3-30 comments (active but not overwhelming)
    - Not already a candidate
    - Decent upvotes (> 2)

    Everything else → skipped (with reason).

    Args:
        threads: List of RedditThread objects to filter.
        client: Client with keywords and competitive_landscape.
        max_candidates: Max threads to send to LLM.
        max_growth: Max growth opportunities to return.
        growth_max_age_hours: Max age for growth opportunity threads.

    Returns:
        PreFilterResult with candidates, growth_opportunities, and skipped lists.
    """
    result = PreFilterResult()

    # Extract keywords from client
    keywords_data = client.keywords or {}
    high_keywords = [k.lower() for k in (keywords_data.get("high") or [])]
    medium_keywords = [k.lower() for k in (keywords_data.get("medium") or [])]
    low_keywords = [k.lower() for k in (keywords_data.get("low") or [])]
    all_keywords = high_keywords + medium_keywords + low_keywords

    # Extract competitor names from competitive_landscape
    competitors = _extract_competitors(client.competitive_landscape)

    # Build regex patterns for efficient matching
    keyword_patterns = _build_keyword_patterns(high_keywords, medium_keywords, low_keywords)
    competitor_pattern = _build_competitor_pattern(competitors)

    now = datetime.now(timezone.utc)
    growth_cutoff = now - timedelta(hours=growth_max_age_hours)

    candidate_set: set = set()

    for thread in threads:
        # Build searchable text (title + body, lowercased)
        text = _get_thread_text(thread)

        # Check keyword matches
        match_level = _check_keyword_match(text, keyword_patterns)

        # Check competitor mention
        has_competitor = bool(competitor_pattern and competitor_pattern.search(text))

        # Determine if candidate
        is_candidate = False
        candidate_reason = ""

        if match_level == "high":
            is_candidate = True
            candidate_reason = "high-priority keyword"
        elif match_level == "medium":
            is_candidate = True
            candidate_reason = "medium-priority keyword"
        elif has_competitor:
            is_candidate = True
            candidate_reason = "competitor mention"
        elif match_level == "low" and _has_engagement(thread):
            is_candidate = True
            candidate_reason = "low keyword + engagement"
        elif _is_high_engagement_in_target_sub(thread):
            # Catch-all: active thread in target subreddit, might have strategic value
            is_candidate = True
            candidate_reason = "high engagement (catch-all)"

        if is_candidate and len(result.candidates) < max_candidates:
            result.candidates.append(thread)
            candidate_set.add(thread.id)
        elif is_candidate:
            # Over candidate cap — still note it
            result.skipped.append({
                "thread": thread,
                "reason": f"over cap ({candidate_reason})",
            })
        elif _is_growth_opportunity(thread, growth_cutoff) and len(result.growth_opportunities) < max_growth:
            # Not relevant for client, but good for avatar karma
            result.growth_opportunities.append(thread)
        else:
            # Skip entirely
            skip_reason = "no keyword match"
            if not _has_engagement(thread):
                skip_reason = "no keywords, low engagement"
            result.skipped.append({
                "thread": thread,
                "reason": skip_reason,
            })

    logger.info(
        f"Pre-filter: {result.total_input} threads → "
        f"{result.candidates_count} candidates, "
        f"{result.growth_count} growth, "
        f"{result.skipped_count} skipped. "
        f"Client: {client.client_name}"
    )

    return result


def _get_thread_text(thread: RedditThread) -> str:
    """Get searchable text from thread (title + body, lowercased)."""
    parts = [thread.post_title or ""]
    if thread.post_body:
        # Only use first 1000 chars of body for matching (efficiency)
        parts.append(thread.post_body[:1000])
    return " ".join(parts).lower()


def _extract_competitors(competitive_landscape: str | None) -> list[str]:
    """Extract competitor names from the competitive_landscape text field."""
    if not competitive_landscape:
        return []

    # Common patterns: "Competitors: X, Y, Z" or just comma-separated names
    # Also handle "vs X", "compared to X", etc.
    competitors = []

    # Split by common delimiters
    text = competitive_landscape.lower()

    # Try to find explicit lists
    for line in competitive_landscape.split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split by commas, semicolons
        parts = re.split(r"[,;]", line)
        for part in parts:
            part = part.strip().strip("-•*").strip()
            # Filter out long phrases (likely descriptions, not names)
            if part and len(part) < 40 and len(part.split()) <= 4:
                competitors.append(part.lower())

    return list(set(competitors))


def _build_keyword_patterns(
    high: list[str], medium: list[str], low: list[str]
) -> dict[str, re.Pattern | None]:
    """Build compiled regex patterns for each keyword priority level."""
    patterns = {}
    for level, keywords in [("high", high), ("medium", medium), ("low", low)]:
        if keywords:
            # Word boundary matching for each keyword
            escaped = [re.escape(k) for k in keywords]
            pattern_str = r"\b(" + "|".join(escaped) + r")\b"
            try:
                patterns[level] = re.compile(pattern_str, re.IGNORECASE)
            except re.error:
                # Fallback: simple substring check
                patterns[level] = None
        else:
            patterns[level] = None
    return patterns


def _build_competitor_pattern(competitors: list[str]) -> re.Pattern | None:
    """Build a compiled regex for competitor name matching."""
    if not competitors:
        return None
    escaped = [re.escape(c) for c in competitors if len(c) > 2]
    if not escaped:
        return None
    try:
        return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)
    except re.error:
        return None


def _check_keyword_match(
    text: str, patterns: dict[str, re.Pattern | None]
) -> str | None:
    """Check which keyword level matches. Returns 'high', 'medium', 'low', or None."""
    if patterns.get("high") and patterns["high"].search(text):
        return "high"
    if patterns.get("medium") and patterns["medium"].search(text):
        return "medium"
    if patterns.get("low") and patterns["low"].search(text):
        return "low"
    return None


def _has_engagement(thread: RedditThread) -> bool:
    """Check if thread has meaningful engagement."""
    return (thread.ups or 0) >= 3 or _estimate_comment_count(thread) >= 3


def _estimate_comment_count(thread: RedditThread) -> int:
    """Estimate comment count from comments_json length (rough heuristic)."""
    if not thread.comments_json:
        return 0
    # Rough estimate: each comment is ~200-500 chars in JSON
    return max(1, len(thread.comments_json) // 300)


def _is_high_engagement_in_target_sub(thread: RedditThread) -> bool:
    """Check if thread has high engagement (catch-all for strategic value)."""
    comments = _estimate_comment_count(thread)
    return comments >= 10 and (thread.ups or 0) >= 5


def _is_growth_opportunity(thread: RedditThread, cutoff: datetime) -> bool:
    """Check if thread is a good growth opportunity for avatar karma building.

    Criteria:
    - Fresh (within cutoff)
    - Has some engagement (3-50 comments)
    - Not dead (> 2 upvotes)
    - Not too controversial
    """
    # Freshness check
    thread_time = thread.scraped_at or thread.created_at
    if thread_time and thread_time < cutoff:
        return False

    comments = _estimate_comment_count(thread)
    ups = thread.ups or 0

    # Sweet spot: active discussion, not overwhelming
    return 3 <= comments <= 50 and ups >= 3
