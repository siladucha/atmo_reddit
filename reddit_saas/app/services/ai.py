"""AI service — wrapper around LiteLLM for all LLM calls.

Handles model routing, token tracking, cost calculation, and logging.
"""

import json
import time
import logging
from decimal import Decimal

import litellm
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.ai_usage import AIUsageLog

logger = logging.getLogger(__name__)
settings = get_settings()

# Disable LiteLLM's verbose logging
litellm.set_verbose = False

# Cost per 1M tokens (update as prices change)
MODEL_COSTS = {
    "anthropic/claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "anthropic/claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    "gemini/gemini-2.0-flash": {"input": 0.075, "output": 0.30},
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
    model = model or settings.litellm_generation_model
    start = time.time()

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = litellm.completion(**kwargs)

    duration_ms = int((time.time() - start) * 1000)
    content = response.choices[0].message.content

    # Extract token usage
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    # Calculate cost
    cost_usd = _calculate_cost(model, input_tokens, output_tokens)

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
