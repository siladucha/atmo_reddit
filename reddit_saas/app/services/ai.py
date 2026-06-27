"""AI service — wrapper around LiteLLM for all LLM calls.

Handles model routing, token tracking, cost calculation, logging,
and automatic model fallback on provider errors.
"""

import json
import re
import time
from app.logging_config import get_logger
from contextvars import ContextVar
from decimal import Decimal

import litellm
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.ai_usage import AIUsageLog

logger = get_logger(__name__)

# Disable LiteLLM's verbose logging
litellm.set_verbose = False

# Context variable: set once at task/route level, auto-propagates to all log_ai_usage calls
# Values: "scheduler", "manual", "orchestrator", "api", "test_run", "wizard"
ai_trigger_context: ContextVar[str | None] = ContextVar("ai_trigger_context", default=None)

# Cost per 1M tokens (update as prices change)
MODEL_COSTS = {
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "anthropic/claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "anthropic/claude-haiku-4-5": {"input": 1.00, "output": 5.00},
    "anthropic/claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "gemini/gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini/gemini-2.5-flash-lite": {"input": 0.0, "output": 0.0},  # Free tier
    "gemini/gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    # Bedrock variants
    "bedrock/anthropic.claude-sonnet-4-20250514-v1:0": {"input": 3.00, "output": 15.00},
    "bedrock/anthropic.claude-3-5-haiku-20241022-v1:0": {"input": 0.80, "output": 4.00},
}

# Fallback model chain: if primary model fails, try these in order.
# Key = model prefix or exact model name, Value = ordered list of fallbacks.
MODEL_FALLBACK_CHAIN = {
    "gemini/gemini-2.5-flash": ["gemini/gemini-2.5-flash-lite", "anthropic/claude-haiku-4-5"],
    "gemini/gemini-2.5-flash-lite": ["gemini/gemini-2.5-flash", "anthropic/claude-haiku-4-5"],
    "gemini/": ["gemini/gemini-2.5-flash-lite", "anthropic/claude-haiku-4-5"],  # prefix fallback
    "perplexity/sonar": ["gemini/gemini-2.5-flash"],  # GEO fallback: Perplexity → Gemini with grounding
    "perplexity/": ["gemini/gemini-2.5-flash"],  # prefix fallback
}

# Errors that trigger automatic model fallback
_FALLBACK_EXCEPTIONS = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.AuthenticationError,
    litellm.exceptions.NotFoundError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.Timeout,
)

# ---------------------------------------------------------------------------
# LLM Budget Gate — hard cap on daily LLM calls to prevent runaway spend
# ---------------------------------------------------------------------------

# Limits per hour and per day. Exceeding = LLMBudgetExceeded raised.
_LLM_HOURLY_LIMIT = 500   # ~8x normal peak (60 calls/30min window × 2 pipelines)
_LLM_DAILY_LIMIT = 3000   # ~10x normal daily usage (~300 calls/day at 10 clients)


class LLMBudgetExceeded(Exception):
    """Raised when LLM call budget is exhausted for the current period."""
    pass


# Cached Redis connection for budget gate (avoid per-call overhead)
_budget_redis_client = None


def _get_budget_redis():
    """Get or create a cached Redis client for budget tracking."""
    global _budget_redis_client
    if _budget_redis_client is None:
        try:
            import redis as _redis_lib
            from app.config import get_settings
            settings = get_settings()
            _budget_redis_client = _redis_lib.from_url(settings.redis_url, decode_responses=True)
        except Exception:
            return None
    return _budget_redis_client


