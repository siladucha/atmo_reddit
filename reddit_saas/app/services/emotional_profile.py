"""Subreddit Emotional Profile — analyzer, compatibility scorer, and pipeline helper.

Implements:
- Profile analysis: fetch top comments from subreddit, LLM-analyze tone patterns
- Compatibility scoring: compare avatar voice against subreddit profile
- Pipeline helper: inject tone context into generation prompt

Models: Gemini Flash for analysis (cheap), Gemini Flash for compatibility (cheap).
Schedule: Weekly refresh (Sunday 04:30), on-demand via admin UI.
"""

import time
import uuid
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.avatar_subreddit_compatibility import AvatarSubredditCompatibility
from app.models.subreddit import Subreddit
from app.schemas.emotional_profile import CompatibilityResult, EmotionalProfileSchema
from app.services.ai import call_llm_json, log_ai_usage
from app.services.reddit import get_reddit_client

logger = get_logger(__name__)

# Model: cheap for tone analysis
PROFILE_MODEL = "gemini/gemini-2.5-flash"
COMPATIBILITY_MODEL = "gemini/gemini-2.5-flash-lite"

# --- Prompts ---

PROFILE_SYSTEM_PROMPT = """You are a Reddit community behavior analyst.

Analyze the provided top-performing comments from a subreddit to determine what communication tones and styles are rewarded (upvoted) and punished (downvoted/removed) by the community.

OUTPUT FORMAT (strict JSON):
{
  "rewarded_tones": [
    {"name": "tone name (1-3 words)", "description": "How this tone manifests in comments (max 300 chars)"}
  ],
  "punished_tones": [
    {"name": "tone name (1-3 words)", "description": "What triggers negative reactions (max 300 chars)"}
  ],
  "community_temperament": "2-3 sentence characterization of the community's behavioral norms, what is valued, what triggers hostility",
  "formality_level": "casual|moderate|formal",
  "humor_tolerance": "none|low|moderate|high",
  "vulnerability_tolerance": "none|low|moderate|high"
}

RULES:
- Return ONLY valid JSON. No markdown, no code blocks.
- "rewarded_tones": 1-5 items. Tones that consistently earn upvotes.
- "punished_tones": 0-5 items. Tones that get downvoted or hostile replies.
- Focus on ACTIONABLE insights: what should a new participant do/avoid?
- Base analysis ONLY on the provided comments, not assumptions about the subreddit name.
- Be specific. "helpful" is too vague. "Step-by-step technical guidance with code examples" is better."""

PROFILE_USER_PROMPT = """Subreddit: r/{subreddit_name}

Top-performing comments (sorted by upvotes, minimum score 2):

{comments_text}

Analyze these comments to determine what tones work and what tones fail in this community. Return JSON only."""

COMPATIBILITY_SYSTEM_PROMPT = """You are an expert at evaluating voice-community fit.

Given an avatar's voice profile and a subreddit's emotional profile, score how well the avatar's communication style fits the community.

OUTPUT FORMAT (strict JSON):
{
  "score": 0-100,
  "mismatch_reasons": ["reason 1", "reason 2"]
}

SCORING GUIDE:
- 80-100: Excellent fit. Avatar's style matches community norms closely.
- 60-79: Good fit with minor adjustments needed.
- 40-59: Mediocre fit. Some tone conflicts but manageable.
- 20-39: Poor fit. Significant tone mismatches likely to cause negative karma.
- 0-19: Terrible fit. Avatar should not engage in this community.

"mismatch_reasons": 0-5 short strings explaining WHY the score is what it is.
Only include reasons for scores below 80.

Return JSON only."""

COMPATIBILITY_USER_PROMPT = """## Avatar Voice Profile
{voice_profile}

## Avatar Tone Principles
{tone_principles}

## Subreddit: r/{subreddit_name}
Community temperament: {community_temperament}

Rewarded tones:
{rewarded_text}

Punished tones:
{punished_text}

Formality: {formality_level}
Humor tolerance: {humor_tolerance}

Score this avatar's fit with this subreddit. Return JSON only."""


# =============================================================================
# Profile Analyzer
# =============================================================================


