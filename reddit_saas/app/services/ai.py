"""AI service — wrapper around LiteLLM for all LLM calls.

Handles model routing, token tracking, cost calculation, logging,
and automatic model fallback on provider errors.
"""

import json
import re
import time
import copy
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
    "gemini/gemini-2.5-flash": ["gemini/gemini-2.5-flash-lite"],
    "gemini/gemini-2.5-flash-lite": ["gemini/gemini-2.5-flash"],
    "gemini/": ["gemini/gemini-2.5-flash-lite"],  # prefix fallback
    "anthropic/claude-sonnet-4-6": ["gemini/gemini-2.5-flash"],  # Anthropic fails → Gemini (not Haiku)
    "anthropic/claude-haiku-4-5": ["gemini/gemini-2.5-flash-lite"],
    "anthropic/": ["gemini/gemini-2.5-flash"],  # any Anthropic → Gemini
    "perplexity/sonar": ["gemini/gemini-2.5-flash"],  # GEO fallback: Perplexity → Gemini with grounding
    "perplexity/": ["gemini/gemini-2.5-flash"],  # prefix fallback
}

# Errors that trigger automatic model fallback
_FALLBACK_EXCEPTIONS = (
    litellm.exceptions.RateLimitError,
    litellm.exceptions.AuthenticationError,
    litellm.exceptions.BadRequestError,  # Includes "credit balance too low"
    litellm.exceptions.NotFoundError,
    litellm.exceptions.ServiceUnavailableError,
    litellm.exceptions.InternalServerError,
    litellm.exceptions.Timeout,
)


def _is_cache_control_error(error: Exception) -> bool:
    """Check if error is related to cache_control field (Anthropic prompt caching)."""
    msg = str(error).lower()
    return "cache_control" in msg or "caching" in msg

# ---------------------------------------------------------------------------
# LLM Budget Gate — hard cap on daily LLM calls to prevent runaway spend
# ---------------------------------------------------------------------------

# Limits per hour and per day. Exceeding = LLMBudgetExceeded raised.
_LLM_HOURLY_LIMIT = 500   # ~8x normal peak (60 calls/30min window × 2 pipelines)
_LLM_DAILY_LIMIT = 3000   # ~10x normal daily usage (~300 calls/day at 10 clients)

# ---------------------------------------------------------------------------
# Cost-Based Circuit Breaker (R-AI-007) — halts when spend rate is anomalous
# ---------------------------------------------------------------------------
# Rolling cost tracked per 10-minute window. If cost in any 10-min window
# exceeds threshold, all subsequent calls are blocked until the window expires.
_COST_WINDOW_SECONDS = 600          # 10-minute sliding window
_COST_WINDOW_LIMIT_USD = 5.0       # $5 per 10-min window (normal max ~$0.60 at peak)
_SINGLE_CALL_COST_LIMIT_USD = 1.0  # single call > $1 = block (should never happen)

# Per-task call counter — prevents a single Celery task from making unbounded LLM calls
_MAX_CALLS_PER_TASK = 50  # No single task invocation should need >50 LLM calls


class LLMBudgetExceeded(Exception):
    """Raised when LLM call budget is exhausted for the current period."""
    pass


class LLMRunawayDetected(LLMBudgetExceeded):
    """Raised when anomalous spend rate is detected (R-AI-007 circuit breaker)."""
    pass


