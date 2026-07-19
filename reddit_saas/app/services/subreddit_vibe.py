"""Subreddit Daily Vibe Analysis.

Provides fresh, same-day atmospheric context for EPG generation.
Answers: "What's happening in this subreddit TODAY?"

Unlike emotional_profile (weekly, historical tone patterns),
daily vibe captures current mood, trending topics, and community energy.

Runs: before EPG generation, for each subreddit participating in today's slots.
Cost: Gemini Flash ~$0.0003/sub. Cached per day (one analysis per sub per day).
"""

import time
import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.services.ai import call_llm_json, log_ai_usage

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Prompt
# ─────────────────────────────────────────────────────────────────────

VIBE_SYSTEM_PROMPT = """You are a Reddit community observer. Analyze the current hot posts from a subreddit and describe today's atmosphere in 3-5 sentences.

OUTPUT FORMAT (strict JSON):
{
  "mood": "one word (e.g. excited, frustrated, supportive, memey, analytical, celebratory, angry, curious)",
  "trending_topics": ["topic 1", "topic 2", "topic 3"],
  "energy_level": "low|medium|high",
  "vibe_summary": "2-4 sentences describing today's atmosphere. What are people talking about? What emotions dominate? What kind of comments would fit right now?"
}

RULES:
- Return ONLY valid JSON. No markdown, no code blocks.
- Base your analysis ONLY on the posts provided. Don't assume from the subreddit name.
- "trending_topics": 2-5 items. Specific topics/themes from today's posts (not generic category names).
- "vibe_summary": Be specific and actionable. A commenter should read this and know what tone/angle to use TODAY.
- Focus on CURRENT energy, not the sub's historical personality."""

VIBE_USER_PROMPT = """Subreddit: r/{subreddit_name}

Today's hot posts (titles + engagement):

{posts_text}

Describe the current vibe of this subreddit based on these posts. Return JSON only."""


# ─────────────────────────────────────────────────────────────────────
# Core Functions
# ─────────────────────────────────────────────────────────────────────


def get_daily_vibe(db: Session, subreddit_name: str) -> Optional[dict]:
    """Get today's vibe for a subreddit. Returns cached if fresh, None if unavailable.

    Returns dict with: mood, trending_topics, energy_level, vibe_summary
    Or None if no vibe available (no data, sub not in registry, etc.)
    """
    from app.models.subreddit import Subreddit

    subreddit_name_lower = subreddit_name.strip().lower()

    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name_lower)
        .first()
    )
    if not subreddit:
        return None

    # Check if cached for today
    today = date.today()
    if (
        subreddit.daily_vibe
        and subreddit.daily_vibe_date
        and subreddit.daily_vibe_date == today
    ):
        return subreddit.daily_vibe

    return None


def compute_daily_vibe(db: Session, subreddit_name: str) -> Optional[dict]:
    """Compute fresh daily vibe for a subreddit using hot posts from DB.

    Uses already-scraped posts (hobby_subreddits + reddit_threads) to avoid
    extra PRAW calls. Falls back to PRAW only if no DB data available.

    Returns dict with vibe data, or None on failure.
    Stores result on Subreddit model for same-day caching.
    """
    from app.config import get_config
    from app.models.hobby import HobbySubreddit
    from app.models.subreddit import Subreddit
    from app.models.thread import RedditThread
    from datetime import timedelta

    subreddit_name_lower = subreddit_name.strip().lower()

    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name_lower)
        .first()
    )

    # Check cache first
    today = date.today()
    if (
        subreddit
        and subreddit.daily_vibe
        and subreddit.daily_vibe_date
        and subreddit.daily_vibe_date == today
    ):
        return subreddit.daily_vibe

    # Gather posts from DB (last 48h — fresh enough to reflect current atmosphere)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    posts_data = []

    # Source 1: reddit_threads (professional pipeline)
    threads = (
        db.query(RedditThread)
        .filter(
            sa_func.lower(RedditThread.subreddit) == subreddit_name_lower,
            RedditThread.scraped_at >= cutoff,
        )
        .order_by(RedditThread.ups.desc().nullslast())
        .limit(10)
        .all()
    )
    for t in threads:
        posts_data.append({
            "title": (t.post_title or "")[:120],
            "ups": t.ups or 0,
            "comments": t.num_comments or 0,
            "body_snippet": (t.post_body or "")[:150],
        })

    # Source 2: hobby_subreddits (hobby pipeline)
    hobby_posts = (
        db.query(HobbySubreddit)
        .filter(
            sa_func.lower(HobbySubreddit.subreddit) == subreddit_name_lower,
            HobbySubreddit.created_at >= cutoff,
        )
        .order_by(HobbySubreddit.post_ups.desc().nullslast())
        .limit(10)
        .all()
    )
    for hp in hobby_posts:
        # Avoid duplicates by title
        title = (hp.post_title or "")[:120]
        if not any(p["title"] == title for p in posts_data):
            posts_data.append({
                "title": title,
                "ups": hp.post_ups or 0,
                "comments": 0,
                "body_snippet": (hp.post_body or "")[:150],
            })

    # Deduplicate and take top 10 by engagement
    posts_data.sort(key=lambda p: p["ups"], reverse=True)
    posts_data = posts_data[:10]

    if len(posts_data) < 3:
        # Not enough data — try PRAW as fallback
        posts_data = _fetch_hot_posts_praw(subreddit_name_lower)

    if len(posts_data) < 3:
        logger.info(
            "VIBE | sub=r/%s | skipped (only %d posts available)",
            subreddit_name_lower, len(posts_data),
        )
        return None

    # Format posts for prompt
    lines = []
    for i, p in enumerate(posts_data, 1):
        line = f"{i}. [{p['ups']}↑] {p['title']}"
        if p.get("body_snippet"):
            line += f"\n   {p['body_snippet']}"
        lines.append(line)

    posts_text = "\n".join(lines)

    # LLM call — Gemini Flash (cheapest)
    model = get_config("llm_scoring_model")
    messages = [
        {"role": "system", "content": VIBE_SYSTEM_PROMPT},
        {"role": "user", "content": VIBE_USER_PROMPT.format(
            subreddit_name=subreddit_name_lower,
            posts_text=posts_text,
        )},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=model,
            temperature=0.4,
            max_tokens=400,
        )
    except Exception as e:
        logger.warning("VIBE | sub=r/%s | llm_error=%s", subreddit_name_lower, str(e)[:100])
        return None

    # Log cost
    try:
        log_ai_usage(
            db=db,
            client_id=None,
            operation="subreddit_daily_vibe",
            result=result,
            subreddit_name=subreddit_name_lower,
            triggered_by="epg_generation",
        )
    except Exception:
        pass

    data = result.get("data", {})

    # Validate minimal structure
    vibe = {
        "mood": data.get("mood", "neutral"),
        "trending_topics": data.get("trending_topics", [])[:5],
        "energy_level": data.get("energy_level", "medium"),
        "vibe_summary": data.get("vibe_summary", ""),
    }

    if not vibe["vibe_summary"]:
        logger.warning("VIBE | sub=r/%s | empty vibe_summary", subreddit_name_lower)
        return None

    # Cache on subreddit model
    if subreddit:
        subreddit.daily_vibe = vibe
        subreddit.daily_vibe_date = today
        db.commit()

    logger.info(
        "VIBE | sub=r/%s | mood=%s energy=%s topics=%s",
        subreddit_name_lower, vibe["mood"], vibe["energy_level"],
        ",".join(vibe["trending_topics"][:3]),
    )
    return vibe


