"""Draft Reconciliation Service — auto-link approved drafts to Reddit comments.

When an avatar owner posts a RAMP-generated comment manually (via mobile app,
browser, or EPG email without submitting the permalink back), the system has
an approved CommentDraft that never transitions to "posted".

This service fetches the avatar's recent Reddit comments, compares against
unresolved approved drafts, and when a match is found:
1. Transitions the draft to status="posted"
2. Sets reddit_comment_url, posted_at
3. Emits an activity event for transparency

Matching strategy (multi-signal, ranked):
  1. Exact body match (first 120 chars normalized)
  2. High-similarity fuzzy match (≥85% token overlap)
  3. Thread + avatar match (comment in same thread, same avatar, close timing)

Schedule: Runs as part of karma_tracking (every 4h), only for avatars
that have approved drafts pending reconciliation.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.thread import RedditThread

logger = get_logger(__name__)

# How old an approved draft can be before we stop trying to reconcile
MAX_DRAFT_AGE_DAYS = 14

# Minimum token overlap ratio for fuzzy match (0.0 to 1.0)
FUZZY_MATCH_THRESHOLD = 0.85

# Maximum time gap between draft creation and Reddit comment (hours)
MAX_TIME_GAP_HOURS = 72


@dataclass
class ReconciliationMatch:
    """A confirmed match between a draft and a Reddit comment."""
    draft_id: uuid.UUID
    reddit_comment_id: str
    reddit_comment_url: str
    match_method: str  # "exact_body" | "fuzzy_body" | "thread_timing"
    confidence: float  # 0.0 to 1.0
    reddit_score: int
    posted_at: datetime


@dataclass
class ReconciliationResult:
    """Summary of reconciliation for one avatar."""
    avatar_id: uuid.UUID
    username: str
    drafts_checked: int = 0
    matches_found: int = 0
    matches: list[ReconciliationMatch] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _normalize_text(text: str) -> str:
    """Normalize text for comparison: lowercase, strip whitespace, collapse spaces."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    # Remove common markdown formatting
    text = re.sub(r'[*_~`]', '', text)
    return text


def _tokenize(text: str) -> set[str]:
    """Split text into word tokens for overlap calculation."""
    return set(re.findall(r'\b\w+\b', text.lower()))


def _token_overlap(text_a: str, text_b: str) -> float:
    """Calculate Jaccard-like token overlap between two texts.

    Returns ratio of shared tokens to total unique tokens (0.0 to 1.0).
    """
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _get_draft_text(draft: CommentDraft) -> str:
    """Get the final text of a draft (edited preferred over AI-generated)."""
    return (draft.edited_draft or draft.ai_draft or "").strip()


def _build_reddit_comment_url(subreddit: str, thread_id: str, comment_id: str) -> str:
    """Build full Reddit comment URL from components."""
    return f"https://www.reddit.com/r/{subreddit}/comments/{thread_id}/_/{comment_id}/"