# Per-task call counter (ContextVar — reset at each Celery task start)
_task_call_counter: ContextVar[int] = ContextVar("_task_call_counter", default=0)


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
    """Check Redis-based call counters AND cost circuit breaker.

    Three layers of protection (R-AI-007):
      1. Call count: hourly (500) + daily (3000) hard caps
      2. Cost window: $5 per 10-min rolling window (detects runaway loops early)
      3. Per-task cap: max 50 LLM calls per single Celery task invocation

    Keys:
      ramp:llm:calls:hourly:{YYYYMMDDHH} — TTL 7200s (2h)
      ramp:llm:calls:daily:{YYYYMMDD}   — TTL 90000s (25h)
      ramp:llm:cost:window:{YYYYMMDDHHMM_bucket} — TTL 900s (15 min, covers window + buffer)

    Fail-open: if Redis is unreachable, log warning and allow the call.
    """
    # --- Layer 3: Per-task call counter (no Redis needed) ---
    current_task_calls = _task_call_counter.get(0)
    if current_task_calls >= _MAX_CALLS_PER_TASK:
        logger.critical(
            "LLM_RUNAWAY_PER_TASK | calls_in_task=%d | limit=%d | model=%s | "
            "HALTING — single task exceeded max LLM calls",
            current_task_calls, _MAX_CALLS_PER_TASK, model,
        )
        raise LLMRunawayDetected(
            f"Single task exceeded max LLM calls: {current_task_calls}/{_MAX_CALLS_PER_TASK}. "
            f"Possible infinite loop detected."
        )
    _task_call_counter.set(current_task_calls + 1)

    try:
        import datetime as _dt

        redis = _get_budget_redis()
        if redis is None:
            return  # fail-open (settings not available)

        now = _dt.datetime.now(_dt.timezone.utc)
        hourly_key = f"ramp:llm:calls:hourly:{now.strftime('%Y%m%d%H')}"
        daily_key = f"ramp:llm:calls:daily:{now.strftime('%Y%m%d')}"

        # --- Layer 2: Cost circuit breaker (10-min window) ---
        # Bucket = 10-min slot (e.g., "2026070214:3" = 14:30-14:39)
        cost_bucket = f"{now.strftime('%Y%m%d%H')}:{now.minute // 10}"
        cost_key = f"ramp:llm:cost:window:{cost_bucket}"

        # Check current cost in window BEFORE making the call
        try:
            current_cost_raw = redis.get(cost_key)
            if current_cost_raw:
                current_cost = float(current_cost_raw)
                if current_cost >= _COST_WINDOW_LIMIT_USD:
                    logger.critical(
                        "LLM_RUNAWAY_COST_WINDOW | cost_usd=%.4f | limit=%.2f | "
                        "window=%s | model=%s | HALTING — spend rate too high",
                        current_cost, _COST_WINDOW_LIMIT_USD, cost_bucket, model,
                    )
                    raise LLMRunawayDetected(
                        f"LLM cost circuit breaker tripped: ${current_cost:.2f} in 10-min window "
                        f"(limit: ${_COST_WINDOW_LIMIT_USD:.2f}). Possible runaway loop."
                    )
        except LLMRunawayDetected:
            raise
        except Exception:
            pass  # fail-open on Redis error for cost check

        # --- Layer 1: Call count caps ---
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

    except (LLMBudgetExceeded, LLMRunawayDetected):
        raise
    except Exception as e:
        # Fail-open: Redis down or unexpected error — don't block LLM calls
        logger.warning("LLM budget gate error (fail-open): %s", str(e)[:100])


def _record_cost_in_window(cost_usd: float) -> None:
    """Record cost of a completed LLM call in the 10-min rolling window.

    Called AFTER a successful call to track accumulated spend.
    """
    if cost_usd <= 0:
        return
    try:
        import datetime as _dt
        redis = _get_budget_redis()
        if redis is None:
            return
        now = _dt.datetime.now(_dt.timezone.utc)
        cost_bucket = f"{now.strftime('%Y%m%d%H')}:{now.minute // 10}"
        cost_key = f"ramp:llm:cost:window:{cost_bucket}"
        # INCRBYFLOAT atomically adds to the cost counter
        redis.incrbyfloat(cost_key, cost_usd)
        redis.expire(cost_key, 900)  # 15 min TTL (covers 10-min window + buffer)
    except Exception as e:
        logger.debug("Cost window recording error (non-critical): %s", str(e)[:80])


def reset_task_call_counter() -> None:
    """Reset the per-task LLM call counter.

    Call this at the START of each Celery task to prevent counter
    accumulation across tasks in the same thread/process.
    """
    _task_call_counter.set(0)


# ---------------------------------------------------------------------------
# Provider Budget Gate — auto-fallback when approaching provider credit limit
# ---------------------------------------------------------------------------

# Cache provider spend to avoid DB query on every LLM call.
# Refreshed every 5 minutes via TTL check.
_provider_spend_cache: dict[str, float] = {}
_provider_spend_cache_ts: float = 0.0
_PROVIDER_SPEND_CACHE_TTL = 300  # 5 minutes


def _get_provider_from_model(model: str) -> str:
    """Extract provider name from model string."""
    if model.startswith("anthropic/") or model.startswith("bedrock/"):
        return "anthropic"
    elif model.startswith("gemini/"):
        return "gemini"
    elif model.startswith("perplexity/"):
        return "perplexity"
    elif model.startswith("openai/") or model.startswith("gpt"):
        return "openai"
    return "other"