def compute_vibe_for_epg_subreddits(db: Session, avatar_id: uuid.UUID, plan_date: date | None = None) -> dict[str, dict]:
    """Compute daily vibe for all subreddits that have planned EPG slots today.

    Call this BEFORE generate_all_planned_slots() to ensure vibe is cached.

    Returns: {subreddit_name: vibe_dict} for all subs with successful analysis.
    """
    from app.models.epg_slot import EPGSlot
    from app.models.hobby import HobbySubreddit
    from app.models.thread import RedditThread

    if plan_date is None:
        plan_date = date.today()

    # Get all planned slots for this avatar today
    slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == avatar_id,
            EPGSlot.plan_date == plan_date,
            EPGSlot.status == "planned",
        )
        .all()
    )

    # Collect unique subreddit names from slots
    sub_names: set[str] = set()
    for slot in slots:
        if slot.thread_id:
            thread = db.query(RedditThread).filter(RedditThread.id == slot.thread_id).first()
            if thread and thread.subreddit:
                sub_names.add(thread.subreddit.lower())
        elif slot.hobby_post_id:
            hp = db.query(HobbySubreddit).filter(HobbySubreddit.id == slot.hobby_post_id).first()
            if hp and hp.subreddit:
                sub_names.add(hp.subreddit.lower())

    if not sub_names:
        return {}

    logger.info(
        "VIBE | Computing daily vibe for %d subreddits (avatar=%s)",
        len(sub_names), avatar_id,
    )

    results = {}
    for sub_name in sub_names:
        vibe = compute_daily_vibe(db, sub_name)
        if vibe:
            results[sub_name] = vibe

    logger.info(
        "VIBE | Computed %d/%d vibes (avatar=%s)",
        len(results), len(sub_names), avatar_id,
    )
    return results


def get_vibe_context_for_prompt(db: Session, subreddit_name: str) -> str:
    """Get formatted vibe context string for injection into generation prompt.

    Returns a formatted string suitable for appending to the system prompt,
    or empty string if no vibe available for today.

    Non-blocking: returns "" rather than raising exceptions.
    """
    try:
        vibe = get_daily_vibe(db, subreddit_name)
        if not vibe:
            return ""

        parts = [f"\n## TODAY'S SUBREDDIT VIBE — r/{subreddit_name}"]
        parts.append(f"Mood: {vibe['mood']} | Energy: {vibe['energy_level']}")

        topics = vibe.get("trending_topics", [])
        if topics:
            parts.append(f"Trending now: {', '.join(topics)}")

        summary = vibe.get("vibe_summary", "")
        if summary:
            parts.append(f"What's happening: {summary}")

        parts.append("→ Match this energy. Your comment should feel like it belongs in TODAY's conversation.")

        return "\n".join(parts)
    except Exception as e:
        logger.debug("VIBE | Failed to get vibe context for r/%s: %s", subreddit_name, str(e)[:60])
        return ""


# ─────────────────────────────────────────────────────────────────────
# PRAW Fallback (when no DB data available)
# ─────────────────────────────────────────────────────────────────────


def _fetch_hot_posts_praw(subreddit_name: str) -> list[dict]:
    """Fetch hot posts via PRAW as fallback when DB has no fresh data.

    Lightweight: only titles + scores, no comment fetching.
    """
    try:
        from app.services.reddit import get_reddit_client
        reddit = get_reddit_client(caller="subreddit_vibe")
        sub = reddit.subreddit(subreddit_name)

        posts = []
        for submission in sub.hot(limit=7):
            if submission.stickied:
                continue
            posts.append({
                "title": (submission.title or "")[:120],
                "ups": submission.score or 0,
                "comments": submission.num_comments or 0,
                "body_snippet": (submission.selftext or "")[:150],
            })
            if len(posts) >= 7:
                break

        return posts
    except Exception as e:
        logger.warning("VIBE | PRAW fallback failed for r/%s: %s", subreddit_name, str(e)[:80])
        return []
