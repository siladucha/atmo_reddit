"""Keyword analytics — operational awareness for keyword relevance.

Provides per-keyword stats: which subreddits match, how many threads,
which avatars engaged on threads containing the keyword.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.thread import RedditThread
from app.models.thread_score import ThreadScore
from app.models.comment_draft import CommentDraft
from app.models.avatar import Avatar


@dataclass
class KeywordSubredditHit:
    """How a keyword performs in a specific subreddit."""
    subreddit: str
    thread_count: int
    engage_count: int  # threads tagged 'engage'
    latest_hit: datetime | None


@dataclass
class KeywordAvatarHit:
    """Which avatar engaged on threads matching this keyword."""
    avatar_id: str
    avatar_username: str
    draft_count: int


@dataclass
class KeywordStats:
    """Full stats for a single keyword."""
    name: str
    priority: str
    total_threads: int  # threads where keyword appears in title/body
    engage_threads: int  # of those, tagged 'engage'
    drafts_generated: int  # comment drafts on matching threads
    subreddit_hits: list[KeywordSubredditHit] = field(default_factory=list)
    avatar_hits: list[KeywordAvatarHit] = field(default_factory=list)
    last_seen: datetime | None = None


def get_keyword_stats_for_client(
    db: Session,
    client_id: uuid.UUID,
    days: int = 30,
) -> list[KeywordStats]:
    """Compute keyword analytics for a client over the last N days.

    For each keyword, searches threads (title + body) to find matches,
    then aggregates by subreddit and avatar engagement.
    """
    from app.services.admin import get_client_keywords

    keywords = get_client_keywords(db, client_id)
    if not keywords:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Pre-fetch all client threads from the period
    threads = (
        db.query(RedditThread)
        .filter(
            RedditThread.client_id == client_id,
            RedditThread.created_at >= cutoff,
        )
        .all()
    )

    # Pre-fetch scores for these threads
    thread_ids = [t.id for t in threads]
    scores_map: dict[uuid.UUID, ThreadScore] = {}
    if thread_ids:
        scores = (
            db.query(ThreadScore)
            .filter(
                ThreadScore.thread_id.in_(thread_ids),
                ThreadScore.client_id == client_id,
            )
            .all()
        )
        scores_map = {s.thread_id: s for s in scores}

    # Pre-fetch drafts for these threads
    drafts_by_thread: dict[uuid.UUID, list[CommentDraft]] = {}
    if thread_ids:
        drafts = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.thread_id.in_(thread_ids),
                CommentDraft.client_id == client_id,
            )
            .all()
        )
        for d in drafts:
            drafts_by_thread.setdefault(d.thread_id, []).append(d)

    results: list[KeywordStats] = []

    for kw in keywords:
        kw_name = kw["name"].lower()
        stats = KeywordStats(
            name=kw["name"],
            priority=kw["priority"],
            total_threads=0,
            engage_threads=0,
            drafts_generated=0,
        )

        subreddit_data: dict[str, dict] = {}  # subreddit -> {count, engage, latest}
        avatar_data: dict[str, dict] = {}  # avatar_id -> {username, count}

        for thread in threads:
            title = (thread.post_title or "").lower()
            body = (thread.post_body or "").lower()

            if kw_name not in title and kw_name not in body:
                continue

            stats.total_threads += 1

            # Track last seen
            if stats.last_seen is None or thread.created_at > stats.last_seen:
                stats.last_seen = thread.created_at

            # Subreddit breakdown
            sub = thread.subreddit or "unknown"
            if sub not in subreddit_data:
                subreddit_data[sub] = {"count": 0, "engage": 0, "latest": None}
            subreddit_data[sub]["count"] += 1
            if subreddit_data[sub]["latest"] is None or thread.created_at > subreddit_data[sub]["latest"]:
                subreddit_data[sub]["latest"] = thread.created_at

            # Check score tag
            score = scores_map.get(thread.id)
            if score and score.tag == "engage":
                stats.engage_threads += 1
                subreddit_data[sub]["engage"] += 1

            # Check drafts
            thread_drafts = drafts_by_thread.get(thread.id, [])
            stats.drafts_generated += len(thread_drafts)
            for draft in thread_drafts:
                aid = str(draft.avatar_id)
                if aid not in avatar_data:
                    avatar_data[aid] = {
                        "username": draft.avatar.reddit_username if draft.avatar else "?",
                        "count": 0,
                    }
                avatar_data[aid]["count"] += 1

        # Build sub-objects
        stats.subreddit_hits = sorted(
            [
                KeywordSubredditHit(
                    subreddit=sub,
                    thread_count=d["count"],
                    engage_count=d["engage"],
                    latest_hit=d["latest"],
                )
                for sub, d in subreddit_data.items()
            ],
            key=lambda x: x.thread_count,
            reverse=True,
        )

        stats.avatar_hits = sorted(
            [
                KeywordAvatarHit(
                    avatar_id=aid,
                    avatar_username=d["username"],
                    draft_count=d["count"],
                )
                for aid, d in avatar_data.items()
            ],
            key=lambda x: x.draft_count,
            reverse=True,
        )

        results.append(stats)

    return results
