"""Day 1 Landscape Report — auto-generated on onboarding completion.

Shows the "aha moment": threads where brand is absent, competitor mentions,
high-intent discussions, and sample AI draft previews.

Works WITHOUT avatars — uses client keywords + subreddits only.
"""

import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.logging_config import get_logger
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.subreddit import ClientSubredditAssignment, Subreddit

logger = get_logger(__name__)


def generate_landscape_report(db: Session, client_id: uuid.UUID) -> dict:
    """Generate Day 1 Landscape Report for a client.

    Does NOT require avatars. Uses existing scraped threads + client keywords.
    If no threads exist yet (brand new client), triggers scraping first.

    Returns:
        {
            "generated_at": datetime,
            "subreddits_monitored": int,
            "threads_found": int,
            "threads_relevant": int,
            "competitor_mentions": [{"thread_title": ..., "subreddit": ..., "competitor": ..., "url": ...}],
            "high_intent_threads": [{"title": ..., "subreddit": ..., "upvotes": ..., "url": ..., "why": ...}],
            "brand_absent_threads": [{"title": ..., "subreddit": ..., "upvotes": ..., "url": ...}],
            "sample_drafts": [{"thread_title": ..., "subreddit": ..., "draft_text": ...}],
            "share_of_voice": {"brand": 0, "competitors": {...}},
        }
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return {"error": "Client not found"}

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    # Get client's subreddits
    assignments = (
        db.query(ClientSubredditAssignment)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active.is_(True),
        )
        .all()
    )
    subreddit_names = [a.subreddit.subreddit_name for a in assignments if a.subreddit]

    # Get recent threads in those subreddits
    threads = (
        db.query(RedditThread)
        .filter(
            RedditThread.subreddit.in_(subreddit_names),
            RedditThread.created_at >= week_ago,
        )
        .order_by(RedditThread.ups.desc().nullslast())
        .limit(200)
        .all()
    )

    # Extract keywords and competitors
    keywords_data = client.keywords or {}
    all_keywords = []
    for tier in ("high", "medium", "low"):
        all_keywords.extend(keywords_data.get(tier, []))
    all_keywords_lower = [k.lower() for k in all_keywords]

    competitors = _extract_competitor_names(client.competitive_landscape)
    brand_names = [client.brand_name.lower()] if client.brand_name else []

    # Analyze threads
    competitor_mentions = []
    high_intent = []
    brand_absent = []
    relevant_count = 0

    for thread in threads:
        text = f"{thread.post_title or ''} {(thread.post_body or '')[:500]}".lower()

        # Check keyword relevance
        is_relevant = any(kw in text for kw in all_keywords_lower)
        if is_relevant:
            relevant_count += 1

        # Check competitor mentions
        for comp in competitors:
            if comp.lower() in text:
                competitor_mentions.append({
                    "thread_title": thread.post_title or "",
                    "subreddit": thread.subreddit or "",
                    "competitor": comp,
                    "url": thread.url or "",
                    "upvotes": thread.ups or 0,
                })
                break

        # Check brand presence
        brand_mentioned = any(b in text for b in brand_names)

        # High-intent: relevant + high engagement + brand absent
        if is_relevant and not brand_mentioned and (thread.ups or 0) >= 5:
            high_intent.append({
                "title": thread.post_title or "",
                "subreddit": thread.subreddit or "",
                "upvotes": thread.ups or 0,
                "url": thread.url or "",
                "why": "Relevant to your keywords, your brand not mentioned",
            })

        # Brand absent from relevant threads
        if is_relevant and not brand_mentioned:
            brand_absent.append({
                "title": thread.post_title or "",
                "subreddit": thread.subreddit or "",
                "upvotes": thread.ups or 0,
                "url": thread.url or "",
            })

    # Sort by impact
    competitor_mentions.sort(key=lambda x: x.get("upvotes", 0), reverse=True)
    high_intent.sort(key=lambda x: x.get("upvotes", 0), reverse=True)
    brand_absent.sort(key=lambda x: x.get("upvotes", 0), reverse=True)

    # Share of voice (competitor mentions vs brand mentions)
    sov = {"brand": 0, "competitors": {}}
    brand_mention_count = sum(
        1 for t in threads
        if any(b in f"{t.post_title or ''} {(t.post_body or '')[:500]}".lower() for b in brand_names)
    )
    sov["brand"] = brand_mention_count
    for comp in competitors:
        count = sum(
            1 for t in threads
            if comp.lower() in f"{t.post_title or ''} {(t.post_body or '')[:500]}".lower()
        )
        if count > 0:
            sov["competitors"][comp] = count

    report = {
        "generated_at": now.isoformat(),
        "subreddits_monitored": len(subreddit_names),
        "threads_found": len(threads),
        "threads_relevant": relevant_count,
        "competitor_mentions": competitor_mentions[:10],
        "high_intent_threads": high_intent[:10],
        "brand_absent_threads": brand_absent[:15],
        "sample_drafts": [],  # Will be populated by AI draft generation (phase 2)
        "share_of_voice": sov,
    }

    logger.info(
        "Landscape report for %s: %d threads, %d relevant, %d competitor mentions, %d high-intent",
        client.client_name, len(threads), relevant_count,
        len(competitor_mentions), len(high_intent),
    )

    return report


def _extract_competitor_names(competitive_landscape: str | None) -> list[str]:
    """Extract competitor names from text field."""
    if not competitive_landscape:
        return []
    import re
    competitors = []
    for line in competitive_landscape.split("\n"):
        line = line.strip().strip("-•*").strip()
        if not line:
            continue
        parts = re.split(r"[,;]", line)
        for part in parts:
            part = part.strip()
            if part and len(part) < 40 and len(part.split()) <= 3:
                competitors.append(part)
    return list(set(competitors))[:10]