def analyze_subreddit_profile(db: Session, subreddit_name: str) -> dict:
    """Analyze a subreddit's emotional profile from its top comments.

    Fetches hot threads via PRAW, collects top comments (score >= 2),
    sends to Gemini Flash for structured tone analysis.

    Args:
        db: Database session.
        subreddit_name: Bare subreddit name (no r/ prefix).

    Returns:
        Dict with "profile" (EmotionalProfileSchema dict) and "confidence" str.
        On failure returns {"error": str}.
    """
    subreddit_name = subreddit_name.strip().lower()

    # Fetch subreddit record
    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name)
        .first()
    )
    if not subreddit:
        return {"error": f"Subreddit '{subreddit_name}' not found in registry"}

    # Collect comments via PRAW
    try:
        comments_text, comment_count, thread_count = _fetch_top_comments(subreddit_name)
    except Exception as e:
        error_msg = f"Reddit API error: {str(e)[:200]}"
        subreddit.emotional_profile_error = error_msg
        db.commit()
        logger.error("EP_ANALYZE | sub=r/%s | error=%s", subreddit_name, error_msg)
        return {"error": error_msg}

    if comment_count < 10:
        # Not enough data for reliable analysis
        subreddit.emotional_profile_error = f"Insufficient data: only {comment_count} qualifying comments"
        db.commit()
        logger.warning("EP_ANALYZE | sub=r/%s | insufficient_comments=%d", subreddit_name, comment_count)
        return {"error": f"Only {comment_count} comments with score >= 2 (need 10+)"}

    # Determine confidence level
    if comment_count >= 25 and thread_count >= 5:
        confidence = "high"
    elif comment_count >= 15 or thread_count >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    # LLM analysis
    messages = [
        {"role": "system", "content": PROFILE_SYSTEM_PROMPT},
        {"role": "user", "content": PROFILE_USER_PROMPT.format(
            subreddit_name=subreddit_name,
            comments_text=comments_text,
        )},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=PROFILE_MODEL,
            temperature=0.3,
            max_tokens=1024,
        )
    except Exception as e:
        error_msg = f"LLM error: {str(e)[:200]}"
        subreddit.emotional_profile_error = error_msg
        db.commit()
        logger.error("EP_ANALYZE | sub=r/%s | llm_error=%s", subreddit_name, error_msg)
        return {"error": error_msg}

    data = result["data"]

    # Inject confidence (not from LLM — calculated from data volume)
    data["confidence"] = confidence

    # Validate with Pydantic schema
    try:
        validated = EmotionalProfileSchema.model_validate(data)
        profile_dict = validated.model_dump()
    except ValidationError as e:
        # Retry once with corrective prompt
        retry_result = _retry_with_correction(messages, str(e), confidence)
        if retry_result is None:
            error_msg = f"Schema validation failed: {str(e)[:200]}"
            subreddit.emotional_profile_error = error_msg
            db.commit()
            return {"error": error_msg}
        profile_dict = retry_result

    # Store: copy current to previous, save new profile
    subreddit.previous_emotional_profile = subreddit.emotional_profile
    subreddit.emotional_profile = profile_dict
    subreddit.emotional_profile_analyzed_at = datetime.now(timezone.utc)
    subreddit.emotional_profile_error = None

    # Log AI usage
    try:
        log_ai_usage(
            db=db,
            client_id=None,
            operation="emotional_profile",
            result=result,
            triggered_by=f"profile_analysis:{subreddit_name}",
        )
    except Exception:
        pass

    db.commit()

    # Log ActivityEvent for audit trail
    try:
        from app.models.activity_event import ActivityEvent
        event = ActivityEvent(
            event_type="emotional_profile_analyzed",
            message=(
                f"Emotional profile analyzed for r/{subreddit_name}: "
                f"confidence={confidence}, "
                f"rewarded={len(profile_dict.get('rewarded_tones', []))}, "
                f"punished={len(profile_dict.get('punished_tones', []))}"
            ),
            event_metadata={
                "subreddit_name": subreddit_name,
                "confidence": confidence,
                "formality_level": profile_dict.get("formality_level"),
                "humor_tolerance": profile_dict.get("humor_tolerance"),
                "rewarded_count": len(profile_dict.get("rewarded_tones", [])),
                "punished_count": len(profile_dict.get("punished_tones", [])),
                "model": result.get("model", PROFILE_MODEL),
                "cost_usd": float(result.get("cost_usd", 0)),
            },
        )
        db.add(event)
        db.commit()
    except Exception:
        pass

    logger.info(
        "EP_ANALYZE | sub=r/%s | confidence=%s | rewarded=%d | punished=%d | formality=%s",
        subreddit_name,
        confidence,
        len(profile_dict["rewarded_tones"]),
        len(profile_dict["punished_tones"]),
        profile_dict["formality_level"],
    )

    return {"profile": profile_dict, "confidence": confidence}