def _check_llm_budget_gate(model: str) -> None:
    """Check Redis-based call counters. Raise LLMBudgetExceeded if limits hit.

    Keys:
      ramp:llm:calls:hourly:{YYYYMMDDHH} — TTL 7200s (2h)
      ramp:llm:calls:daily:{YYYYMMDD}   — TTL 90000s (25h)

    Fail-open: if Redis is unreachable, log warning and allow the call.
    """
    try:
        import datetime as _dt

        redis = _get_budget_redis()
        if redis is None:
            return  # fail-open (settings not available)

        now = _dt.datetime.now(_dt.timezone.utc)
        hourly_key = f"ramp:llm:calls:hourly:{now.strftime('%Y%m%d%H')}"
        daily_key = f"ramp:llm:calls:daily:{now.strftime('%Y%m%d')}"

        # Atomic increment
        pipe = redis.pipeline(transaction=False)
        pipe.incr(hourly_key)
        pipe.expire(hourly_key, 7200)
        pipe.incr(daily_key)
        pipe.expire(daily_key, 90000)
        results = pipe.execute()

        hourly_count = results[0]
        daily_count = results[2]

        if hourly_count > _LLM_HOURLY_LIMIT:
            logger.critical(
                "LLM_BUDGET_EXCEEDED_HOURLY | count=%d | limit=%d | model=%s",
                hourly_count, _LLM_HOURLY_LIMIT, model,
            )
            raise LLMBudgetExceeded(
                f"Hourly LLM call limit exceeded: {hourly_count}/{_LLM_HOURLY_LIMIT}"
            )

        if daily_count > _LLM_DAILY_LIMIT:
            logger.critical(
                "LLM_BUDGET_EXCEEDED_DAILY | count=%d | limit=%d | model=%s",
                daily_count, _LLM_DAILY_LIMIT, model,
            )
            raise LLMBudgetExceeded(
                f"Daily LLM call limit exceeded: {daily_count}/{_LLM_DAILY_LIMIT}"
            )

        # Warning at 80%
        if hourly_count > _LLM_HOURLY_LIMIT * 0.8 or daily_count > _LLM_DAILY_LIMIT * 0.8:
            logger.warning(
                "LLM_BUDGET_WARNING | hourly=%d/%d | daily=%d/%d | model=%s",
                hourly_count, _LLM_HOURLY_LIMIT, daily_count, _LLM_DAILY_LIMIT, model,
            )

    except LLMBudgetExceeded:
        raise
    except Exception as e:
        # Fail-open: Redis down or unexpected error — don't block LLM calls
        logger.warning("LLM budget gate error (fail-open): %s", str(e)[:100])




def call_llm(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    response_format: dict | None = None,
    timeout: int = 60,
) -> dict:
    """Make an LLM call and return the response with usage metadata.

    Automatic fallback: if the primary model fails with a provider error
    (404, 429, 500, 503, timeout, auth), tries fallback models from
    MODEL_FALLBACK_CHAIN, then finally the generation model (Sonnet).

    Args:
        messages: List of message dicts [{"role": "system", "content": "..."}, ...]
        model: Model identifier. Defaults to generation model from config.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        response_format: Optional JSON schema for structured output.

    Returns:
        Dict with keys: content, input_tokens, output_tokens, cost_usd, duration_ms, model
    """
    model = model or get_config("llm_generation_model")
    start = time.time()

    # Route API key based on model provider
    api_key = _resolve_api_key(model)
    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Hard timeout — without this a hung provider blocks a Celery worker
        # until Celery's task hard timeout (often minutes), starving the queue.
        "timeout": timeout,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if response_format:
        kwargs["response_format"] = response_format

    # Log the outgoing LLM request
    total_prompt_chars = sum(len(m.get("content", "")) for m in messages)
    logger.info(
        "LLM_CALL | model=%s | temperature=%.2f | max_tokens=%d | "
        "messages_count=%d | prompt_chars=%d | response_format=%s",
        model, temperature, max_tokens, len(messages),
        total_prompt_chars, "json" if response_format else "text",
    )

    # --- Hard budget gate: prevent runaway LLM spend ---
    _check_llm_budget_gate(model)

    # Attempt call with fallback chain on provider errors
    response = None
    last_error = None

    # Build ordered list of models to try: [primary, ...fallbacks, generation_model]
    models_to_try = [model] + _get_fallback_chain(model)

    for attempt_model in models_to_try:
        try:
            kwargs["model"] = attempt_model
            kwargs["api_key"] = _resolve_api_key(attempt_model)
            if attempt_model != model:
                start = time.time()  # reset timer for fallback
            response = litellm.completion(**kwargs)
            model = attempt_model  # track which model actually succeeded
            last_error = None
            break
        except _FALLBACK_EXCEPTIONS as e:
            last_error = e
            logger.warning(
                "LLM_FALLBACK | model=%s failed (%s: %s)",
                attempt_model, type(e).__name__, str(e)[:150],
            )
            continue
        except Exception:
            # Non-retryable error (e.g. bad request, content filter) — don't fallback
            raise

    if response is None:
        # All models exhausted — re-raise the last provider error
        logger.error("LLM_ALL_MODELS_FAILED | tried=%s | last_error=%s", models_to_try, last_error)
        raise last_error  # type: ignore[misc]

    duration_ms = int((time.time() - start) * 1000)
    content = response.choices[0].message.content or ""

    # Extract token usage
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    # Calculate cost
    cost_usd = _calculate_cost(model, input_tokens, output_tokens)

    # Log the response
    logger.info(
        "LLM_RESULT | model=%s | input_tokens=%d | output_tokens=%d | "
        "cost_usd=%.6f | duration_ms=%d | response_chars=%d",
        model, input_tokens, output_tokens, cost_usd, duration_ms,
        len(content) if content else 0,
    )
    logger.debug(
        "LLM_RESPONSE_BODY | model=%s | content=%s",
        model, (content[:500] + "...") if content and len(content) > 500 else content,
    )

    return {
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "duration_ms": duration_ms,
        "model": model,
    }


