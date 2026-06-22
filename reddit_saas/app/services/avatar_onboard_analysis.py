"""Avatar Onboard Analysis — fetches Reddit profile + AI classification in one step.

Flow:
1. PRAW: fetch last 100 comments + 25 posts + subreddits + karma breakdown
2. Claude Sonnet: one call → classification, voice_profile, strategy, hill, topics
3. Returns structured dict ready for UI display + manager approval

Cost tracked as operation="avatar_onboarding" in AIUsageLog.
"""

import time
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.client import Client
from app.services.ai import call_llm_json, log_ai_usage
from app.services.reddit import get_reddit_client

logger = get_logger(__name__)


# --------------------------------------------------------------------------
# Step 1: PRAW fetch — Medium depth (100 comments, 25 posts)
# --------------------------------------------------------------------------


def fetch_reddit_profile(reddit_username: str) -> dict:
    """Fetch Reddit profile data: comments, posts, subreddits, karma.

    Args:
        reddit_username: Reddit username (without u/ prefix)

    Returns:
        Dict with profile data or error info.
        Keys: username, account_age_days, karma_comment, karma_post,
              comments (list), posts (list), active_subreddits (dict),
              created_utc, error (if failed)
    """
    start = time.time()
    username = reddit_username.replace("u/", "").strip()

    try:
        reddit = get_reddit_client("avatar_onboarding")
        redditor = reddit.redditor(username)

        # Force fetch to validate account exists
        _ = redditor.id

        # Account metadata
        account_created = datetime.fromtimestamp(redditor.created_utc, tz=timezone.utc)
        account_age_days = (datetime.now(timezone.utc) - account_created).days

        # Fetch comments (last 100)
        comments = []
        try:
            for comment in redditor.comments.new(limit=100):
                comments.append({
                    "subreddit": str(comment.subreddit),
                    "body": comment.body[:500],  # Truncate for context window
                    "score": comment.score,
                    "created_utc": comment.created_utc,
                })
        except Exception as e:
            logger.warning("Failed to fetch comments for %s: %s", username, e)

        # Fetch posts (last 25)
        posts = []
        try:
            for submission in redditor.submissions.new(limit=25):
                posts.append({
                    "subreddit": str(submission.subreddit),
                    "title": submission.title[:200],
                    "selftext": (submission.selftext or "")[:300],
                    "score": submission.score,
                    "created_utc": submission.created_utc,
                })
        except Exception as e:
            logger.warning("Failed to fetch posts for %s: %s", username, e)

        # Aggregate subreddit activity
        subreddit_stats: dict[str, dict] = {}
        for c in comments:
            sub = c["subreddit"]
            if sub not in subreddit_stats:
                subreddit_stats[sub] = {"comments": 0, "posts": 0, "total_karma": 0}
            subreddit_stats[sub]["comments"] += 1
            subreddit_stats[sub]["total_karma"] += c["score"]
        for p in posts:
            sub = p["subreddit"]
            if sub not in subreddit_stats:
                subreddit_stats[sub] = {"comments": 0, "posts": 0, "total_karma": 0}
            subreddit_stats[sub]["posts"] += 1
            subreddit_stats[sub]["total_karma"] += p["score"]

        # Sort by total karma
        sorted_subs = dict(
            sorted(subreddit_stats.items(), key=lambda x: x[1]["total_karma"], reverse=True)
        )

        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "PRAW_FETCH | user=%s | comments=%d | posts=%d | subreddits=%d | duration_ms=%d",
            username, len(comments), len(posts), len(sorted_subs), duration_ms,
        )

        return {
            "username": username,
            "account_age_days": account_age_days,
            "karma_comment": getattr(redditor, "comment_karma", 0),
            "karma_post": getattr(redditor, "link_karma", 0),
            "created_utc": redditor.created_utc,
            "comments": comments,
            "posts": posts,
            "active_subreddits": sorted_subs,
            "duration_ms": duration_ms,
            "error": None,
        }
    except Exception as e:
        logger.error("PRAW fetch failed for %s: %s", username, e)
        return {
            "username": username,
            "error": str(e),
            "comments": [],
            "posts": [],
            "active_subreddits": {},
            "account_age_days": 0,
            "karma_comment": 0,
            "karma_post": 0,
            "created_utc": None,
            "duration_ms": int((time.time() - start) * 1000),
        }


# --------------------------------------------------------------------------
# Step 2: AI classification — one Claude Sonnet call
# --------------------------------------------------------------------------