def _fetch_top_comments(subreddit_name: str) -> tuple[str, int, int]:
    """Fetch top comments from a subreddit's hot threads.

    Returns: (formatted_text, comment_count, thread_count)
    """
    reddit = get_reddit_client(caller="emotional_profile")
    sub = reddit.subreddit(subreddit_name)

    comments_data = []
    thread_count = 0

    for submission in sub.hot(limit=10):
        if submission.stickied:
            continue
        thread_count += 1
        submission.comment_sort = "best"
        submission.comments.replace_more(limit=0)

        for comment in submission.comments[:10]:
            if hasattr(comment, "score") and comment.score >= 2 and hasattr(comment, "body"):
                body = comment.body.strip()
                if len(body) > 20:  # Skip very short comments
                    comments_data.append({
                        "score": comment.score,
                        "body": body[:500],  # Cap individual comment length
                        "thread_title": submission.title[:100],
                    })

        # Rate limit: 2s between thread fetches
        time.sleep(2)

        if len(comments_data) >= 30:
            break

    # Sort by score descending, take top 30
    comments_data.sort(key=lambda c: c["score"], reverse=True)
    comments_data = comments_data[:30]

    # Format for prompt
    lines = []
    for i, c in enumerate(comments_data, 1):
        lines.append(f"[{i}] Score: {c['score']} | Thread: \"{c['thread_title']}\"")
        lines.append(f"    {c['body']}")
        lines.append("")

    return "\n".join(lines), len(comments_data), thread_count


def _retry_with_correction(
    original_messages: list[dict], error_text: str, confidence: str
) -> dict | None:
    """Retry LLM call with corrective prompt including the validation error."""
    corrective = (
        f"Your previous response failed validation: {error_text[:300]}\n\n"
        "Please fix the response and return valid JSON matching the schema exactly."
    )
    messages = original_messages + [{"role": "user", "content": corrective}]

    try:
        result = call_llm_json(
            messages=messages,
            model=PROFILE_MODEL,
            temperature=0.2,
            max_tokens=1024,
        )
        data = result["data"]
        data["confidence"] = confidence
        validated = EmotionalProfileSchema.model_validate(data)
        return validated.model_dump()
    except Exception:
        return None


# =============================================================================
# Compatibility Scoring
# =============================================================================


def compute_compatibility(
    db: Session, avatar: Avatar, subreddit_name: str
) -> AvatarSubredditCompatibility | None:
    """Compute avatar-subreddit compatibility score.

    Requires: subreddit has emotional_profile AND avatar has voice_profile_md.
    Uses Gemini Flash Lite (cheapest available).

    Args:
        db: Database session.
        avatar: Avatar with voice_profile_md.
        subreddit_name: Bare subreddit name.

    Returns:
        AvatarSubredditCompatibility record (created or updated), or None on failure.
    """
    subreddit_name_lower = subreddit_name.strip().lower()

    # Get subreddit profile
    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name_lower)
        .first()
    )
    if not subreddit or not subreddit.emotional_profile:
        return None

    profile = subreddit.emotional_profile
    if not avatar.voice_profile_md:
        return None

    # Build prompt
    rewarded_text = "\n".join(
        f"- {t['name']}: {t['description']}" for t in profile.get("rewarded_tones", [])
    )
    punished_text = "\n".join(
        f"- {t['name']}: {t['description']}" for t in profile.get("punished_tones", [])
    ) or "- None identified"

    messages = [
        {"role": "system", "content": COMPATIBILITY_SYSTEM_PROMPT},
        {"role": "user", "content": COMPATIBILITY_USER_PROMPT.format(
            voice_profile=avatar.voice_profile_md[:2000],
            tone_principles=avatar.tone_principles or "(not defined)",
            subreddit_name=subreddit_name_lower,
            community_temperament=profile.get("community_temperament", "Unknown"),
            rewarded_text=rewarded_text,
            punished_text=punished_text,
            formality_level=profile.get("formality_level", "moderate"),
            humor_tolerance=profile.get("humor_tolerance", "moderate"),
        )},
    ]

    try:
        result = call_llm_json(
            messages=messages,
            model=COMPATIBILITY_MODEL,
            temperature=0.2,
            max_tokens=256,
            schema=CompatibilityResult,
        )
    except Exception as e:
        logger.warning(
            "EP_COMPAT | avatar=%s | sub=r/%s | error=%s",
            avatar.reddit_username, subreddit_name_lower, str(e)[:100],
        )
        # On failure: if existing record, mark stale
        existing = _get_existing_compat(db, avatar.id, subreddit_name_lower)
        if existing:
            existing.is_stale = True
            db.commit()
        return existing

    data = result["data"]
    score = max(0, min(100, data.get("score", 50)))
    mismatch_reasons = data.get("mismatch_reasons", [])[:5]

    # Upsert compatibility record
    record = _get_existing_compat(db, avatar.id, subreddit_name_lower)
    if record:
        record.score = score
        record.mismatch_reasons = mismatch_reasons
        record.is_stale = False
        record.computed_at = datetime.now(timezone.utc)
    else:
        record = AvatarSubredditCompatibility(
            avatar_id=avatar.id,
            subreddit_name=subreddit_name_lower,
            score=score,
            mismatch_reasons=mismatch_reasons,
            is_stale=False,
        )
        db.add(record)

    db.commit()

    logger.info(
        "EP_COMPAT | avatar=%s | sub=r/%s | score=%d | mismatches=%d",
        avatar.reddit_username, subreddit_name_lower, score, len(mismatch_reasons),
    )

    return record