def call_llm_json(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    schema: type[BaseModel] | None = None,
) -> dict:
    """Make an LLM call expecting JSON output. Parses the response.

    Robust JSON extraction: handles raw JSON, markdown code blocks,
    prose-wrapped JSON (common with Gemini), and nested objects.
    Retries once with a different model on parse failure.

    Args:
        messages: List of message dicts.
        model: Model identifier.
        temperature: Sampling temperature.
        max_tokens: Max output tokens.
        schema: Optional Pydantic model class to validate the parsed JSON against.

    Returns:
        Dict with keys: data (parsed+validated JSON), input_tokens, output_tokens,
        cost_usd, duration_ms, model

    Raises:
        ValueError: If JSON cannot be extracted after all retries.
        ValidationError: If schema is provided and the LLM response fails validation.
    """
    result = call_llm(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )

    content = result["content"]

    # Guard: LLM returned None or empty string (safety filter, rate limit, etc.)
    if not content or not content.strip():
        raise ValueError(
            f"LLM returned empty response (model={result.get('model', 'unknown')}, "
            f"input_tokens={result.get('input_tokens', '?')}, "
            f"output_tokens={result.get('output_tokens', '?')})"
        )

    # Attempt to parse JSON from the response
    data = _extract_json(content)

    if data is None:
        # First parse failed — retry with a fallback model (different provider)
        retry_model = _get_json_retry_model(result.get("model", model or ""))
        if retry_model:
            logger.warning(
                "LLM_JSON_PARSE_FAILED | model=%s | retrying with %s | content_preview=%s",
                result.get("model"), retry_model, repr(content[:150]),
            )
            result = call_llm(
                messages=messages,
                model=retry_model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            content = result["content"]
            if content and content.strip():
                data = _extract_json(content)

    if data is None:
        raise ValueError(
            f"LLM returned non-JSON response after retry "
            f"(model={result.get('model', 'unknown')}, "
            f"content_preview={content[:200]!r})"
        )

    # Validate against schema if provided
    if schema is not None:
        validated = schema.model_validate(data)
        data = validated.model_dump()

    result["data"] = data
    return result


def _extract_json(content: str) -> dict | None:
    """Extract JSON object from LLM response content.

    Handles multiple formats:
    1. Pure JSON string
    2. Markdown code blocks (```json ... ``` or ``` ... ```)
    3. Prose-wrapped JSON (e.g. "Here is the JSON response: {...}")
    4. JSON with trailing commas or minor syntax issues

    Returns parsed dict or None if extraction failed.
    """
    if not content or not content.strip():
        return None

    text = content.strip()

    # 1. Try direct JSON parse (most common case)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code blocks
    if "```json" in text:
        block = text.split("```json", 1)[1]
        if "```" in block:
            block = block.split("```", 1)[0]
        block = block.strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            pass

    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            block = parts[1].strip()
            # Remove optional language hint on first line
            if block and block.split("\n")[0].isalpha():
                block = "\n".join(block.split("\n")[1:])
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                pass

    # 3. Find the outermost { ... } block (greedy — handles nested objects)
    brace_start = text.find("{")
    if brace_start != -1:
        # Find matching closing brace
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
                        # Try fixing trailing commas
                        fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
                        try:
                            return json.loads(fixed)
                        except json.JSONDecodeError:
                            pass
                    break

    # 4. Last resort: find any JSON-like pattern with regex
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _get_fallback_chain(model: str) -> list[str]:
    """Get ordered fallback models for a given model.

    Returns deduplicated list (excludes the primary model itself).
    Always ends with the generation model as ultimate fallback.
    """
    fallbacks = []

    # Check exact match first, then prefix match
    if model in MODEL_FALLBACK_CHAIN:
        fallbacks = list(MODEL_FALLBACK_CHAIN[model])
    else:
        # Try prefix match (e.g. "gemini/" catches any gemini model)
        for prefix, chain in MODEL_FALLBACK_CHAIN.items():
            if prefix.endswith("/") and model.startswith(prefix):
                fallbacks = list(chain)
                break

    # Always add generation model as ultimate fallback
    try:
        generation_model = get_config("llm_generation_model")
        if generation_model and generation_model not in fallbacks:
            fallbacks.append(generation_model)
    except Exception:
        # DB unavailable — use hardcoded Sonnet as last resort
        ultimate = "anthropic/claude-sonnet-4-6"
        if ultimate not in fallbacks:
            fallbacks.append(ultimate)

    # Remove the primary model from fallbacks
    fallbacks = [m for m in fallbacks if m != model]
    return fallbacks


def _get_json_retry_model(failed_model: str) -> str | None:
    """Get a different-provider model for JSON retry.

    If Gemini failed to produce valid JSON, retry with Haiku (cheaper than Sonnet).
    If Anthropic failed, retry with Gemini Flash Lite.
    """
    if failed_model.startswith("gemini/"):
        return "anthropic/claude-haiku-4-5"
    elif failed_model.startswith("anthropic/"):
        return "gemini/gemini-2.5-flash-lite"
    return None


def log_ai_usage(
    db: Session,
    client_id: str | None,
    operation: str,
    result: dict,
    *,
    avatar_id: str | None = None,
    thread_id: str | None = None,
    subreddit_name: str | None = None,
    triggered_by: str | None = None,
) -> None:
    """Log an AI call to the ai_usage_log table.

    Args:
        db: Database session
        client_id: Client UUID string (or None for system operations)
        operation: Operation name (scoring, persona_select, generation, editing, hobby_comment)
        result: Dict returned by call_llm or call_llm_json
        avatar_id: Avatar UUID string (optional, for per-avatar cost tracking)
        thread_id: Thread UUID string (optional, for per-thread cost tracking)
        subreddit_name: Subreddit name (optional, for per-subreddit cost tracking)
        triggered_by: What initiated this call (scheduler, manual, orchestrator, api, test_run)
    """
    log = AIUsageLog(
        client_id=client_id,
        avatar_id=avatar_id,
        thread_id=thread_id,
        subreddit_name=subreddit_name,
        operation=operation,
        model=result["model"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        cost_usd=Decimal(str(result["cost_usd"])),
        duration_ms=result["duration_ms"],
        triggered_by=triggered_by or ai_trigger_context.get(),
    )
    db.add(log)
    db.commit()


def _resolve_api_key(model: str) -> str | None:
    """Route API key based on model provider.

    Ori's workflow used different providers per step:
    - Gemini Flash for scoring/classification (cheap, fast)
    - Claude Opus/Sonnet for generation (quality)
    - GPT for fallback

    We mirror this by resolving the correct key per provider prefix.
    """
    if model.startswith("gemini/"):
        key = get_config("gemini_api_key")
        if not key:
            # Fallback: try main LLM key (works if using OpenRouter or unified key)
            key = get_config("llm_api_key")
        return key or None
    elif model.startswith("anthropic/"):
        return get_config("llm_api_key")
    elif model.startswith("perplexity/"):
        # GEO module uses Perplexity Sonar — key from system settings
        key = get_config("geo_perplexity_api_key") if _setting_exists("geo_perplexity_api_key") else None
        if not key:
            import os
            key = os.environ.get("PERPLEXITY_API_KEY")
        return key or None
    elif model.startswith("bedrock/"):
        return None  # Uses AWS credentials from env
    elif model.startswith("openai/") or model.startswith("gpt"):
        return get_config("openai_api_key") if _setting_exists("openai_api_key") else None
    else:
        # Fallback: try the main llm_api_key
        return get_config("llm_api_key")


def _setting_exists(key: str) -> bool:
    """Check if a setting exists and is non-empty."""
    try:
        val = get_config(key)
        return bool(val and val.strip())
    except Exception:
        return False


def _calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate cost in USD based on model and token counts."""
    costs = MODEL_COSTS.get(model)
    if not costs:
        # Try partial match (for bedrock/ prefix variants)
        for key, val in MODEL_COSTS.items():
            if key in model or model in key:
                costs = val
                break

    if not costs:
        logger.warning(f"Unknown model for cost calculation: {model}")
        return 0.0

    input_cost = (input_tokens / 1_000_000) * costs["input"]
    output_cost = (output_tokens / 1_000_000) * costs["output"]
    return round(input_cost + output_cost, 6)