def analyze_avatar_with_ai(
    profile_data: dict,
    client: Client | None = None,
    db: Session | None = None,
) -> dict:
    """Run AI analysis on fetched Reddit profile.

    One LLM call produces:
    - classification (type, role, synthetic_likelihood)
    - voice_profile (tone, style, vocabulary)
    - suggested_strategy (hill, topics, approach)
    - display_name suggestion
    - persona_bio suggestion
    - suggested_hobby_subreddits
    - suggested_business_subreddits

    Args:
        profile_data: Output of fetch_reddit_profile()
        client: Optional client context for better strategy
        db: Database session for cost logging

    Returns:
        Dict with AI analysis results + cost metadata
    """
    if profile_data.get("error"):
        return {
            "error": f"Cannot analyze — Reddit fetch failed: {profile_data['error']}",
            "classification": None,
            "voice_profile": None,
            "strategy": None,
        }

    # Build context for LLM
    comments_sample = profile_data["comments"][:50]  # Top 50 for context window
    posts_sample = profile_data["posts"][:15]

    comments_text = "\n".join(
        f"[r/{c['subreddit']} | score:{c['score']}] {c['body'][:250]}"
        for c in comments_sample
    )
    posts_text = "\n".join(
        f"[r/{p['subreddit']} | score:{p['score']}] {p['title']} — {p['selftext'][:150]}"
        for p in posts_sample
    )
    subreddits_text = "\n".join(
        f"r/{sub}: {stats['comments']} comments, {stats['posts']} posts, {stats['total_karma']} karma"
        for sub, stats in list(profile_data["active_subreddits"].items())[:20]
    )

    # Client context (if available)
    client_context = ""
    if client:
        client_context = f"""
CLIENT CONTEXT (this avatar will serve this client):
- Company: {client.client_name} ({client.brand_name or ''})
- Industry: {client.industry or 'Not specified'}
- Profile: {(client.company_profile or '')[:300]}
- ICP: {(client.icp_profiles or '')[:200]}
- Problem they solve: {(client.company_problem or '')[:200]}
"""

    system_prompt = """You are an expert at analyzing Reddit accounts for a managed community engagement platform.

Analyze this Reddit account and produce a structured profile. Be specific and grounded in the actual data — don't make up information not supported by the comments/posts.

Output a JSON object with these exact keys:

{
  "classification": {
    "avatar_type": "personal_creator | commentator | lurker | promoter | expert",
    "primary_role": "content_creator | community_helper | industry_expert | casual_participant",
    "synthetic_likelihood": 0-100,
    "confidence": 0-100,
    "notes": "brief explanation of classification"
  },
  "display_name": "suggested first name or persona name (natural, not username)",
  "persona_bio": "one sentence professional bio based on their actual interests/expertise (max 200 chars)",
  "voice_profile": {
    "tone": "2-3 word tone description (e.g. 'warm, technical, concise')",
    "style": "how they write — sentence structure, length preference, formatting habits",
    "vocabulary_lean": "specific jargon, phrases, or word choices they favor",
    "speech_patterns": "distinctive patterns (questions? lists? anecdotes? data?)",
    "tone_principles": "3-5 rules for writing as this person"
  },
  "strategy": {
    "hill_i_die_on": "their core belief/position they consistently advocate for",
    "helpful_mode_topics": "topics where they naturally help others (comma-separated)",
    "suggested_approach": "how this avatar should engage — what works for them",
    "strengths": "what they do well on Reddit",
    "weaknesses": "what to avoid or improve"
  },
  "subreddits": {
    "hobby": ["3-5 subreddits for credibility building based on their actual interests"],
    "business": ["3-5 subreddits for professional engagement based on their expertise"]
  },
  "suggested_phase": 1,
  "phase_reasoning": "why this phase based on karma, age, and activity"
}

RULES:
- Be specific to THIS account's actual behavior — never generic
- synthetic_likelihood: 0 = definitely real human, 100 = definitely automated
- suggested_phase: 1 (newcomer/building), 2 (established, can seed content), 3 (authority, can mention brands)
- Phase 3 requires: 2000+ karma AND 6+ months AND consistent quality
- If account has very little history, say so honestly in notes
- display_name should feel natural (like a real person's first name)
- persona_bio should be plausible for the person's actual expertise"""

    user_prompt = f"""REDDIT ACCOUNT: u/{profile_data['username']}
Account age: {profile_data['account_age_days']} days
Comment karma: {profile_data['karma_comment']}
Post karma: {profile_data['karma_post']}

ACTIVE SUBREDDITS:
{subreddits_text}

RECENT COMMENTS (newest first):
{comments_text}

RECENT POSTS (newest first):
{posts_text}
{client_context}
Analyze this account and provide the structured JSON profile."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model="anthropic/claude-sonnet-4-20250514",
            temperature=0.3,
            max_tokens=2048,
        )

        # Log AI usage
        if db:
            log_ai_usage(
                db=db,
                client_id=str(client.id) if client else None,
                operation="avatar_onboarding",
                result=result,
                avatar_id=None,
                triggered_by="onboarding",
            )

        return {
            "error": None,
            "data": result["data"],
            "cost_usd": result["cost_usd"],
            "model": result["model"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "duration_ms": result["duration_ms"],
        }

    except Exception as e:
        logger.error("AI analysis failed for %s: %s", profile_data["username"], e)
        return {
            "error": str(e),
            "data": None,
            "cost_usd": 0,
            "model": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": 0,
        }


# --------------------------------------------------------------------------
# Combined: fetch + analyze in one call
# --------------------------------------------------------------------------


def run_avatar_onboard_analysis(
    reddit_username: str,
    client: Client | None = None,
    db: Session | None = None,
) -> dict:
    """Full avatar onboarding analysis: PRAW fetch + AI classification.

    Args:
        reddit_username: Reddit username
        client: Optional client for context
        db: Database session for logging

    Returns:
        Dict with:
        - profile: raw Reddit data
        - analysis: AI classification results
        - error: None or error message
    """
    # Step 1: Fetch from Reddit
    profile = fetch_reddit_profile(reddit_username)

    if profile.get("error"):
        return {
            "profile": profile,
            "analysis": None,
            "error": f"Reddit fetch failed: {profile['error']}",
        }

    # Step 2: AI analysis
    analysis = analyze_avatar_with_ai(profile, client=client, db=db)

    if analysis.get("error"):
        return {
            "profile": profile,
            "analysis": analysis,
            "error": f"AI analysis failed: {analysis['error']}",
        }

    return {
        "profile": profile,
        "analysis": analysis,
        "error": None,
    }
