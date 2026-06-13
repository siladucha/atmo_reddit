"""GEO Citation Parser — extracts and categorizes URLs from LLM responses.

Focuses on Reddit URL extraction and normalization. Also extracts
all non-Reddit citation URLs for completeness.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse, unquote


@dataclass
class RedditUrl:
    url: str
    category: str  # thread | comment | subreddit | other
    subreddit: str | None = None
    thread_id: str | None = None
    comment_id: str | None = None


@dataclass
class CitationResult:
    reddit_urls: list[RedditUrl] = field(default_factory=list)
    other_urls: list[str] = field(default_factory=list)
    inline_citations: dict[int, str] = field(default_factory=dict)  # citation number -> url


# Pattern for Reddit URLs (www.reddit.com, reddit.com, old.reddit.com)
REDDIT_URL_PATTERN = re.compile(
    r'https?://(?:www\.|old\.)?reddit\.com/[^\s\)\]\}\,\"\'<>]+',
    re.IGNORECASE,
)

# General URL pattern for non-Reddit citations
GENERAL_URL_PATTERN = re.compile(
    r'https?://[^\s\)\]\}\,\"\'<>]+',
    re.IGNORECASE,
)

# Perplexity inline citation pattern: [1], [2], etc. followed by URL
INLINE_CITATION_PATTERN = re.compile(
    r'\[(\d+)\]\s*(?:\(?(https?://[^\s\)\]\}\,\"\'<>]+)\)?)',
    re.IGNORECASE,
)

# Alternative: citation at end of text like "Sources:\n[1] url"
CITATION_BLOCK_PATTERN = re.compile(
    r'^\s*\[(\d+)\]\s*(https?://[^\s\)\]\}\,\"\'<>]+)',
    re.MULTILINE,
)

# Thread pattern: /r/{sub}/comments/{id}/{slug}/
THREAD_PATTERN = re.compile(
    r'/r/([^/]+)/comments/([^/]+)/?([^/]*?)/?$'
)

# Comment pattern: /r/{sub}/comments/{id}/{slug}/{comment_id}/
COMMENT_PATTERN = re.compile(
    r'/r/([^/]+)/comments/([^/]+)/[^/]+/([^/]+)/?$'
)

# Subreddit pattern: /r/{sub}/
SUBREDDIT_PATTERN = re.compile(
    r'/r/([^/]+)/?$'
)


def _normalize_reddit_url(url: str) -> str:
    """Normalize a Reddit URL by removing query params and trailing slashes."""
    # Decode percent-encoding
    url = unquote(url)

    # Parse and rebuild without query params
    parsed = urlparse(url)

    # Normalize domain to www.reddit.com
    path = parsed.path.rstrip("/")

    # Rebuild clean URL
    normalized = f"https://www.reddit.com{path}"
    return normalized


def _categorize_reddit_url(url: str) -> RedditUrl:
    """Categorize a Reddit URL into thread, comment, subreddit, or other."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")

    # Check comment pattern first (more specific)
    m = COMMENT_PATTERN.search(path)
    if m:
        return RedditUrl(
            url=url,
            category="comment",
            subreddit=m.group(1),
            thread_id=m.group(2),
            comment_id=m.group(3),
        )

    # Check thread pattern
    m = THREAD_PATTERN.search(path)
    if m:
        return RedditUrl(
            url=url,
            category="thread",
            subreddit=m.group(1),
            thread_id=m.group(2),
        )

    # Check subreddit pattern
    m = SUBREDDIT_PATTERN.search(path)
    if m:
        return RedditUrl(
            url=url,
            category="subreddit",
            subreddit=m.group(1),
        )

    # Fallback — still a Reddit URL but doesn't match known patterns
    return RedditUrl(url=url, category="other")


def parse_citations(text: str) -> CitationResult:
    """Parse citations from an LLM response text.

    Extracts:
    - Reddit URLs (normalized, categorized)
    - Non-Reddit URLs
    - Inline citations (numbered references)

    Args:
        text: The full LLM response text.

    Returns:
        CitationResult with reddit_urls, other_urls, and inline_citations.
    """
    if not text:
        return CitationResult()

    # Extract inline citations [n](url) or [n] url
    inline_citations: dict[int, str] = {}
    for m in INLINE_CITATION_PATTERN.finditer(text):
        num = int(m.group(1))
        url = m.group(2).rstrip(")")
        inline_citations[num] = url

    # Also check citation block format (Sources section)
    for m in CITATION_BLOCK_PATTERN.finditer(text):
        num = int(m.group(1))
        url = m.group(2).rstrip(")")
        if num not in inline_citations:
            inline_citations[num] = url

    # Extract all Reddit URLs
    reddit_urls_raw = REDDIT_URL_PATTERN.findall(text)

    # Also include Reddit URLs from inline citations
    for url in inline_citations.values():
        if re.match(r'https?://(?:www\.|old\.)?reddit\.com/', url, re.IGNORECASE):
            if url not in reddit_urls_raw:
                reddit_urls_raw.append(url)

    # Normalize and deduplicate Reddit URLs
    seen_normalized = set()
    reddit_urls: list[RedditUrl] = []
    for raw_url in reddit_urls_raw:
        normalized = _normalize_reddit_url(raw_url)
        if normalized not in seen_normalized:
            seen_normalized.add(normalized)
            reddit_url = _categorize_reddit_url(normalized)
            reddit_urls.append(reddit_url)

    # Extract all other URLs (non-Reddit)
    all_urls = GENERAL_URL_PATTERN.findall(text)
    other_urls = []
    seen_other = set()
    for url in all_urls:
        # Clean trailing punctuation
        url = url.rstrip(".,;:)")
        if re.match(r'https?://(?:www\.|old\.)?reddit\.com/', url, re.IGNORECASE):
            continue  # Skip Reddit URLs (already captured)
        if url not in seen_other:
            seen_other.add(url)
            other_urls.append(url)

    return CitationResult(
        reddit_urls=reddit_urls,
        other_urls=other_urls,
        inline_citations=inline_citations,
    )