def _refresh_provider_spend_cache() -> None:
    """Refresh the provider spend cache from DB (called at most every 5 min)."""
    global _provider_spend_cache, _provider_spend_cache_ts

    now = time.time()
    if now - _provider_spend_cache_ts < _PROVIDER_SPEND_CACHE_TTL:
        return  # cache still fresh

    try:
        from app.database import SessionLocal
        from app.models.ai_usage import AIUsageLog
        from sqlalchemy import func as _func, case as _case, literal_column
        from datetime import datetime as _dt, timezone as _tz

        db = SessionLocal()
        try:
            now_utc = _dt.now(_tz.utc)
            month_start = now_utc.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

            rows = (
                db.query(
                    _case(
                        (AIUsageLog.model.like("anthropic/%"), "anthropic"),
                        (AIUsageLog.model.like("gemini/%"), "gemini"),
                        (AIUsageLog.model.like("perplexity/%"), "perplexity"),
                        (AIUsageLog.model.like("openai/%"), "openai"),
                        (AIUsageLog.model.like("gpt%"), "openai"),
                        (AIUsageLog.model.like("bedrock/%"), "anthropic"),
                        else_="other",
                    ).label("provider"),
                    _func.coalesce(_func.sum(AIUsageLog.cost_usd), 0).label("total_cost"),
                )
                .filter(AIUsageLog.created_at >= month_start)
                .group_by(literal_column("provider"))
                .all()
            )

            _provider_spend_cache.clear()
            for row in rows:
                _provider_spend_cache[row.provider] = float(row.total_cost)
            _provider_spend_cache_ts = now
        finally:
            db.close()
    except Exception as e:
        logger.debug("Provider spend cache refresh failed (non-blocking): %s", str(e)[:80])


def _check_provider_budget(model: str) -> str:
    """Check if the model's provider is near budget exhaustion.

    If provider spend >= block_threshold (default 95%), auto-switch to
    a fallback provider. This prevents pipeline death when credits run out.

    Returns the model to use (original or fallback).
    """
    provider = _get_provider_from_model(model)
    if provider == "other":
        return model  # unknown provider, pass through

    # Refresh cache if stale
    _refresh_provider_spend_cache()

    spent = _provider_spend_cache.get(provider, 0.0)

    # Get budget limit from settings (cached in settings service)
    try:
        budget_key = f"provider_budget_{provider}_usd"
        budget_str = get_config(budget_key)
        budget = float(budget_str) if budget_str else 0.0
    except (ValueError, TypeError):
        budget = 0.0

    if budget <= 0:
        return model  # unlimited budget

    usage_pct = spent / budget

    # Get block threshold (default 95%)
    try:
        block_str = get_config("provider_budget_block_threshold_pct")
        block_threshold = float(block_str) / 100.0 if block_str else 0.95
    except (ValueError, TypeError):
        block_threshold = 0.95

    if usage_pct >= block_threshold:
        # Provider is near exhaustion — find a cross-provider fallback
        fallback = _get_cross_provider_fallback(provider)
        if fallback and fallback != model:
            logger.warning(
                "PROVIDER_BUDGET_GATE | provider=%s | spent=$%.2f/$%.0f (%.0f%%) | "
                "threshold=%.0f%% | auto_fallback=%s → %s",
                provider, spent, budget, usage_pct * 100,
                block_threshold * 100, model, fallback,
            )
            return fallback
        else:
            # No fallback available — log critical but allow the call
            logger.critical(
                "PROVIDER_BUDGET_EXHAUSTED | provider=%s | spent=$%.2f/$%.0f | "
                "NO FALLBACK AVAILABLE — call will proceed but may fail",
                provider, spent, budget,
            )

    elif usage_pct >= 0.70:
        # Warning zone — log but don't redirect
        logger.info(
            "PROVIDER_BUDGET_WARNING | provider=%s | spent=$%.2f/$%.0f (%.0f%%)",
            provider, spent, budget, usage_pct * 100,
        )

    return model