def compute_all_compatibility_for_avatar(db: Session, avatar: Avatar) -> list[AvatarSubredditCompatibility]:
    """Compute compatibility for all subreddits assigned to an avatar's clients."""
    from app.models.subreddit import ClientSubredditAssignment

    if not avatar.voice_profile_md or not avatar.client_ids:
        return []

    # Get all active subreddit assignments for avatar's clients
    sub_names = set()
    for client_id_str in avatar.client_ids:
        try:
            client_uuid = uuid.UUID(client_id_str)
        except (ValueError, TypeError):
            continue
        assignments = (
            db.query(ClientSubredditAssignment)
            .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
            .filter(
                ClientSubredditAssignment.client_id == client_uuid,
                ClientSubredditAssignment.is_active == True,
                Subreddit.emotional_profile.isnot(None),
            )
            .all()
        )
        for a in assignments:
            sub_names.add(a.subreddit.subreddit_name.lower())

    # Also add hobby/business subreddits from avatar config
    for sub_list in [avatar.hobby_subreddits, avatar.business_subreddits]:
        if isinstance(sub_list, dict):
            for name in sub_list.get("subreddits", sub_list.get("names", [])):
                if isinstance(name, str):
                    sub_names.add(name.lower())
        elif isinstance(sub_list, list):
            for name in sub_list:
                if isinstance(name, str):
                    sub_names.add(name.lower())

    results = []
    for sub_name in sub_names:
        record = compute_compatibility(db, avatar, sub_name)
        if record:
            results.append(record)

    return results


def _get_existing_compat(
    db: Session, avatar_id: uuid.UUID, subreddit_name: str
) -> AvatarSubredditCompatibility | None:
    """Get existing compatibility record."""
    return (
        db.query(AvatarSubredditCompatibility)
        .filter(
            AvatarSubredditCompatibility.avatar_id == avatar_id,
            AvatarSubredditCompatibility.subreddit_name == subreddit_name,
        )
        .first()
    )


# =============================================================================
# Pipeline Helper — Tone Context for Generation
# =============================================================================


def get_subreddit_tone_context(db: Session, subreddit_name: str) -> str | None:
    """Get tone context string for injection into generation prompt.

    Returns a formatted string suitable for appending to the system prompt,
    or None if no profile exists.

    Non-blocking: returns None rather than raising exceptions.
    """
    subreddit_name_lower = subreddit_name.strip().lower()

    subreddit = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name_lower)
        .first()
    )
    if not subreddit or not subreddit.emotional_profile:
        return None

    profile = subreddit.emotional_profile

    # Build injection text
    parts = [f"## SUBREDDIT TONE CONTEXT — r/{subreddit_name}"]
    parts.append(f"Community: {profile.get('community_temperament', 'Unknown')}")
    parts.append(f"Formality: {profile.get('formality_level', 'moderate')} | Humor: {profile.get('humor_tolerance', 'moderate')}")

    rewarded = profile.get("rewarded_tones", [])
    if rewarded:
        parts.append("\nWORKS WELL (rewarded by community):")
        for t in rewarded:
            parts.append(f"  - {t['name']}: {t['description']}")

    punished = profile.get("punished_tones", [])
    if punished:
        parts.append("\nAVOID (punished by community):")
        for t in punished:
            parts.append(f"  - {t['name']}: {t['description']}")

    return "\n".join(parts)


def get_avatar_compatibility_context(
    db: Session, avatar_id: uuid.UUID, subreddit_name: str
) -> dict | None:
    """Get compatibility data for pipeline decisions.

    Returns:
        {"score": int, "mismatch_reasons": [...], "tone_warning": [...] | None}
        or None if no record exists.
    """
    record = _get_existing_compat(db, avatar_id, subreddit_name.strip().lower())
    if not record:
        return None

    tone_warning = None
    if record.score < 40:
        tone_warning = record.mismatch_reasons

    return {
        "score": record.score,
        "mismatch_reasons": record.mismatch_reasons,
        "tone_warning": tone_warning,
    }
