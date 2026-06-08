"""Avatar Analysis Service — LLM-based behavioral profiling with retry/fallback.

Orchestrates avatar analysis: builds prompts, calls LLM with retry logic,
validates output against BehavioralProfile schema, logs usage, and handles
fallback to alternative model on total primary failure.
"""

import json
from app.logging_config import get_logger
import time
import uuid
from decimal import Decimal

import litellm
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.models.ai_usage import AIUsageLog
from app.schemas.avatar_analysis import (
    AvatarAnalysisRequest,
    BehavioralProfile,
)
from app.services.ai import call_llm_json, ai_trigger_context
from app.services.learning_loop import get_recent_edits
from app.services.settings import get_setting

logger = get_logger(__name__)


class AnalysisError(Exception):
    """Raised when all analysis attempts (retries + fallback) fail."""

    def __init__(self, attempts: int, last_failure_reason: str):
        self.attempts = attempts
        self.last_failure_reason = last_failure_reason
        super().__init__(
            f"All analysis attempts failed (attempts={attempts}): {last_failure_reason}"
        )


# Transient error types that warrant retry
_TRANSIENT_ERRORS = (
    litellm.exceptions.Timeout,
    litellm.exceptions.RateLimitError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.APIConnectionError,
    ValidationError,
    ValueError,  # JSON parse errors from call_llm_json
)


def _build_system_prompt() -> str:
    """Build the system prompt for avatar behavioral analysis."""
    return (
        "You are a behavioral analyst for Reddit accounts. "
        "Analyze the provided avatar data and return a structured JSON behavioral profile.\n\n"
        "Your output MUST be a JSON object with the following structure:\n"
        "{\n"
        '  "basic": {"username": str, "account_age_days": int, "total_karma": int, "is_mod": bool},\n'
        '  "behavior": {"total_comments": int, "days_since_last_activity": int, "uses_emoji": bool, "avg_comment_length": int},\n'
        '  "topics": {"top_subreddits": [str], "key_themes": [str]},\n'
        '  "speech": {"frequent_terms": [str], "pattern_description": str},\n'
        '  "mismatches": [str],\n'
        '  "summary": str (30-50 words behavioral synopsis)\n'
        "}\n\n"
        "For 'mismatches': compare the voice_profile_md (intended persona) against "
        "actual behavior patterns found in comments/posts. List any discrepancies.\n\n"
        "For 'summary': write a concise 30-50 word behavioral synopsis."
    )


def _build_user_prompt(request: AvatarAnalysisRequest) -> str:
    """Build the user prompt from the analysis request data."""
    analytics = request.profile_analytics

    parts = [
        f"Username: {request.reddit_username}",
        f"Active: {request.active}",
        f"Account age: {analytics.account_age_days} days",
        f"Total karma: {analytics.total_karma}",
        f"Subreddits: {', '.join(analytics.subreddits) if analytics.subreddits else 'none'}",
    ]

    if request.voice_profile_md:
        parts.append(f"\n--- Voice Profile (intended persona) ---\n{request.voice_profile_md}")

    if analytics.recent_comments:
        comments_text = "\n".join(
            f"- {c.get('body', c.get('text', str(c)))[:200]}"
            for c in analytics.recent_comments[:20]
        )
        parts.append(f"\n--- Recent Comments ({len(analytics.recent_comments)} total) ---\n{comments_text}")

    if analytics.recent_posts:
        posts_text = "\n".join(
            f"- {p.get('title', p.get('text', str(p)))[:200]}"
            for p in analytics.recent_posts[:20]
        )
        parts.append(f"\n--- Recent Posts ({len(analytics.recent_posts)} total) ---\n{posts_text}")

    return "\n".join(parts)


def _build_few_shot_section(edit_records: list) -> str:
    """Build the few-shot examples section from edit records.

    Returns an empty string if no records are provided.
    """
    if not edit_records:
        return ""

    parts = [
        "\n\n--- Corrections from previous analyses ---",
        "Here are corrections made to previous analyses of this avatar.",
        "Learn from these to avoid repeating the same mistakes:\n",
    ]

    for i, record in enumerate(edit_records, start=1):
        parts.append(f"Example {i}:")
        parts.append(f"Original: {json.dumps(record.llm_output, ensure_ascii=False)}")
        parts.append(f"Corrected: {json.dumps(record.human_edited, ensure_ascii=False)}")
        parts.append(f"What changed: {record.diff_summary}")
        parts.append("")  # blank line between examples

    return "\n".join(parts)