def get_unreconciled_drafts(
    db: Session,
    avatar_id: uuid.UUID,
) -> list[CommentDraft]:
    """Find approved drafts that haven't been posted (candidates for reconciliation).

    Returns drafts that are:
    - status = 'approved'
    - created within MAX_DRAFT_AGE_DAYS
    - have text content (ai_draft or edited_draft)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_DRAFT_AGE_DAYS)

    drafts = (
        db.query(CommentDraft)
        .filter(
            and_(
                CommentDraft.avatar_id == avatar_id,
                CommentDraft.status == "approved",
                CommentDraft.created_at >= cutoff,
            )
        )
        .order_by(CommentDraft.created_at.desc())
        .all()
    )

    # Filter to those with actual text content
    return [d for d in drafts if _get_draft_text(d)]


def reconcile_avatar_drafts(
    db: Session,
    avatar: Avatar,
    reddit_comments: list[dict],
) -> ReconciliationResult:
    """Match approved drafts to Reddit comments for a single avatar.

    Args:
        db: SQLAlchemy session.
        avatar: The avatar to reconcile.
        reddit_comments: List of dicts from Reddit API, each containing:
            - id: Reddit comment ID
            - body: Comment body text
            - subreddit: Subreddit display name
            - score: Comment karma
            - created_utc: Unix timestamp
            - permalink: Comment permalink (relative)
            - link_id: Parent submission ID (t3_xxx format)

    Returns:
        ReconciliationResult with all matches found and applied.
    """
    result = ReconciliationResult(
        avatar_id=avatar.id,
        username=avatar.reddit_username,
    )

    # Get unreconciled drafts
    drafts = get_unreconciled_drafts(db, avatar.id)
    result.drafts_checked = len(drafts)

    if not drafts:
        return result

    if not reddit_comments:
        return result

    # Build lookup structures for drafts
    # Key: normalized first 120 chars → list of drafts
    draft_by_body: dict[str, list[CommentDraft]] = {}
    for draft in drafts:
        draft_text = _normalize_text(_get_draft_text(draft))[:120]
        if draft_text:
            draft_by_body.setdefault(draft_text, []).append(draft)

    # Track which drafts have been matched (avoid double-matching)
    matched_draft_ids: set[uuid.UUID] = set()

    # Pass 1: Exact body match (first 120 chars normalized)
    for comment in reddit_comments:
        comment_body = _normalize_text(comment.get("body", ""))[:120]
        if not comment_body:
            continue

        if comment_body in draft_by_body:
            candidates = draft_by_body[comment_body]
            for draft in candidates:
                if draft.id in matched_draft_ids:
                    continue

                match = _apply_match(
                    db, draft, comment, "exact_body", confidence=0.98
                )
                if match:
                    result.matches.append(match)
                    matched_draft_ids.add(draft.id)
                    break  # One comment → one draft

    # Pass 2: Fuzzy body match (≥85% token overlap)
    for comment in reddit_comments:
        comment_body = comment.get("body", "")
        if not comment_body or len(comment_body.strip()) < 20:
            continue

        comment_created = datetime.fromtimestamp(
            comment.get("created_utc", 0), tz=timezone.utc
        )

        for draft in drafts:
            if draft.id in matched_draft_ids:
                continue

            draft_text = _get_draft_text(draft)
            if not draft_text or len(draft_text) < 20:
                continue

            # Time sanity check: comment should be after draft creation
            if comment_created < draft.created_at:
                continue

            # Time gap check
            gap_hours = (comment_created - draft.created_at).total_seconds() / 3600
            if gap_hours > MAX_TIME_GAP_HOURS:
                continue

            overlap = _token_overlap(draft_text, comment_body)
            if overlap >= FUZZY_MATCH_THRESHOLD:
                match = _apply_match(
                    db, draft, comment, "fuzzy_body", confidence=round(overlap, 3)
                )
                if match:
                    result.matches.append(match)
                    matched_draft_ids.add(draft.id)
                    break  # Move to next comment

    # Pass 3: Thread + timing match (same thread, same avatar, close timing)
    for comment in reddit_comments:
        comment_link_id = comment.get("link_id", "")  # t3_xxx
        if not comment_link_id:
            continue

        # Extract reddit_native_id from link_id (remove t3_ prefix)
        thread_native_id = comment_link_id.replace("t3_", "")
        comment_created = datetime.fromtimestamp(
            comment.get("created_utc", 0), tz=timezone.utc
        )

        for draft in drafts:
            if draft.id in matched_draft_ids:
                continue

            # Draft must be linked to a thread
            if not draft.thread_id:
                continue

            # Load thread to compare
            thread = draft.thread
            if not thread:
                continue

            if thread.reddit_native_id != thread_native_id:
                continue

            # Time sanity: comment after draft creation, within window
            if comment_created < draft.created_at:
                continue

            gap_hours = (comment_created - draft.created_at).total_seconds() / 3600
            if gap_hours > MAX_TIME_GAP_HOURS:
                continue

            # Additional signal: body length should be similar (±50%)
            draft_text = _get_draft_text(draft)
            comment_body = comment.get("body", "")
            if draft_text and comment_body:
                len_ratio = len(comment_body) / max(len(draft_text), 1)
                if len_ratio < 0.5 or len_ratio > 2.0:
                    continue

            match = _apply_match(
                db, draft, comment, "thread_timing", confidence=0.75
            )
            if match:
                result.matches.append(match)
                matched_draft_ids.add(draft.id)
                break

    result.matches_found = len(result.matches)
    return result


def _apply_match(
    db: Session,
    draft: CommentDraft,
    reddit_comment: dict,
    method: str,
    confidence: float,
) -> ReconciliationMatch | None:
    """Apply a reconciliation match: update draft status and return match record.

    Returns None if the update fails for any reason.
    """
    try:
        comment_id = reddit_comment["id"]
        subreddit = reddit_comment.get("subreddit", "")
        link_id = reddit_comment.get("link_id", "").replace("t3_", "")
        permalink = reddit_comment.get("permalink", "")
        score = reddit_comment.get("score", 0)
        created_utc = reddit_comment.get("created_utc", 0)
        posted_at = datetime.fromtimestamp(created_utc, tz=timezone.utc)

        # Build URL
        if permalink:
            reddit_url = f"https://www.reddit.com{permalink}"
        else:
            reddit_url = _build_reddit_comment_url(subreddit, link_id, comment_id)

        # Update the draft
        draft.status = "posted"
        draft.posted_at = posted_at
        draft.reddit_comment_url = reddit_url
        draft.reddit_score = score

        db.flush()

        # Emit activity event
        _emit_reconciliation_event(db, draft, method, confidence)

        logger.info(
            "DRAFT_RECONCILED | draft_id=%s | avatar=%s | method=%s | "
            "confidence=%.2f | reddit_comment_id=%s | subreddit=r/%s",
            draft.id, draft.avatar.reddit_username if draft.avatar else "?",
            method, confidence, comment_id, subreddit,
        )

        return ReconciliationMatch(
            draft_id=draft.id,
            reddit_comment_id=comment_id,
            reddit_comment_url=reddit_url,
            match_method=method,
            confidence=confidence,
            reddit_score=score,
            posted_at=posted_at,
        )

    except Exception as e:
        logger.error(
            "DRAFT_RECONCILE_FAILED | draft_id=%s | method=%s | error=%s",
            draft.id, method, str(e)[:200],
        )
        db.rollback()
        return None


def _emit_reconciliation_event(
    db: Session,
    draft: CommentDraft,
    method: str,
    confidence: float,
):
    """Emit an ActivityEvent for draft reconciliation."""
    from app.models.activity_event import ActivityEvent

    subreddit = ""
    if draft.thread:
        subreddit = getattr(draft.thread, "subreddit", "") or ""

    avatar_name = ""
    if draft.avatar:
        avatar_name = draft.avatar.reddit_username or ""

    event = ActivityEvent(
        event_type="draft_auto_reconciled",
        client_id=draft.client_id,
        message=(
            f"Auto-linked approved draft to Reddit comment by u/{avatar_name} "
            f"in r/{subreddit} (method: {method}, confidence: {confidence:.0%})"
        ),
        event_metadata={
            "draft_id": str(draft.id),
            "avatar_id": str(draft.avatar_id),
            "subreddit": subreddit,
            "match_method": method,
            "confidence": confidence,
            "reddit_comment_url": draft.reddit_comment_url,
        },
    )
    db.add(event)


def run_reconciliation_for_avatar(
    db: Session,
    avatar: Avatar,
    redditor=None,
) -> ReconciliationResult:
    """Full reconciliation flow for a single avatar.

    Fetches recent comments from Reddit (or uses provided redditor),
    then runs the matching logic.

    Args:
        db: SQLAlchemy session.
        avatar: Avatar to reconcile.
        redditor: Optional pre-fetched PRAW redditor object (saves an API call
                  when called from karma_tracking which already has it).

    Returns:
        ReconciliationResult.
    """
    from app.services.reddit import get_reddit_client
    from app.services.sanitize import ensure_username_bare
    from prawcore.exceptions import NotFound, Forbidden, RequestException

    # Quick check: does this avatar have any approved drafts to reconcile?
    drafts = get_unreconciled_drafts(db, avatar.id)
    if not drafts:
        return ReconciliationResult(
            avatar_id=avatar.id,
            username=avatar.reddit_username,
        )

    # Fetch Reddit comments
    try:
        if redditor is None:
            reddit = get_reddit_client(caller="reconciliation")
            redditor = reddit.redditor(ensure_username_bare(avatar.reddit_username))

        reddit_comments = []
        for comment in redditor.comments.new(limit=100):
            reddit_comments.append({
                "id": comment.id,
                "body": comment.body or "",
                "subreddit": comment.subreddit.display_name,
                "score": comment.score,
                "created_utc": comment.created_utc,
                "permalink": comment.permalink,
                "link_id": getattr(comment, "link_id", "") or "",
            })

    except (NotFound, Forbidden) as e:
        logger.warning(
            "RECONCILIATION_SKIP | avatar=%s | error=%s",
            avatar.reddit_username, type(e).__name__,
        )
        return ReconciliationResult(
            avatar_id=avatar.id,
            username=avatar.reddit_username,
            errors=[f"Reddit API: {type(e).__name__}"],
        )
    except (RequestException, Exception) as e:
        logger.error(
            "RECONCILIATION_ERROR | avatar=%s | error=%s",
            avatar.reddit_username, str(e)[:200],
        )
        return ReconciliationResult(
            avatar_id=avatar.id,
            username=avatar.reddit_username,
            errors=[str(e)[:200]],
        )

    # Run matching
    result = reconcile_avatar_drafts(db, avatar, reddit_comments)

    if result.matches_found > 0:
        try:
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(
                "RECONCILIATION_COMMIT_FAILED | avatar=%s | error=%s",
                avatar.reddit_username, str(e)[:200],
            )
            result.errors.append(f"Commit failed: {str(e)[:100]}")
            result.matches_found = 0
            result.matches = []

    return result
