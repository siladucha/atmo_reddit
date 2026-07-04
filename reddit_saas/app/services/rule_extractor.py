"""Rule Extractor service — PRAW + Gemini Flash structured rule extraction.

Fetches subreddit sidebar/wiki content via PRAW, sends to Gemini Flash
for structured extraction, validates with Pydantic, stores results on
SubredditRiskProfile.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

import json
import time
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, field_validator
from prawcore.exceptions import Forbidden, NotFound, Redirect
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.services.reddit import get_reddit_client
from app.services.ai import call_llm, log_ai_usage
from app.services.transparency import record_activity_event

logger = get_logger(__name__)

# Constants
RULE_EXTRACTION_DELAY_SECONDS = 3
CIRCUIT_BREAKER_THRESHOLD = 0.5
MAX_SIDEBAR_CHARS = 4000
MAX_RULES_PER_SUBREDDIT = 20
LLM_RETRY_DELAY_SECONDS = 5
LLM_MODEL = "gemini/gemini-2.0-flash"
LLM_TEMPERATURE = 0.1

# Valid rule categories
RULE_CATEGORIES = (
    "min_karma",
    "min_account_age",
    "no_self_promo",
    "required_flair",
    "posting_frequency_limit",
    "content_restriction",
    "other",
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ExtractedRule(BaseModel):
    """A single extracted subreddit rule."""

    category: Literal[
        "min_karma",
        "min_account_age",
        "no_self_promo",
        "required_flair",
        "posting_frequency_limit",
        "content_restriction",
        "other",
    ]
    description: str
    threshold_value: str | None = None

    @field_validator("description")
    @classmethod
    def truncate_description(cls, v: str) -> str:
        """Ensure description does not exceed 200 characters."""
        if len(v) > 200:
            return v[:200]
        return v


class ExtractionResult(BaseModel):
    """Result of rule extraction for a subreddit."""

    rules: list[ExtractedRule]

    @field_validator("rules")
    @classmethod
    def limit_rules(cls, v: list[ExtractedRule]) -> list[ExtractedRule]:
        """Cap rules at MAX_RULES_PER_SUBREDDIT."""
        if len(v) > MAX_RULES_PER_SUBREDDIT:
            return v[:MAX_RULES_PER_SUBREDDIT]
        return v


# ---------------------------------------------------------------------------
# LLM Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a Reddit moderation rule parser. "
    "Extract formal rules from subreddit sidebar/wiki text."
)

_USER_PROMPT_TEMPLATE = """Extract all posting rules from this subreddit sidebar. Return a JSON array of rules.

Each rule must have:
- category: one of min_karma, min_account_age, no_self_promo, required_flair, posting_frequency_limit, content_restriction, other
- description: concise rule description (max 200 chars)
- threshold_value: numeric or duration value if applicable (e.g. "500", "30 days"), null if not applicable

Return max 20 rules. If no rules found, return empty array.

Sidebar text:
---
{sidebar_text}
---