def _get_cross_provider_fallback(provider: str) -> str | None:
    """Get a fallback model from a DIFFERENT provider.

    Used when a provider's budget is exhausted. Routes to the best
    alternative that won't hit the same budget limit.
    """
    # Provider fallback preferences (quality-ordered)
    _CROSS_PROVIDER_FALLBACK = {
        "anthropic": "gemini/gemini-2.5-flash",      # Anthropic exhausted → Gemini (good quality, cheap)
        "gemini": "anthropic/claude-sonnet-4-6",     # Gemini exhausted → Anthropic (unlikely, Gemini is cheap)
        "perplexity": "gemini/gemini-2.5-flash",     # Perplexity exhausted → Gemini
        "openai": "gemini/gemini-2.5-flash",         # OpenAI exhausted → Gemini
    }

    fallback_model = _CROSS_PROVIDER_FALLBACK.get(provider)
    if not fallback_model:
        return None

    # Verify the fallback provider isn't ALSO exhausted
    fallback_provider = _get_provider_from_model(fallback_model)
    fallback_spent = _provider_spend_cache.get(fallback_provider, 0.0)

    try:
        fb_budget_key = f"provider_budget_{fallback_provider}_usd"
        fb_budget_str = get_config(fb_budget_key)
        fb_budget = float(fb_budget_str) if fb_budget_str else 0.0
    except (ValueError, TypeError):
        fb_budget = 0.0

    if fb_budget > 0 and (fallback_spent / fb_budget) >= 0.95:
        # Fallback provider is also exhausted — try the next option
        # Last resort: gemini-2.5-flash-lite (free tier)
        return "gemini/gemini-2.5-flash-lite"

    return fallback_model




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

    # --- Provider budget gate: auto-fallback when approaching provider credit limit ---
    model = _check_provider_budget(model)

    # --- Prompt Caching: inject cache_control for Anthropic models ---
    # deepcopy prevents mutation of caller's messages list
    cache_retry_attempted = False
    if model.startswith("anthropic/") and messages:
        effective_messages = copy.deepcopy(messages)
        effective_messages[0]["cache_control"] = {"type": "ephemeral"}
        kwargs["messages"] = effective_messages
    else:
        kwargs["messages"] = messages

    # Attempt call with fallback chain on provider errors
    response = None
    last_error = None

    # Build ordered list of models to try: [primary, ...fallbacks, generation_model]
    models_to_try = [model] + _get_fallback_chain(model)

    # Track the originally requested model for quality monitoring
    _original_requested_model = model

    for attempt_model in models_to_try:
        try:
            kwargs["model"] = attempt_model
            kwargs["api_key"] = _resolve_api_key(attempt_model)
            # If switching to non-Anthropic fallback, strip cache_control
            if not attempt_model.startswith("anthropic/") and kwargs.get("messages") is not messages:
                kwargs["messages"] = messages
            if attempt_model != model:
                start = time.time()  # reset timer for fallback
            response = litellm.completion(**kwargs)
            model = attempt_model  # track which model actually succeeded
            last_error = None
            break
        except _FALLBACK_EXCEPTIONS as e:
            # Check if error is cache_control related — retry once without it
            if not cache_retry_attempted and _is_cache_control_error(e):
                cache_retry_attempted = True
                logger.warning(
                    "PROMPT_CACHE_STRIPPED | model=%s | error=%s",
                    attempt_model, str(e)[:100],
                )
                kwargs["messages"] = messages  # use original without cache_control
                try:
                    response = litellm.completion(**kwargs)
                    model = attempt_model
                    last_error = None
                    break
                except _FALLBACK_EXCEPTIONS as e2:
                    last_error = e2
                    continue
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

    # --- Prompt Cache metrics logging ---
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    if cache_creation or cache_read:
        total_input = cache_read + cache_creation + input_tokens
        hit_ratio = cache_read / total_input if total_input > 0 else 0
        logger.info(
            "PROMPT_CACHE | model=%s | cache_creation=%d | cache_read=%d | hit_ratio=%.2f",
            model, cache_creation, cache_read, hit_ratio,
        )

    # Calculate cost — prefer litellm.completion_cost (includes web_search fees)
    try:
        cost_usd = litellm.completion_cost(completion_response=response)
    except Exception:
        cost_usd = _calculate_cost(model, input_tokens, output_tokens)

    # --- Expensive call alert: flag single calls > $0.10 for ops visibility ---
    if cost_usd > 0.10:
        logger.warning(
            "EXPENSIVE_LLM_CALL | model=%s | cost_usd=%.4f | "
            "input_tokens=%d | output_tokens=%d | duration_ms=%d",
            model, cost_usd, input_tokens, output_tokens, duration_ms,
        )

    # --- R-AI-007: Single-call cost hard limit ---
    if cost_usd > _SINGLE_CALL_COST_LIMIT_USD:
        logger.critical(
            "LLM_SINGLE_CALL_COST_LIMIT | model=%s | cost_usd=%.4f | limit=%.2f | "
            "input_tokens=%d | output_tokens=%d | "
            "ALERT — single call exceeded cost limit (response already received)",
            model, cost_usd, _SINGLE_CALL_COST_LIMIT_USD,
            input_tokens, output_tokens,
        )

    # --- R-AI-007: Record cost in rolling window for circuit breaker ---
    _record_cost_in_window(cost_usd)

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
        "requested_model": _original_requested_model,
        "fallback_used": model != _original_requested_model,
        "quality_outcome": "fallback_used" if model != _original_requested_model else "success",
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
    # Retry with fallback model before giving up — Gemini sometimes returns empty
    # content with output_tokens > 0 (safety filter, structured output parse issue).
    if not content or not content.strip():
        retry_model = _get_json_retry_model(result.get("model", model or ""))
        if retry_model:
            logger.warning(
                "LLM_JSON_EMPTY_RESPONSE | model=%s | output_tokens=%s | retrying with %s",
                result.get("model"), result.get("output_tokens", "?"), retry_model,
            )
            result = call_llm(
                messages=messages,
                model=retry_model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            content = result["content"]

        if not content or not content.strip():
            result["quality_outcome"] = "empty"
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
        result["quality_outcome"] = "parse_error"
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
    result["quality_outcome"] = "success"
    return result


def _extract_json(content: str) -> dict | None:
    """Extract JSON object from LLM response content.

    Handles multiple formats:
    1. Pure JSON string
    2. Markdown code blocks (```json ... ``` or ``` ... ```)
    3. Prose-wrapped JSON (e.g. "Here is the JSON response: {...}")
    4. JSON with trailing commas or minor syntax issues
    5. Truncated JSON (missing closing braces — common with max_tokens cutoff)

    Returns parsed dict or None if extraction failed.
    """
    if not content or not content.strip():
        return None

    text = content.strip()

    # 0. Strip common Gemini preamble patterns before any parsing
    # Gemini often prepends "Here is the JSON requested:" or similar
    preamble_patterns = [
        r"^Here\s+is\s+the\s+JSON\s*(?:requested|response|output)?:?\s*",
        r"^(?:Sure|Okay|Certainly)[,!.]?\s*(?:Here(?:'s|\s+is)\s+the\s+JSON)?:?\s*",
        r"^```(?:json)?\s*\n?",  # Leading code fence without closing
    ]
    cleaned = text
    for pattern in preamble_patterns:
        cleaned = re.sub(pattern, "", cleaned, count=1, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    # Remove trailing code fence if present
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3].strip()

    # 1. Try direct JSON parse on cleaned text
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Also try original text (in case cleaning damaged it)
    if cleaned != text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # 2. Extract from markdown code blocks (case-insensitive)
    text_lower = text.lower()
    if "```json" in text_lower:
        # Find the actual position case-insensitively
        idx = text_lower.find("```json")
        block = text[idx + 7:]  # len("```json") = 7
        if "```" in block:
            block = block.split("```", 1)[0]
        block = block.strip()
        try:
            return json.loads(block)
        except json.JSONDecodeError:
            # Try fixing truncated JSON
            fixed = _try_fix_truncated_json(block)
            if fixed is not None:
                return fixed

    if "```" in text:
        parts = text.split("```")
        if len(parts) >= 3:
            block = parts[1].strip()
            # Remove optional language hint on first line (json, JSON, etc.)
            first_line = block.split("\n")[0].strip()
            if first_line and (first_line.isalpha() or first_line.lower() in ("json", "javascript", "js")):
                block = "\n".join(block.split("\n")[1:])
            try:
                return json.loads(block.strip())
            except json.JSONDecodeError:
                fixed = _try_fix_truncated_json(block.strip())
                if fixed is not None:
                    return fixed
        # Handle case where there's only opening ``` (no closing — truncated)
        elif len(parts) == 2:
            block = parts[1].strip()
            first_line = block.split("\n")[0].strip()
            if first_line and first_line.lower() in ("json", "javascript", "js", ""):
                block = "\n".join(block.split("\n")[1:])
            block = block.strip()
            if block:
                try:
                    return json.loads(block)
                except json.JSONDecodeError:
                    fixed = _try_fix_truncated_json(block)
                    if fixed is not None:
                        return fixed

    # 3. Find the outermost { ... } block (greedy — handles nested objects)
    brace_start = text.find("{")
    if brace_start != -1:
        # Find matching closing brace
        depth = 0
        end_pos = -1
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    end_pos = i
                    break

        if end_pos != -1:
            candidate = text[brace_start:end_pos + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Try fixing trailing commas
                fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
                try:
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass
        else:
            # No matching closing brace found — likely truncated by max_tokens
            # Try to close the JSON ourselves
            candidate = text[brace_start:]
            fixed = _try_fix_truncated_json(candidate)
            if fixed is not None:
                return fixed

    # 4. Last resort: find any JSON-like pattern with regex
    json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass

    return None


def _try_fix_truncated_json(text: str) -> dict | None:
    """Attempt to fix truncated JSON by closing open braces/brackets.

    Common with max_tokens cutoff: {"comment": "Great post about bre
    We try to salvage by closing strings and braces.
    """
    if not text or not text.strip():
        return None

    text = text.strip()

    # Remove trailing commas
    text = re.sub(r',\s*$', '', text)

    # If it doesn't start with {, skip
    if not text.startswith("{"):
        # Try to find { in text
        brace_pos = text.find("{")
        if brace_pos == -1:
            return None
        text = text[brace_pos:]

    # Count unclosed braces and brackets
    in_string = False
    escape_next = False
    open_braces = 0
    open_brackets = 0
    last_meaningful_char = ""

    for ch in text:
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            open_braces += 1
        elif ch == "}":
            open_braces -= 1
        elif ch == "[":
            open_brackets += 1
        elif ch == "]":
            open_brackets -= 1
        if ch.strip():
            last_meaningful_char = ch

    # If already balanced, try direct parse
    if open_braces == 0 and open_brackets == 0:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    # Try to close an open string (truncated mid-value)
    if in_string:
        text += '"'

    # Remove trailing comma after closing string
    text = re.sub(r',\s*$', '', text)

    # Close open brackets then braces
    text += "]" * max(0, open_brackets)
    text += "}" * max(0, open_braces)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
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

    # Always add generation model as ultimate fallback, then Gemini as safety net
    try:
        generation_model = get_config("llm_generation_model")
        if generation_model and generation_model not in fallbacks:
            fallbacks.append(generation_model)
        # If generation_model is Anthropic, also add Gemini as absolute last resort
        if generation_model and generation_model.startswith("anthropic/"):
            gemini_safety = "gemini/gemini-2.5-flash"
            if gemini_safety not in fallbacks:
                fallbacks.append(gemini_safety)
    except Exception:
        # DB unavailable — use Gemini Flash as last resort (always available, no credit limits)
        ultimate = "gemini/gemini-2.5-flash"
        if ultimate not in fallbacks:
            fallbacks.append(ultimate)

    # Remove the primary model from fallbacks
    fallbacks = [m for m in fallbacks if m != model]
    return fallbacks


def _get_json_retry_model(failed_model: str) -> str | None:
    """Get a different-provider model for JSON retry.

    Strategy: stay within free/cheap providers. Avoid Anthropic as fallback
    because of credit limits. Use Gemini variants (free tier / very cheap).
    """
    if failed_model == "gemini/gemini-2.5-flash":
        return "gemini/gemini-2.5-flash-lite"
    elif failed_model == "gemini/gemini-2.5-flash-lite":
        return "gemini/gemini-2.5-flash"
    elif failed_model.startswith("gemini/"):
        return "gemini/gemini-2.5-flash"
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
    quality_outcome: str | None = None,
    fallback_model: str | None = None,
    retry_count: int = 0,
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
        quality_outcome: Quality classification (success/empty/parse_error/timeout/error/fallback_used)
        fallback_model: If fallback was used, which model ultimately succeeded
        retry_count: How many retries were needed
    """
    # Auto-detect quality_outcome if not explicitly provided
    if quality_outcome is None:
        quality_outcome = result.get("quality_outcome", "success")

    # Auto-detect fallback_model from result
    if fallback_model is None and result.get("fallback_used"):
        fallback_model = result.get("requested_model")

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
        quality_outcome=quality_outcome,
        fallback_model=fallback_model,
        retry_count=retry_count,
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
