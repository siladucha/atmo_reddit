"""Task verification service — two-stage Reddit URL verification.

Stage 1 (URL): URL exists, accessible, correct subreddit, correct author
Stage 2 (Content): text similarity >60%, not [removed], not [deleted]

Uses existing PRAW read-only client. No new Reddit credentials needed.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.execution_task import ExecutionTask

logger = get_logger(__name__)

SIMILARITY_THRESHOLD = 0.60


@dataclass
class VerificationResult:
    """Result of URL/content verification."""
    stage: str          # "url" | "content" | "full"
    passed: bool
    checks: dict
    match_score: float | None = None
    failure_reason: str | None = None
    reddit_comment_url: str | None = None


# ---------------------------------------------------------------------------
# URL Parsing
# ---------------------------------------------------------------------------

def parse_reddit_url(url: str) -> dict | None:
    """Parse Reddit URL to extract subreddit and comment_id.

    Supports:
      https://www.reddit.com/r/{sub}/comments/{post_id}/{slug}/{comment_id}/
      https://reddit.com/r/...
      https://old.reddit.com/r/...

    Returns: {"subreddit": str, "post_id": str, "comment_id": str | None} or None
    """
    if not url:
        return None

    # Normalize
    url = url.strip().rstrip("/")

    # Pattern: /r/{sub}/comments/{post_id}/{slug}/{comment_id}
    pattern = r"(?:https?://)?(?:www\.|old\.)?reddit\.com/r/([^/]+)/comments/([^/]+)(?:/[^/]*)?(?:/([a-z0-9]+))?"
    match = re.match(pattern, url, re.IGNORECASE)
    if match:
        return {
            "subreddit": match.group(1),
            "post_id": match.group(2),
            "comment_id": match.group(3),
        }

    return None


# ---------------------------------------------------------------------------
# Stage 1: URL Verification
# ---------------------------------------------------------------------------

def verify_stage1_url(task: ExecutionTask, reddit_url: str) -> VerificationResult:
    """Stage 1: Verify URL exists, correct subreddit, correct author.

    Uses PRAW read-only client.
    """
    checks = {
        "url_parsed": False,
        "comment_exists": False,
        "not_removed": False,
        "not_deleted": False,
        "correct_subreddit": False,
        "correct_author": False,
    }

    # Parse URL
    parsed = parse_reddit_url(reddit_url)
    if not parsed:
        return VerificationResult(
            stage="url", passed=False, checks=checks,
            failure_reason="Could not parse Reddit URL format",
        )
    checks["url_parsed"] = True

    if not parsed.get("comment_id"):
        return VerificationResult(
            stage="url", passed=False, checks=checks,
            failure_reason="URL does not contain a comment ID (only post URL provided)",
        )

    # Fetch comment via PRAW
    try:
        from app.services.reddit import get_reddit_client
        reddit = get_reddit_client()
        comment = reddit.comment(id=parsed["comment_id"])
        comment.refresh()  # Force API fetch
    except Exception as e:
        error_str = str(e).lower()
        if "404" in error_str or "not found" in error_str:
            return VerificationResult(
                stage="url", passed=False, checks=checks,
                failure_reason="Comment not found on Reddit (404)",
            )
        logger.warning("PRAW error during verification: %s", str(e)[:200])
        return VerificationResult(
            stage="url", passed=False, checks=checks,
            failure_reason=f"Reddit API error: {str(e)[:100]}",
        )

    checks["comment_exists"] = True

    # Check not removed/deleted
    body = getattr(comment, "body", "") or ""
    if body == "[removed]":
        checks["not_removed"] = False
        return VerificationResult(
            stage="url", passed=False, checks=checks,
            failure_reason="Comment has been removed by moderators",
        )
    checks["not_removed"] = True

    if body == "[deleted]":
        checks["not_deleted"] = False
        return VerificationResult(
            stage="url", passed=False, checks=checks,
            failure_reason="Comment has been deleted by author",
        )
    checks["not_deleted"] = True

    # Check subreddit
    comment_sub = getattr(comment.subreddit, "display_name", "").lower()
    expected_sub = (task.subreddit or "").lower().lstrip("r/")
    checks["correct_subreddit"] = comment_sub == expected_sub
    if not checks["correct_subreddit"]:
        return VerificationResult(
            stage="url", passed=False, checks=checks,
            failure_reason=f"Wrong subreddit: expected r/{expected_sub}, got r/{comment_sub}",
        )

    # Check author
    comment_author = getattr(comment.author, "name", "").lower() if comment.author else ""
    expected_author = (task.avatar_username or "").lower()
    checks["correct_author"] = comment_author == expected_author
    if not checks["correct_author"]:
        return VerificationResult(
            stage="url", passed=False, checks=checks,
            failure_reason=f"Wrong author: expected u/{expected_author}, got u/{comment_author}",
        )

    permalink = f"https://www.reddit.com{comment.permalink}" if hasattr(comment, "permalink") else reddit_url

    return VerificationResult(
        stage="url", passed=True, checks=checks,
        reddit_comment_url=permalink,
    )


# ---------------------------------------------------------------------------
# Stage 2: Content Verification
# ---------------------------------------------------------------------------

def verify_stage2_content(task: ExecutionTask, reddit_url: str) -> VerificationResult:
    """Stage 2: Verify text similarity >60%.

    Assumes Stage 1 already passed (comment exists and is accessible).
    """
    checks = {
        "text_fetched": False,
        "text_similarity": False,
    }

    parsed = parse_reddit_url(reddit_url)
    if not parsed or not parsed.get("comment_id"):
        return VerificationResult(
            stage="content", passed=False, checks=checks,
            failure_reason="Cannot re-parse URL for content verification",
        )

    try:
        from app.services.reddit import get_reddit_client
        reddit = get_reddit_client()
        comment = reddit.comment(id=parsed["comment_id"])
        comment.refresh()
    except Exception as e:
        return VerificationResult(
            stage="content", passed=False, checks=checks,
            failure_reason=f"Reddit API error on content fetch: {str(e)[:100]}",
        )

    body = getattr(comment, "body", "") or ""
    checks["text_fetched"] = True

    # Normalize and compare
    actual_text = _normalize_text(body)
    expected_text = _normalize_text(task.generated_text or "")

    if not expected_text:
        # No generated text to compare — pass by default
        checks["text_similarity"] = True
        return VerificationResult(
            stage="content", passed=True, checks=checks, match_score=1.0,
            reddit_comment_url=reddit_url,
        )

    ratio = SequenceMatcher(None, actual_text, expected_text).ratio()
    checks["text_similarity"] = ratio >= SIMILARITY_THRESHOLD

    if not checks["text_similarity"]:
        return VerificationResult(
            stage="content", passed=False, checks=checks,
            match_score=round(ratio, 3),
            failure_reason=f"Text similarity too low: {ratio:.1%} (threshold: {SIMILARITY_THRESHOLD:.0%})",
        )

    permalink = f"https://www.reddit.com{comment.permalink}" if hasattr(comment, "permalink") else reddit_url

    return VerificationResult(
        stage="content", passed=True, checks=checks,
        match_score=round(ratio, 3),
        reddit_comment_url=permalink,
    )


# ---------------------------------------------------------------------------
# Full Verification (both stages + state updates)
# ---------------------------------------------------------------------------

def verify_full(db: Session, task_id: uuid.UUID, reddit_url: str) -> VerificationResult:
    """Run both verification stages and update task/draft/slot status.

    Includes all audit patches:
    - URL reuse prevention
    - Slot already-posted guard (race condition protection)
    - State machine validation
    """
    task = db.query(ExecutionTask).filter(ExecutionTask.id == task_id).first()
    if not task:
        return VerificationResult(
            stage="full", passed=False, checks={},
            failure_reason="Task not found",
        )

    # Terminal state guard
    if task.status in ("verified", "expired", "cancelled"):
        return VerificationResult(
            stage="full", passed=False, checks={},
            failure_reason=f"Task is in terminal state: {task.status}",
        )

    # --- AUDIT PATCH 1: URL reuse prevention ---
    existing_with_url = (
        db.query(ExecutionTask)
        .filter(
            ExecutionTask.submitted_url == reddit_url,
            ExecutionTask.status == "verified",
            ExecutionTask.id != task.id,
        )
        .first()
    )
    if existing_with_url:
        return VerificationResult(
            stage="full", passed=False, checks={},
            failure_reason=f"URL already used for verified task {existing_with_url.task_code}",
        )

    # --- AUDIT PATCH 2: Slot already-posted guard ---
    slot = db.query(EPGSlot).filter(EPGSlot.id == task.epg_slot_id).first()
    if slot and slot.status == "posted":
        now = datetime.now(timezone.utc)
        task.status = "cancelled"
        task.status_changed_at = now
        task.cancel_reason = "slot_already_posted_by_other_channel"
        history = task.status_history or []
        history.append({"status": "cancelled", "at": now.isoformat(), "by": "system", "reason": "slot_already_posted"})
        task.status_history = history
        db.commit()
        return VerificationResult(
            stage="full", passed=False, checks={},
            failure_reason="Slot was already posted by another execution channel",
        )

    # Stage 1: URL verification
    result1 = verify_stage1_url(task, reddit_url)
    if not result1.passed:
        task.failure_reason = result1.failure_reason
        task.verification_result = {"stage1": result1.checks}
        db.commit()
        return result1

    # Update to url_verified
    now = datetime.now(timezone.utc)
    task.status = "url_verified"
    task.status_changed_at = now
    task.submitted_url = reddit_url
    history = task.status_history or []
    history.append({"status": "url_verified", "at": now.isoformat(), "by": "system"})
    task.status_history = history
    db.flush()

    # Stage 2: Content verification
    result2 = verify_stage2_content(task, reddit_url)
    if not result2.passed:
        # Stay at url_verified — Reddit may need indexing time
        task.verification_result = {"stage1": result1.checks, "stage2": result2.checks, "match_score": result2.match_score}
        db.commit()
        return result2

    # --- BOTH STAGES PASSED — finalize ---
    task.status = "verified"
    task.status_changed_at = now
    task.verified_at = now
    task.verification_result = {
        "stage1": result1.checks,
        "stage2": result2.checks,
        "match_score": result2.match_score,
    }
    history.append({"status": "verified", "at": now.isoformat(), "by": "system"})
    task.status_history = history

    # Update downstream: draft + slot
    if task.draft_id:
        draft = db.query(CommentDraft).filter(CommentDraft.id == task.draft_id).first()
        if draft:
            draft.status = "posted"
            draft.posted_at = now
            draft.reddit_comment_url = result2.reddit_comment_url or reddit_url

    if slot:
        slot.status = "posted"
        slot.posted_at = now

    db.commit()

    logger.info(
        "Task %s verified: url=%s match=%.0f%%",
        task.task_code, reddit_url[:60], (result2.match_score or 0) * 100,
    )

    # Notify client
    try:
        from app.services.task_notifications import notify_draft_posted
        if task.client_id:
            notify_draft_posted(task.client_id, subreddit=task.subreddit, reddit_url=result2.reddit_comment_url)
    except Exception:
        pass

    return VerificationResult(
        stage="full", passed=True,
        checks={**result1.checks, **result2.checks},
        match_score=result2.match_score,
        reddit_comment_url=result2.reddit_comment_url,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, collapse whitespace, strip."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    # Remove markdown formatting
    text = re.sub(r"[*_~`#>]", "", text)
    return text