Return ONLY valid JSON array, no markdown."""


# ---------------------------------------------------------------------------
# Internal sentinel for distinguishing failure reasons
# ---------------------------------------------------------------------------


class _ExtractionFailure:
    """Sentinel to distinguish 'no content' from 'LLM extraction failed'."""

    def __init__(self, reason: str):
        self.reason = reason


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------


def _fetch_sidebar_content(subreddit_name: str) -> str | None:
    """Fetch sidebar description + wiki rules page via PRAW.

    Returns concatenated text (truncated to MAX_SIDEBAR_CHARS) or None if
    no content is accessible.
    """
    try:
        reddit = get_reddit_client("rule_extractor")
        subreddit = reddit.subreddit(subreddit_name)

        parts: list[str] = []

        # Fetch sidebar description
        try:
            description = subreddit.description
            if description and description.strip():
                parts.append(description.strip())
        except Exception as e:
            logger.debug(
                "RULE_EXTRACTOR | subreddit=r/%s | sidebar_description fetch failed: %s",
                subreddit_name, str(e)[:100],
            )

        # Fetch wiki rules page
        try:
            wiki_page = subreddit.wiki["rules"]
            wiki_content = wiki_page.content_md
            if wiki_content and wiki_content.strip():
                parts.append(wiki_content.strip())
        except (NotFound, Forbidden, Redirect):
            logger.debug(
                "RULE_EXTRACTOR | subreddit=r/%s | wiki/rules page not accessible",
                subreddit_name,
            )
        except Exception as e:
            logger.debug(
                "RULE_EXTRACTOR | subreddit=r/%s | wiki fetch error: %s",
                subreddit_name, str(e)[:100],
            )

        if not parts:
            return None

        # Concatenate and truncate to MAX_SIDEBAR_CHARS
        combined = "\n\n".join(parts)
        if len(combined) > MAX_SIDEBAR_CHARS:
            combined = combined[:MAX_SIDEBAR_CHARS]

        return combined

    except (NotFound, Forbidden, Redirect) as e:
        logger.warning(
            "RULE_EXTRACTOR | subreddit=r/%s | inaccessible (%s): %s",
            subreddit_name, type(e).__name__, str(e)[:100],
        )
        return None
    except Exception as e:
        logger.error(
            "RULE_EXTRACTOR | subreddit=r/%s | PRAW error: %s",
            subreddit_name, str(e)[:200],
        )
        return None


def _parse_llm_response(content: str) -> ExtractionResult:
    """Parse LLM response into ExtractionResult. Raises ValueError on failure."""
    if not content or not content.strip():
        raise ValueError("Empty LLM response")

    text = content.strip()

    # Try to extract JSON array from response
    # Handle markdown code blocks
    if "```json" in text:
        block = text.split("```json", 1)[1]
        if "```" in block:
            block = block.split("```", 1)[0]
        text = block.strip()
    elif "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            text = parts[1].strip()

    # Try parsing as JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find array in the text
        bracket_start = text.find("[")
        if bracket_start != -1:
            bracket_end = text.rfind("]")
            if bracket_end > bracket_start:
                candidate = text[bracket_start:bracket_end + 1]
                try:
                    data = json.loads(candidate)
                except json.JSONDecodeError:
                    raise ValueError(f"Cannot parse JSON from LLM response: {text[:200]}")
            else:
                raise ValueError(f"Cannot find valid JSON array: {text[:200]}")
        else:
            raise ValueError(f"No JSON array in LLM response: {text[:200]}")

    # If data is a list, wrap in the expected format
    if isinstance(data, list):
        return ExtractionResult(rules=data)
    elif isinstance(data, dict) and "rules" in data:
        return ExtractionResult(rules=data["rules"])
    else:
        raise ValueError(f"Unexpected JSON structure: {type(data)}")


def extract_subreddit_rules(
    subreddit_name: str,
    db: Session | None = None,
) -> "ExtractionResult | _ExtractionFailure | None":
    """Fetch sidebar/wiki via PRAW, send to Gemini Flash for structured extraction.

    Returns:
        ExtractionResult on success.
        None if no sidebar/wiki content is accessible (no_content).
        _ExtractionFailure if LLM extraction failed after retry.

    Retries once on validation failure (Req 1.6).
    """
    logger.info(
        "RULE_EXTRACTOR | action=extract | subreddit=r/%s | status=start",
        subreddit_name,
    )

    # Step 1: Fetch sidebar content
    sidebar_text = _fetch_sidebar_content(subreddit_name)
    if sidebar_text is None:
        logger.info(
            "RULE_EXTRACTOR | action=extract | subreddit=r/%s | status=no_content",
            subreddit_name,
        )
        return None

    # Step 2: Call LLM
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(sidebar_text=sidebar_text)},
    ]

    # First attempt
    try:
        result = call_llm(
            messages=messages,
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            max_tokens=2048,
        )

        # Log AI cost if DB session available
        if db:
            try:
                log_ai_usage(
                    db=db,
                    client_id=None,
                    operation="subreddit_rule_extraction",
                    result=result,
                    subreddit_name=subreddit_name,
                    triggered_by="scheduler",
                )
            except Exception:
                pass  # Don't fail extraction on logging error

        extraction = _parse_llm_response(result["content"])
        logger.info(
            "RULE_EXTRACTOR | action=extract | subreddit=r/%s | status=success | rules_count=%d",
            subreddit_name, len(extraction.rules),
        )
        return extraction

    except (ValueError, Exception) as first_error:
        logger.warning(
            "RULE_EXTRACTOR | action=extract | subreddit=r/%s | attempt=1 | error=%s",
            subreddit_name, str(first_error)[:200],
        )

        # Retry once after delay (Req 1.6)
        time.sleep(LLM_RETRY_DELAY_SECONDS)

        try:
            result = call_llm(
                messages=messages,
                model=LLM_MODEL,
                temperature=LLM_TEMPERATURE,
                max_tokens=2048,
            )

            # Log AI cost if DB session available
            if db:
                try:
                    log_ai_usage(
                        db=db,
                        client_id=None,
                        operation="subreddit_rule_extraction",
                        result=result,
                        subreddit_name=subreddit_name,
                        triggered_by="scheduler",
                    )
                except Exception:
                    pass

            extraction = _parse_llm_response(result["content"])
            logger.info(
                "RULE_EXTRACTOR | action=extract | subreddit=r/%s | "
                "status=success_retry | rules_count=%d",
                subreddit_name, len(extraction.rules),
            )
            return extraction

        except Exception as retry_error:
            logger.error(
                "RULE_EXTRACTOR | action=extract | subreddit=r/%s | "
                "status=extraction_failed | attempt=2 | error=%s",
                subreddit_name, str(retry_error)[:200],
            )
            return _ExtractionFailure(reason=str(retry_error)[:200])


# ---------------------------------------------------------------------------
# Batch extraction
# ---------------------------------------------------------------------------


def refresh_all_subreddit_rules(db: Session) -> dict:
    """Batch: iterate active subreddits, extract rules, update profiles.

    Processes subreddits sequentially with RULE_EXTRACTION_DELAY_SECONDS delay.
    Circuit breaker at CIRCUIT_BREAKER_THRESHOLD (50% failure) pauses 120s.
    Preserves previous rules until new extraction succeeds (Req 1.8).

    Returns summary dict with counts.
    """
    from app.models.subreddit import Subreddit, ClientSubredditAssignment
    from app.models.subreddit_risk_profile import SubredditRiskProfile

    logger.info("RULE_EXTRACTOR | action=refresh_all | status=start")
    start_time = time.time()

    # Query subreddits with at least one active assignment (Req 1.1)
    subreddit_ids_with_assignments = (
        db.query(ClientSubredditAssignment.subreddit_id)
        .filter(ClientSubredditAssignment.is_active.is_(True))
        .distinct()
        .subquery()
    )

    subreddits = (
        db.query(Subreddit)
        .filter(
            Subreddit.id.in_(subreddit_ids_with_assignments),
            Subreddit.is_active.is_(True),
        )
        .all()
    )

    total = len(subreddits)
    success_count = 0
    failure_count = 0
    no_content_count = 0
    processed_count = 0
    circuit_breaker_triggered = False

    logger.info(
        "RULE_EXTRACTOR | action=refresh_all | subreddits_found=%d",
        total,
    )

    for idx, subreddit in enumerate(subreddits):
        # Circuit breaker check (Req 7.5): >50% failure rate
        if processed_count > 0:
            failure_rate = failure_count / processed_count
            if failure_rate > CIRCUIT_BREAKER_THRESHOLD:
                logger.warning(
                    "RULE_EXTRACTOR | action=refresh_all | circuit_breaker=triggered | "
                    "failure_rate=%.2f | processed=%d | failures=%d | pausing=120s",
                    failure_rate, processed_count, failure_count,
                )
                circuit_breaker_triggered = True
                time.sleep(120)
                # Reset failure count after pause to allow resumption
                failure_count = 0
                processed_count = 0

        # Delay between subreddits (Req 1.1)
        if idx > 0:
            time.sleep(RULE_EXTRACTION_DELAY_SECONDS)

        subreddit_name = subreddit.subreddit_name

        try:
            # Get or create risk profile
            profile = (
                db.query(SubredditRiskProfile)
                .filter(SubredditRiskProfile.subreddit_id == subreddit.id)
                .first()
            )
            if not profile:
                profile = SubredditRiskProfile(subreddit_id=subreddit.id)
                db.add(profile)
                db.flush()

            # Extract rules
            extraction_result = extract_subreddit_rules(subreddit_name, db=db)

            if extraction_result is None:
                # No content accessible (Req 1.5)
                profile.extraction_status = "no_content"
                no_content_count += 1
                record_activity_event(
                    db=db,
                    event_type="rule_extraction",
                    message=(
                        f"Rule extraction for r/{subreddit_name}: "
                        f"no sidebar/wiki content accessible"
                    ),
                    metadata={
                        "subreddit_name": subreddit_name,
                        "extraction_status": "no_content",
                    },
                )

            elif isinstance(extraction_result, _ExtractionFailure):
                # LLM extraction failed after retry (Req 1.6)
                # Previous rules preserved — only status changes (Req 1.8)
                profile.extraction_status = "extraction_failed"
                failure_count += 1
                record_activity_event(
                    db=db,
                    event_type="rule_extraction",
                    message=(
                        f"Rule extraction for r/{subreddit_name}: "
                        f"LLM extraction failed after retry"
                    ),
                    metadata={
                        "subreddit_name": subreddit_name,
                        "extraction_status": "extraction_failed",
                        "error": extraction_result.reason,
                    },
                )

            else:
                # Success — update profile (Req 1.4, 1.8)
                # Only overwrite rules on success (preserves previous on failure)
                profile.extracted_rules = [
                    rule.model_dump() for rule in extraction_result.rules
                ]
                profile.extraction_status = "success"
                profile.last_rule_extraction_at = datetime.now(timezone.utc)
                success_count += 1

            db.commit()

        except Exception as e:
            db.rollback()
            failure_count += 1
            logger.error(
                "RULE_EXTRACTOR | action=refresh_all | subreddit=r/%s | error=%s",
                subreddit_name, str(e)[:200],
            )
            record_activity_event(
                db=db,
                event_type="rule_extraction",
                message=(
                    f"Rule extraction for r/{subreddit_name}: "
                    f"unexpected error — {str(e)[:100]}"
                ),
                metadata={
                    "subreddit_name": subreddit_name,
                    "extraction_status": "error",
                    "error": str(e)[:200],
                },
            )
            db.commit()

        processed_count += 1

    duration_seconds = int(time.time() - start_time)

    summary = {
        "total": total,
        "success": success_count,
        "no_content": no_content_count,
        "failures": failure_count,
        "duration_seconds": duration_seconds,
        "circuit_breaker_triggered": circuit_breaker_triggered,
    }

    # Emit batch completion event (Req 7.4)
    record_activity_event(
        db=db,
        event_type="risk_profile_batch",
        message=(
            f"Rule extraction batch complete: {success_count}/{total} succeeded, "
            f"{failure_count} failed, {no_content_count} no content, "
            f"duration {duration_seconds}s"
        ),
        metadata=summary,
    )
    db.commit()

    logger.info(
        "RULE_EXTRACTOR | action=refresh_all | status=complete | %s",
        " | ".join(f"{k}={v}" for k, v in summary.items()),
    )

    return summary
