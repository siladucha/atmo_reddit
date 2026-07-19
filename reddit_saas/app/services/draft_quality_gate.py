"""Draft Quality Gate — fast validation before comment enters review queue.

Cheap, synchronous checks that prevent garbage LLM output from reaching
human reviewers or auto-approve pipeline. Runs AFTER LLM call, BEFORE
CommentDraft creation.

Design: fail-fast, no LLM calls, no DB queries. Pure string validation.
"""

import re
from typing import NamedTuple


class QualityResult(NamedTuple):
    """Result of draft quality check."""
    ok: bool
    reason: str  # empty if ok=True, rejection reason if ok=False


# --- Thresholds ---
MIN_COMMENT_LENGTH = 60  # chars (below this = obviously broken/truncated)
MAX_COMMENT_LENGTH = 600  # chars (hobby = 5-60 words ≈ 30-360 chars; 600 = generous ceiling)
HOT_THREAD_UPS_THRESHOLD = 500  # for hobby pipeline (generous — match threads are 1000+)

# JSON artifact patterns (LLM returned raw JSON instead of text)
_JSON_PATTERNS = re.compile(
    r'^[\s]*[\{\[]'  # starts with { or [
    r'|"comment"\s*:'  # contains "comment":
    r'|"text"\s*:'  # contains "text":
    r'|"response"\s*:'  # contains "response":
    r'|^\s*```'  # starts with code fence
)

# Bot signature phrases (filler closers that scream "AI generated")
_BOT_SIGNATURES = [
    "respect for the analysis",
    "great post",
    "thanks for sharing",
    "interesting take",
    "well said",
    "couldn't agree more",
    "this is so true",
    "appreciate the insight",
    "thanks for the info",
]


def validate_draft_text(comment_text: str, previous_drafts: list[str] | None = None) -> QualityResult:
    """Validate generated comment text before creating a draft.

    Args:
        comment_text: The LLM-generated comment text.
        previous_drafts: Recent draft texts for this avatar (for repeat detection).

    Returns:
        QualityResult(ok=True, reason="") if text passes all checks.
        QualityResult(ok=False, reason="...") if rejected.
    """
    if not comment_text:
        return QualityResult(False, "empty_response")

    text = comment_text.strip()

    # --- Length checks ---
    if len(text) < MIN_COMMENT_LENGTH:
        return QualityResult(False, f"too_short:{len(text)}_chars")

    if len(text) > MAX_COMMENT_LENGTH:
        return QualityResult(False, f"too_long:{len(text)}_chars")

    # --- Word count minimum (catches truncated generation) ---
    word_count = len(text.split())
    if word_count < 10:
        return QualityResult(False, f"too_few_words:{word_count}")

    # --- JSON artifact detection ---
    if _JSON_PATTERNS.search(text):
        return QualityResult(False, "json_artifact")

    # --- Looks like a dict/object literal (Python repr leak) ---
    if text.startswith("{'") or text.startswith('{"'):
        return QualityResult(False, "dict_literal")

    # --- Bot signature detection (entire comment is just a filler phrase) ---
    text_lower = text.lower().strip().rstrip(".")
    for sig in _BOT_SIGNATURES:
        if text_lower == sig or text_lower.startswith(sig):
            return QualityResult(False, f"bot_signature:{sig[:30]}")

    # --- Exact duplicate of recent draft ---
    if previous_drafts:
        text_normalized = _normalize(text)
        for prev in previous_drafts[:10]:
            if prev and _normalize(prev) == text_normalized:
                return QualityResult(False, "exact_duplicate")

    return QualityResult(True, "")


def is_hot_thread_for_hobby(post_ups: int | None) -> bool:
    """Check if a hobby post is too hot (high engagement = risky for low-karma accounts).

    Match Threads, viral posts, etc. with thousands of upvotes are dangerous:
    - Comments get buried instantly
    - Mods aggressively clean low-karma comments
    - Zero engagement value for warming

    Args:
        post_ups: The upvote count of the post. None means unknown (allow).

    Returns:
        True if the post should be SKIPPED (too hot).
    """
    if post_ups is None:
        return False
    return post_ups >= HOT_THREAD_UPS_THRESHOLD


def _normalize(text: str) -> str:
    """Normalize text for duplicate comparison."""
    return re.sub(r'\s+', ' ', text.lower().strip())
