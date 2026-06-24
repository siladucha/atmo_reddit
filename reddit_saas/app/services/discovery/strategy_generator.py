"""Client Strategy Generator — single LLM call to produce operational strategy from Discovery.

Takes Visibility Report content (already in DB) + client brief → Gemini Flash →
validated ClientStrategyOutput JSON. No additional research or API calls.

Performance: ~10-15s, ~$0.0006/generation, max_tokens=2048.
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.discovery_session import DiscoverySession
from app.models.visibility_report import VisibilityReport
from app.schemas.client_strategy import ClientStrategyOutput
from app.services.ai import call_llm

logger = get_logger(__name__)

STRATEGY_MODEL = "gemini/gemini-2.5-flash"
STRATEGY_MAX_TOKENS = 4096
STRATEGY_TIMEOUT = 30  # seconds per attempt
AGENT_PROMPT_PATH = Path("docs/agents/client_strategy_agent.md")


def _load_system_prompt() -> str:
    """Load agent instructions from markdown file."""
    try:
        return AGENT_PROMPT_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        # Fallback: minimal instruction if file missing
        logger.warning("Agent prompt file not found at %s, using minimal fallback", AGENT_PROMPT_PATH)
        return (
            "Generate a Client Strategy JSON with sections: positioning, "
            "subreddit_priorities, content_pillars, forbidden_zones, aeo_targets, phase_roadmap. "
            "Return ONLY valid JSON. No markdown, no code blocks."
        )


def _build_user_prompt(
    report_content: dict,
    client_brief: str,
    confirmed_hypotheses: list[dict],
) -> str:
    """Build user prompt as compact JSON with all Discovery context."""
    payload = {
        "visibility_report": report_content,
        "client_brief": client_brief[:2000],
        "confirmed_hypotheses": confirmed_hypotheses[:10],
    }
    return json.dumps(payload, ensure_ascii=False)


def _get_latest_report(session: DiscoverySession) -> VisibilityReport:
    """Get the latest Visibility Report for a session."""
    if not session.reports:
        raise ValueError(f"No reports found for session {session.id}")
    return sorted(session.reports, key=lambda r: r.report_version, reverse=True)[0]


def _call_and_validate(messages: list[dict]) -> tuple[ClientStrategyOutput | None, dict]:
    """Single LLM call attempt with JSON parse + Pydantic validation.

    Returns (validated_output, result_metadata) or (None, {}) on failure.
    """
    try:
        result = call_llm(
            messages=messages,
            model=STRATEGY_MODEL,
            temperature=0.4,
            max_tokens=STRATEGY_MAX_TOKENS,
            timeout=STRATEGY_TIMEOUT,
        )
    except Exception as e:
        logger.warning("Strategy LLM call failed: %s", e)
        return None, {}

    content = result.get("content", "")
    if not content or not content.strip():
        logger.warning("Strategy LLM returned empty response")
        return None, {}

    # Parse JSON (robust extraction)
    parsed = _extract_json(content)
    if parsed is None:
        logger.warning(
            "Strategy JSON parse failed, content length=%d, starts_with=%s, preview: %s",
            len(content), repr(content[:20]), content[:300],
        )
        return None, {}

    logger.info("Strategy JSON parsed OK, keys: %s", list(parsed.keys())[:10])

    # Validate against schema
    try:
        strategy = ClientStrategyOutput.model_validate(parsed)
        return strategy, result
    except ValidationError as e:
        logger.warning("Strategy schema validation failed: %s", str(e)[:500])
        return None, {}


def generate_client_strategy(
    session: DiscoverySession,
    db: Session,
) -> tuple[ClientStrategyOutput, dict]:
    """Generate and validate Client Strategy from Discovery session data.

    Retry-once on validation failure. 30s timeout per attempt.

    Args:
        session: Completed Discovery session with report and hypotheses.
        db: Database session (for AI usage logging).

    Returns:
        Tuple of (validated ClientStrategyOutput, LLM result metadata).

    Raises:
        ValueError: If both attempts fail.
    """
    # Load inputs
    report = _get_latest_report(session)
    report_content = report.content or {}
    client_brief = session.client_brief
    confirmed = [
        {"statement": h.statement, "confidence_score": h.confidence_score}
        for h in session.hypotheses if h.status == "confirmed"
    ]

    system_prompt = _load_system_prompt()
    user_prompt = _build_user_prompt(report_content, client_brief, confirmed)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    start = time.time()

    # Attempt 1
    strategy, result = _call_and_validate(messages)
    if strategy:
        _log_usage(db, session, result)
        logger.info(
            "Strategy generated for session %s (attempt 1, %.1fs, $%.4f)",
            session.id, time.time() - start, result.get("cost_usd", 0),
        )
        return strategy, result

    # Attempt 2 (retry)
    elapsed = time.time() - start
    if elapsed > 25:
        raise ValueError(
            f"Strategy generation failed on attempt 1 and insufficient time for retry "
            f"(elapsed={elapsed:.1f}s, budget=30s)"
        )

    logger.warning("Strategy retry for session %s (attempt 1 failed after %.1fs)", session.id, elapsed)
    strategy, result = _call_and_validate(messages)
    if strategy:
        _log_usage(db, session, result)
        logger.info(
            "Strategy generated for session %s (attempt 2, %.1fs, $%.4f)",
            session.id, time.time() - start, result.get("cost_usd", 0),
        )
        return strategy, result

    raise ValueError(
        f"Strategy generation failed validation after 2 attempts for session {session.id}"
    )


def _log_usage(db: Session, session: DiscoverySession, result: dict) -> None:
    """Log AI usage for strategy generation."""
    try:
        from app.services.ai import log_ai_usage
        log_ai_usage(
            db=db,
            client_id=str(session.client_id) if session.client_id else None,
            operation="strategy_generation",
            result=result,
            triggered_by=f"discovery_handoff:{session.id}",
        )
    except Exception as e:
        logger.warning("Failed to log strategy generation AI usage: %s", e)


def _extract_json(content: str) -> dict | None:
    """Extract JSON from LLM response (handles code blocks, prose wrapping, truncation)."""
    if not content or not content.strip():
        return None

    text = content.strip()

    # 1. Direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Code block extraction
    if "```json" in text:
        block = text.split("```json", 1)[1]
        if "```" in block:
            block = block.split("```", 1)[0]
        try:
            return json.loads(block.strip())
        except json.JSONDecodeError:
            pass

    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            block = parts[1].strip()
            if block and block.split("\n")[0].isalpha():
                block = "\n".join(block.split("\n")[1:])
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                pass

    # 3. Find outermost { ... } block
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[brace_start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
                    break

    return None
