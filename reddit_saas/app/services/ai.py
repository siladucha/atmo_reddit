"""AI service — wrapper around LiteLLM for all LLM calls.

Handles model routing, token tracking, cost calculation, and logging.
"""

import json
import time
import logging
from decimal import Decimal

import litellm
from sqlalchemy.orm import Session

from app.config import get_config
from app.models.ai_usage import AIUsageLog

logger = logging.getLogger(__name__)

# Disable LiteLLM's verbose logging
litellm.set_verbose = False

# Cost per 1M tokens (update as prices change)
MODEL_COSTS = {
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "gemini/gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini/gemini-2.5-flash-lite": {"input": 0.0, "output": 0.0},  # Free tier
    "gemini/gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    # Bedrock variants
    "bedrock/anthropic.claude-sonnet-4-20250514-v1:0": {"input": 3.00, "output": 15.00},
    "bedrock/anthropic.claude-3-5-haiku-20241022-v1:0": {"input": 0.80, "output": 4.00},
}


def call_llm(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1024,
    response_format: dict | None = None,
) -> dict:
    """Make an LLM call and return the response with usage metadata.

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

    # Call with automatic fallback: if primary model fails (rate limit, auth),
    # fall back to generation model (Anthropic Sonnet)
    try:
        response = litellm.completion(**kwargs)
    except (litellm.exceptions.RateLimitError, litellm.exceptions.AuthenticationError) as e:
        fallback_model = get_config("llm_generation_model")
        if model != fallback_model:
            logger.warning(
                "LLM_FALLBACK | model=%s failed (%s), falling back to %s",
                model, type(e).__name__, fallback_model,
            )
            kwargs["model"] = fallback_model
            kwargs["api_key"] = _resolve_api_key(fallback_model)
            model = fallback_model
            start = time.time()  # reset timer
            response = litellm.completion(**kwargs)
        else:
            raise

    duration_ms = int((time.time() - start) * 1000)
    content = response.choices[0].message.content

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
) -> dict:
    """Make an LLM call expecting JSON output. Parses the response.

    Returns:
        Dict with keys: data (parsed JSON), input_tokens, output_tokens, cost_usd, duration_ms, model
    """
    result = call_llm(
        messages=messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )

    try:
        data = json.loads(result["content"])
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        content = result["content"]
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        data = json.loads(content)

    result["data"] = data
    return result


def log_ai_usage(
    db: Session,
    client_id: str | None,
    operation: str,
    result: dict,
) -> None:
    """Log an AI call to the ai_usage_log table.

    Args:
        db: Database session
        client_id: Client UUID string (or None for system operations)
        operation: Operation name (scoring, persona_select, generation, editing)
        result: Dict returned by call_llm or call_llm_json
    """
    log = AIUsageLog(
        client_id=client_id,
        operation=operation,
        model=result["model"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
        cost_usd=Decimal(str(result["cost_usd"])),
        duration_ms=result["duration_ms"],
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
        return get_config("gemini_api_key")
    elif model.startswith("anthropic/"):
        return get_config("llm_api_key")
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