def _log_attempt(
    db: Session,
    avatar_id: uuid.UUID,
    model: str,
    duration_ms: int,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Log a single LLM attempt to AIUsageLog."""
    log = AIUsageLog(
        avatar_id=avatar_id,
        operation="avatar_analysis",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=Decimal(str(cost_usd)),
        duration_ms=duration_ms,
        triggered_by=ai_trigger_context.get() or "api",
    )
    db.add(log)
    db.flush()


def analyze_avatar(
    db: Session,
    avatar_id: uuid.UUID,
    request: AvatarAnalysisRequest,
) -> BehavioralProfile:
    """Run LLM-based behavioral analysis with retry and fallback logic.

    Strategy:
    1. Attempt with primary model
    2. On transient failure → retry up to max_retries times with exponential backoff
    3. If all retries exhausted → attempt once with fallback model
    4. If fallback fails → raise AnalysisError

    Each attempt is logged to AIUsageLog with operation="avatar_analysis".

    Args:
        db: Database session
        avatar_id: UUID of the avatar being analyzed
        request: The analysis request payload

    Returns:
        BehavioralProfile on success

    Raises:
        AnalysisError: When all attempts (primary + retries + fallback) fail
    """
    # Read config from SystemSettings
    primary_model = get_setting(db, "avatar_analysis_primary_model") or "openai/gpt-4o-mini"
    fallback_model = get_setting(db, "avatar_analysis_fallback_model") or "anthropic/claude-sonnet-4-20250514"
    max_retries_str = get_setting(db, "avatar_analysis_max_retries") or "2"
    max_retries = int(max_retries_str)
    few_shot_limit_str = get_setting(db, "avatar_analysis_few_shot_limit") or "3"
    few_shot_limit = int(few_shot_limit_str)

    base_delay = 2  # seconds

    # Retrieve recent edits for few-shot injection
    edit_records = get_recent_edits(db, avatar_id, limit=few_shot_limit)

    # Build prompts
    system_prompt = _build_system_prompt()
    user_prompt = _build_user_prompt(request)

    # Inject few-shot examples if edit records exist
    if edit_records:
        few_shot_section = _build_few_shot_section(edit_records)
        user_prompt = user_prompt + few_shot_section
        logger.info(
            "AVATAR_ANALYSIS | action=few_shot_injected | avatar_id=%s | count=%d",
            avatar_id,
            len(edit_records),
        )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    total_attempts = 0
    last_error: str = ""

    # --- Primary model attempts (1 initial + max_retries retries) ---
    for attempt in range(1 + max_retries):
        total_attempts += 1
        start_time = time.time()

        try:
            result = call_llm_json(
                messages=messages,
                model=primary_model,
                schema=BehavioralProfile,
                temperature=0.3,
                max_tokens=2048,
            )

            duration_ms = int((time.time() - start_time) * 1000)

            # Log successful attempt
            _log_attempt(
                db,
                avatar_id,
                result["model"],
                duration_ms,
                input_tokens=result["input_tokens"],
                output_tokens=result["output_tokens"],
                cost_usd=result["cost_usd"],
            )
            db.commit()

            logger.info(
                "AVATAR_ANALYSIS | action=success | avatar_id=%s | model=%s | "
                "input_tokens=%d | output_tokens=%d | cost_usd=%.6f | duration_ms=%d",
                avatar_id, result["model"], result["input_tokens"],
                result["output_tokens"], result["cost_usd"], duration_ms,
            )

            return BehavioralProfile.model_validate(result["data"])

        except _TRANSIENT_ERRORS as e:
            duration_ms = int((time.time() - start_time) * 1000)
            last_error = f"{type(e).__name__}: {str(e)[:200]}"

            # Log failed attempt
            _log_attempt(
                db,
                avatar_id,
                primary_model,
                duration_ms,
            )
            db.flush()

            logger.warning(
                "AVATAR_ANALYSIS | action=retry | avatar_id=%s | attempt=%d/%d | "
                "error=%s | duration_ms=%d | model=%s",
                avatar_id, attempt + 1, 1 + max_retries,
                type(e).__name__, duration_ms, primary_model,
            )

            # Exponential backoff before next retry (skip sleep on last attempt)
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                time.sleep(delay)

    # --- Fallback attempt (exactly one) ---
    total_attempts += 1
    start_time = time.time()

    try:
        result = call_llm_json(
            messages=messages,
            model=fallback_model,
            schema=BehavioralProfile,
            temperature=0.3,
            max_tokens=2048,
        )

        duration_ms = int((time.time() - start_time) * 1000)

        # Log successful fallback attempt
        _log_attempt(
            db,
            avatar_id,
            result["model"],
            duration_ms,
            input_tokens=result["input_tokens"],
            output_tokens=result["output_tokens"],
            cost_usd=result["cost_usd"],
        )
        db.commit()

        logger.info(
            "AVATAR_ANALYSIS | action=fallback_success | avatar_id=%s | model=%s | "
            "input_tokens=%d | output_tokens=%d | cost_usd=%.6f | duration_ms=%d",
            avatar_id, result["model"], result["input_tokens"],
            result["output_tokens"], result["cost_usd"], duration_ms,
        )

        return BehavioralProfile.model_validate(result["data"])

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        last_error = f"{type(e).__name__}: {str(e)[:200]}"

        # Log failed fallback attempt
        _log_attempt(
            db,
            avatar_id,
            fallback_model,
            duration_ms,
        )
        db.commit()

        logger.error(
            "AVATAR_ANALYSIS | action=total_failure | avatar_id=%s | "
            "attempts=%d | last_error=%s | model=%s | duration_ms=%d",
            avatar_id, total_attempts, type(e).__name__,
            fallback_model, duration_ms,
        )

        raise AnalysisError(
            attempts=total_attempts,
            last_failure_reason=last_error,
        )
