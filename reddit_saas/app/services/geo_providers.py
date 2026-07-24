"""GEO Provider Abstraction — multi-engine AI search monitoring.

Supports:
- Perplexity Sonar (primary, existing)
- OpenAI web search (gpt-4o-search-preview via web_search_options)
- Anthropic Claude web search (claude-3-5-sonnet with web_search_options)

Each provider uses LiteLLM's unified web_search_options interface.
Brand detection and citation parsing are provider-agnostic (work on raw text).
"""

import time
import uuid
from dataclasses import dataclass

import litellm

from app.logging_config import get_logger
from app.services.ai import _resolve_api_key, _calculate_cost, MODEL_COSTS

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Provider definitions
# ---------------------------------------------------------------------------

PROVIDER_PERPLEXITY = "perplexity"
PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"

ALL_PROVIDERS = [PROVIDER_PERPLEXITY, PROVIDER_OPENAI, PROVIDER_ANTHROPIC]


@dataclass
class GeoProviderConfig:
    """Configuration for a GEO monitoring provider."""

    name: str  # perplexity | openai | anthropic
    model: str  # litellm model string
    display_name: str  # UI display name
    color_class: str  # Tailwind CSS class for badges
    setting_key_enabled: str  # system_settings key for enable/disable
    setting_key_api: str  # system_settings key for API key (or "" if from env)
    cost_per_query_usd: float  # approximate cost for budgeting
    uses_web_search_options: bool  # whether to pass web_search_options param


PROVIDERS: dict[str, GeoProviderConfig] = {
    PROVIDER_PERPLEXITY: GeoProviderConfig(
        name=PROVIDER_PERPLEXITY,
        model="perplexity/sonar",
        display_name="Perplexity",
        color_class="purple",
        setting_key_enabled="geo_provider_perplexity_enabled",
        setting_key_api="geo_perplexity_api_key",
        cost_per_query_usd=0.01,
        uses_web_search_options=False,  # Perplexity searches by default
    ),
    PROVIDER_OPENAI: GeoProviderConfig(
        name=PROVIDER_OPENAI,
        model="openai/gpt-4o-search-preview",
        display_name="ChatGPT",
        color_class="green",
        setting_key_enabled="geo_provider_openai_enabled",
        setting_key_api="openai_api_key",  # stored in system_settings
        cost_per_query_usd=0.04,
        uses_web_search_options=True,
    ),
    PROVIDER_ANTHROPIC: GeoProviderConfig(
        name=PROVIDER_ANTHROPIC,
        model="anthropic/claude-sonnet-4-6",
        display_name="Claude",
        color_class="orange",
        setting_key_enabled="geo_provider_anthropic_enabled",
        setting_key_api="",  # uses llm_api_key via _resolve_api_key (shared Anthropic key)
        cost_per_query_usd=0.03,
        uses_web_search_options=True,
    ),
}

# Register costs for new models in MODEL_COSTS (input/output per 1M tokens)
MODEL_COSTS.setdefault("openai/gpt-4o-search-preview", {"input": 2.50, "output": 10.00})
MODEL_COSTS.setdefault("anthropic/claude-sonnet-4-6", {"input": 3.00, "output": 15.00})


# ---------------------------------------------------------------------------
# Provider execution
# ---------------------------------------------------------------------------

# System prompt for GEO queries (shared across all providers)
GEO_SYSTEM_PROMPT = (
    "You are an AI assistant helping a user research solutions. "
    "Answer the question comprehensively, citing sources where possible. "
    "Include URLs and references to sources you find."
)


@dataclass
class ProviderQueryResult:
    """Result of a single provider query."""

    success: bool
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    model: str
    provider: str
    error: str | None = None


def execute_provider_query(
    provider_config: GeoProviderConfig,
    prompt_text: str,
    api_key: str | None = None,
    timeout: int = 60,
) -> ProviderQueryResult:
    """Execute a single GEO query against a provider.

    Uses LiteLLM's web_search_options for OpenAI and Anthropic.
    Perplexity searches by default (no extra params needed).

    Args:
        provider_config: Provider configuration.
        prompt_text: The buyer-intent prompt to send.
        api_key: Optional API key override.
        timeout: Request timeout in seconds.

    Returns:
        ProviderQueryResult with success/failure and response data.
    """
    messages = [
        {"role": "system", "content": GEO_SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
    ]

    model = provider_config.model
    provider_name = provider_config.name

    kwargs: dict = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
        "timeout": timeout,
    }

    # Resolve API key
    resolved_key = api_key or _resolve_api_key(model)
    if resolved_key:
        kwargs["api_key"] = resolved_key

    # Add web_search_options for providers that need it
    if provider_config.uses_web_search_options:
        kwargs["web_search_options"] = {
            "search_context_size": "medium",
        }

    start_ms = time.time()

    try:
        response = litellm.completion(**kwargs)

        duration_ms = int((time.time() - start_ms) * 1000)
        content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        # Use litellm.completion_cost for accurate cost (includes web_search fees)
        try:
            cost_usd = litellm.completion_cost(completion_response=response)
        except Exception:
            cost_usd = _calculate_cost(model, input_tokens, output_tokens)

        return ProviderQueryResult(
            success=True,
            content=content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            model=model,
            provider=provider_name,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_ms) * 1000)
        logger.warning(
            "GEO_PROVIDER_ERROR | provider=%s | model=%s | error=%s | duration_ms=%d",
            provider_name, model, str(e)[:200], duration_ms,
        )
        return ProviderQueryResult(
            success=False,
            content="",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0,
            duration_ms=duration_ms,
            model=model,
            provider=provider_name,
            error=str(e)[:500],
        )


def get_enabled_providers(db) -> list[GeoProviderConfig]:
    """Get list of enabled GEO providers based on system settings.

    A provider is enabled if:
    1. Its setting key is "true" (or not set — defaults to enabled for Perplexity)
    2. Its API key is available (either in system settings or env vars)

    Returns:
        List of enabled GeoProviderConfig objects.
    """
    from app.services import settings as settings_service

    enabled = []

    for provider_name, config in PROVIDERS.items():
        # Check enabled flag
        enabled_val = settings_service.get_setting(db, config.setting_key_enabled)

        # Perplexity: enabled by default (backward compat)
        if provider_name == PROVIDER_PERPLEXITY:
            if enabled_val and enabled_val.lower() == "false":
                continue
        else:
            # OpenAI/Anthropic: disabled by default, must be explicitly "true"
            if not enabled_val or enabled_val.lower() != "true":
                continue

        # Check API key availability
        if config.setting_key_api:
            key = settings_service.get_setting(db, config.setting_key_api)
            if not key:
                logger.debug(
                    "GEO: Provider %s enabled but no API key in setting '%s'",
                    provider_name, config.setting_key_api,
                )
                continue
        else:
            # Key comes from env var — check via litellm's key resolution
            resolved = _resolve_api_key(config.model)
            if not resolved:
                logger.debug(
                    "GEO: Provider %s enabled but no API key resolved for model '%s'",
                    provider_name, config.model,
                )
                continue

        enabled.append(config)

    return enabled


def get_provider_api_key(db, config: GeoProviderConfig) -> str | None:
    """Resolve API key for a provider from system settings or env."""
    from app.services import settings as settings_service

    if config.setting_key_api:
        return settings_service.get_setting(db, config.setting_key_api) or None
    return _resolve_api_key(config.model)
