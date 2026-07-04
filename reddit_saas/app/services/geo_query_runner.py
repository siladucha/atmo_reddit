"""GEO Query Runner — orchestrates prompt execution across multiple providers.

Supports multi-provider monitoring:
- Perplexity Sonar (web search + citations)
- OpenAI ChatGPT Search (gpt-4o-search-preview)
- Anthropic Claude (web search)
- Gemini (Google Search grounding — fallback)

Each provider runs the same prompts independently. Results stored per-provider
for cross-engine visibility comparison.

Handles: LLM call -> brand detection -> citation parsing -> result storage.
Uses existing call_llm() for API calls and log_ai_usage() for cost tracking.
"""

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.logging_config import get_logger
from sqlalchemy.orm import Session

from app.models.client import Client
from app.models.geo_competitor import GeoCompetitor
from app.models.geo_execution import GeoExecutionBatch, GeoFrequencyMetric, GeoQueryResult
from app.models.geo_prompt import GeoPrompt
from app.services.ai import call_llm, log_ai_usage, MODEL_COSTS
from app.services.geo_brand_detection import detect_brand
from app.services.geo_citation_parser import parse_citations
from app.services.geo_providers import (
    PROVIDERS,
    PROVIDER_PERPLEXITY,
    GeoProviderConfig,
    execute_provider_query,
    get_enabled_providers,
    get_provider_api_key,
)
from app.services import settings as settings_service

logger = get_logger(__name__)

# Perplexity Sonar model string for LiteLLM
PERPLEXITY_MODEL = "perplexity/sonar"

# Gemini fallback model (with Google Search grounding)
# Using flash-lite for lower demand/cost; flash as secondary fallback
GEMINI_GEO_MODEL = "gemini/gemini-2.5-flash-lite"
GEMINI_GEO_FALLBACK = "gemini/gemini-2.5-flash"

# System prompt for GEO queries (kept for legacy Gemini fallback path)
GEO_SYSTEM_PROMPT = (
    "You are an AI assistant helping a user research solutions. "
    "Answer the question comprehensively, citing sources where possible. "
    "Include URLs and references to sources you find."
)

# Add model costs
MODEL_COSTS.setdefault(PERPLEXITY_MODEL, {"input": 1.00, "output": 1.00})
MODEL_COSTS.setdefault(GEMINI_GEO_MODEL, {"input": 0.15, "output": 0.60})

# Retry & circuit breaker settings for GEO batch
GEO_RETRY_ATTEMPTS = 2          # retries per query (total 3 attempts)
GEO_RETRY_DELAY_S = 10          # initial delay between retries
GEO_CIRCUIT_BREAKER_THRESHOLD = 3  # consecutive failures before stopping the batch
GEO_MAX_BATCH_DURATION_S = 1200  # hard timeout: abort batch after 20 min (multi-provider needs more time)


class GeoRateLimiter:
    """Per-provider rate limiter for GEO queries using Redis sliding window."""

    WINDOW_SECONDS = 60

    def __init__(self, redis_client, provider: str) -> None:
        self.redis = redis_client
        self.redis_key = f"geo_rate_limiter:{provider}"

    def is_allowed(self, max_rpm: int) -> bool:
        """Check if a request is allowed under the current rate limit."""
        now = time.time()
        window_start = now - self.WINDOW_SECONDS

        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(self.redis_key, "-inf", window_start)
        pipe.zcard(self.redis_key)
        results = pipe.execute()

        current_count = results[1]
        return current_count < max_rpm

    def record_request(self) -> None:
        """Record that a request was made."""
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex[:8]}"
        self.redis.zadd(self.redis_key, {member: now})
        self.redis.expire(self.redis_key, self.WINDOW_SECONDS * 2)

    def wait_for_slot(self, max_rpm: int, timeout: int = 120) -> bool:
        """Block until a rate limit slot is available or timeout."""
        start = time.time()
        while not self.is_allowed(max_rpm):
            if time.time() - start > timeout:
                return False
            time.sleep(2)
        return True


def _get_redis_client():
    """Get Redis client from app config."""
    import redis
    from app.config import get_settings
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


def _setting_exists_safe(key: str) -> bool:
    """Check if a config key exists and is non-empty (without raising)."""
    try:
        from app.config import get_config
        val = get_config(key)
        return bool(val and val.strip())
    except Exception:
        return False


def _get_perplexity_api_key(db: Session) -> str | None:
    """Get Perplexity API key from system settings."""
    return settings_service.get_setting(db, "geo_perplexity_api_key") or None


def _get_competitors_for_client(db: Session, client_id: uuid.UUID) -> list[dict]:
    """Load active competitors for a client."""
    comps = (
        db.query(GeoCompetitor)
        .filter(GeoCompetitor.client_id == client_id, GeoCompetitor.is_active == True)
        .all()
    )
    return [
        {"id": str(c.id), "name": c.competitor_name, "aliases": c.aliases or []}
        for c in comps
    ]


def run_geo_batch_for_client(
    db: Session,
    client: Client,
    triggered_by: str = "manual",
    user_id: uuid.UUID | None = None,
) -> GeoExecutionBatch | None:
    """Execute a full GEO monitoring batch for a single client.

    Multi-provider: runs the same prompts against ALL enabled providers
    (Perplexity, OpenAI, Anthropic). Each provider's results stored separately
    for cross-engine visibility comparison.

    Steps:
    1. Determine enabled providers
    2. Create GeoExecutionBatch
    3. For each provider × each prompt × N runs:
       a. Call provider via LiteLLM (with web_search_options where applicable)
       b. Run brand detection on response
       c. Run citation parser on response
       d. Store GeoQueryResult (with provider field)
       e. Log to AIUsageLog
    4. Compute frequency metrics per provider
    5. Update batch status

    Args:
        db: Database session.
        client: The Client object.
        triggered_by: What initiated this run (manual/scheduler/onboarding).
        user_id: The user who triggered this (for audit).

    Returns:
        The completed GeoExecutionBatch, or None if no prompts to run.
    """
    # Load active prompts
    prompts = (
        db.query(GeoPrompt)
        .filter(GeoPrompt.client_id == client.id, GeoPrompt.is_active == True)
        .all()
    )
    if not prompts:
        logger.info("GEO: No active prompts for client %s, skipping", client.client_name)
        return None

    # Get enabled providers
    enabled_providers = get_enabled_providers(db)

    # Legacy fallback: if no providers enabled, try Gemini
    if not enabled_providers:
        from app.config import get_config
        gemini_key = get_config("gemini_api_key") if _setting_exists_safe("gemini_api_key") else None
        if not gemini_key:
            logger.error("GEO: No providers enabled AND no Gemini API key — cannot run GEO")
            return None
        # Fall back to legacy single-provider Gemini mode
        logger.info("GEO: No providers enabled — using legacy Gemini fallback")
        return _run_legacy_gemini_batch(db, client, prompts, triggered_by, gemini_key)

    # Get settings
    runs_per_prompt = settings_service.get_setting_int(db, "geo_runs_per_prompt", default=3)

    # Load competitors
    competitors = _get_competitors_for_client(db, client.id)
    brand_name = client.brand_name

    # Calculate total queries (prompts × runs × providers)
    total_queries = len(prompts) * runs_per_prompt * len(enabled_providers)

    # Create batch
    batch = GeoExecutionBatch(
        client_id=client.id,
        triggered_by=triggered_by,
        status="running",
        total_queries=total_queries,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    provider_names = [p.display_name for p in enabled_providers]
    logger.info(
        "GEO: Starting batch %s for client %s — %d prompts × %d runs × %d providers (%s) = %d queries",
        batch.id, client.client_name, len(prompts), runs_per_prompt,
        len(enabled_providers), ", ".join(provider_names), total_queries,
    )

    # Set up rate limiters per provider
    rate_limiters: dict[str, GeoRateLimiter | None] = {}
    try:
        redis_client = _get_redis_client()
        for prov in enabled_providers:
            rate_limiters[prov.name] = GeoRateLimiter(redis_client, prov.name)
    except Exception as e:
        logger.warning("GEO: Could not connect to Redis for rate limiting: %s", e)
        for prov in enabled_providers:
            rate_limiters[prov.name] = None

    successful = 0
    failed = 0
    batch_start = time.time()

    # Per-provider circuit breakers (independent)
    provider_consecutive_failures: dict[str, int] = {p.name: 0 for p in enabled_providers}
    provider_skipped: set[str] = set()

    # Execute: iterate providers → prompts → runs
    for provider_config in enabled_providers:
        if provider_config.name in provider_skipped:
            continue

        provider_api_key = get_provider_api_key(db, provider_config)
        max_rpm = settings_service.get_setting_int(
            db, f"geo_rate_limit_{provider_config.name}_rpm", default=20
        )
        rate_limiter = rate_limiters.get(provider_config.name)

        logger.info("GEO: Running provider %s for batch %s", provider_config.display_name, batch.id)

        for prompt in prompts:
            # Circuit breaker per provider
            if provider_consecutive_failures[provider_config.name] >= GEO_CIRCUIT_BREAKER_THRESHOLD:
                logger.warning(
                    "GEO: Circuit breaker for %s — skipping remaining prompts",
                    provider_config.display_name,
                )
                provider_skipped.add(provider_config.name)
                # Count remaining as failed
                remaining_for_provider = (
                    (len(prompts) - prompts.index(prompt)) * runs_per_prompt
                )
                failed += remaining_for_provider
                break

            # Hard timeout check
            if time.time() - batch_start > GEO_MAX_BATCH_DURATION_S:
                logger.warning(
                    "GEO: Batch %s exceeded %ds timeout during %s. Aborting.",
                    batch.id, GEO_MAX_BATCH_DURATION_S, provider_config.display_name,
                )
                remaining_total = total_queries - successful - failed
                failed += remaining_total
                provider_skipped.update(p.name for p in enabled_providers)
                break

            for run_num in range(1, runs_per_prompt + 1):
                if provider_config.name in provider_skipped:
                    break

                # Rate limiting
                if rate_limiter:
                    if not rate_limiter.wait_for_slot(max_rpm, timeout=30):
                        logger.warning("GEO: Rate limit timeout for %s", provider_config.display_name)
                        _store_failed_result(
                            db, batch, prompt, run_num,
                            "rate_limit_timeout", provider=provider_config.name,
                        )
                        failed += 1
                        continue

                # Execute with retry
                query_result = None
                for attempt in range(1 + GEO_RETRY_ATTEMPTS):
                    try:
                        query_result = _execute_provider_query(
                            db=db,
                            batch=batch,
                            prompt=prompt,
                            client=client,
                            run_number=run_num,
                            brand_name=brand_name,
                            competitors=competitors,
                            provider_config=provider_config,
                            api_key=provider_api_key,
                            triggered_by=triggered_by,
                        )
                        if query_result:
                            break
                        if attempt < GEO_RETRY_ATTEMPTS:
                            delay = GEO_RETRY_DELAY_S * (2 ** attempt)
                            time.sleep(delay)
                    except Exception as e:
                        if attempt < GEO_RETRY_ATTEMPTS:
                            delay = GEO_RETRY_DELAY_S * (2 ** attempt)
                            logger.warning(
                                "GEO: %s attempt %d failed for prompt %s: %s. Retrying in %ds",
                                provider_config.display_name, attempt + 1, prompt.id, str(e)[:100], delay,
                            )
                            time.sleep(delay)
                        else:
                            logger.error(
                                "GEO: %s all attempts exhausted for prompt %s run %d: %s",
                                provider_config.display_name, prompt.id, run_num, e,
                            )
                            _store_failed_result(
                                db, batch, prompt, run_num, str(e)[:500],
                                provider=provider_config.name,
                            )

                if query_result:
                    successful += 1
                    provider_consecutive_failures[provider_config.name] = 0
                    if rate_limiter:
                        rate_limiter.record_request()
                else:
                    failed += 1
                    provider_consecutive_failures[provider_config.name] += 1

    # Compute frequency metrics (per provider)
    _compute_frequency_metrics(db, batch, prompts, enabled_providers)

    # Update batch status
    batch.successful_queries = successful
    batch.failed_queries = failed
    batch.completed_at = datetime.now(timezone.utc)
    if failed == 0:
        batch.status = "completed"
    elif successful == 0:
        batch.status = "failed"
    else:
        batch.status = "partial"
    db.commit()

    logger.info(
        "GEO: Batch %s completed — status=%s, success=%d, failed=%d, providers=%s",
        batch.id, batch.status, successful, failed,
        ", ".join(provider_names),
    )

    return batch


def _run_legacy_gemini_batch(
    db: Session,
    client: Client,
    prompts: list,
    triggered_by: str,
    api_key: str,
) -> GeoExecutionBatch | None:
    """Legacy fallback: run with Gemini + Google Search grounding (no multi-provider)."""
    runs_per_prompt = settings_service.get_setting_int(db, "geo_runs_per_prompt", default=3)
    competitors = _get_competitors_for_client(db, client.id)
    brand_name = client.brand_name
    total_queries = len(prompts) * runs_per_prompt

    batch = GeoExecutionBatch(
        client_id=client.id,
        triggered_by=triggered_by,
        status="running",
        total_queries=total_queries,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)

    successful = 0
    failed = 0
    batch_start = time.time()

    for prompt in prompts:
        if time.time() - batch_start > GEO_MAX_BATCH_DURATION_S:
            failed += (total_queries - successful - failed)
            break
        for run_num in range(1, runs_per_prompt + 1):
            try:
                result = _execute_single_query(
                    db=db, batch=batch, prompt=prompt, client=client,
                    run_number=run_num, brand_name=brand_name,
                    competitors=competitors, api_key=api_key,
                    triggered_by=triggered_by, use_gemini=True,
                )
                if result:
                    successful += 1
                else:
                    failed += 1
            except Exception:
                failed += 1

    _compute_frequency_metrics_legacy(db, batch, prompts)
    batch.successful_queries = successful
    batch.failed_queries = failed
    batch.completed_at = datetime.now(timezone.utc)
    batch.status = "completed" if failed == 0 else ("failed" if successful == 0 else "partial")
    db.commit()
    return batch


def _execute_single_query(
    db: Session,
    batch: GeoExecutionBatch,
    prompt: GeoPrompt,
    client: Client,
    run_number: int,
    brand_name: str,
    competitors: list[dict],
    api_key: str,
    triggered_by: str,
    use_gemini: bool = False,
) -> GeoQueryResult | None:
    """Execute a single LLM query and store the result.

    Uses Perplexity Sonar by default. If use_gemini=True, uses Gemini Flash
    with Google Search grounding tool as fallback provider.
    """
    messages = [
        {"role": "system", "content": GEO_SYSTEM_PROMPT},
        {"role": "user", "content": prompt.prompt_text},
    ]

    model = GEMINI_GEO_MODEL if use_gemini else PERPLEXITY_MODEL
    provider = "gemini" if use_gemini else "perplexity"

    start_ms = time.time()
    try:
        if use_gemini:
            # Gemini with Google Search grounding — pass as tool via litellm
            import litellm
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": 2048,
                "api_key": api_key,
                "tools": [{"google_search": {}}],
                "timeout": 60,
            }
            response = litellm.completion(**kwargs)
            duration_ms = int((time.time() - start_ms) * 1000)
            content_text = response.choices[0].message.content or ""
            usage = response.usage
            input_tokens = usage.prompt_tokens if usage else 0
            output_tokens = usage.completion_tokens if usage else 0
            from app.services.ai import _calculate_cost
            cost_usd = _calculate_cost(model, input_tokens, output_tokens)
            llm_result = {
                "content": content_text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": cost_usd,
                "duration_ms": duration_ms,
                "model": model,
            }
        else:
            llm_result = call_llm(
                messages=messages,
                model=model,
                temperature=0.7,
                max_tokens=2048,
            )
    except Exception as e:
        # If primary fails, try fallback (Perplexity → Gemini)
        if not use_gemini:
            logger.warning("GEO: Perplexity failed for prompt %s, trying Gemini fallback: %s", prompt.id, e)
            try:
                return _execute_single_query(
                    db=db, batch=batch, prompt=prompt, client=client,
                    run_number=run_number, brand_name=brand_name,
                    competitors=competitors, api_key=api_key,
                    triggered_by=triggered_by, use_gemini=True,
                )
            except Exception as fallback_err:
                logger.error("GEO: Gemini fallback also failed: %s", fallback_err)
                _store_failed_result(db, batch, prompt, run_number, f"both_failed: {e} / {fallback_err}")
                return None
        logger.warning("GEO: LLM call failed for prompt %s: %s", prompt.id, e)
        _store_failed_result(db, batch, prompt, run_number, str(e)[:500])
        return None

    duration_ms = int((time.time() - start_ms) * 1000)
    response_text = llm_result.get("content", "")

    # Run brand detection
    detection = detect_brand(response_text, brand_name, competitors)

    # Run citation parser
    citations = parse_citations(response_text)

    # Build competitor mentions data
    competitors_mentioned = [
        {"competitor_id": cm.competitor_id, "name": cm.name}
        for cm in detection.competitors_found
    ]

    # Build Reddit URLs data
    reddit_urls_data = [
        {"url": ru.url, "category": ru.category, "subreddit": ru.subreddit}
        for ru in citations.reddit_urls
    ]

    # All citation sources
    all_citations = [url for url in citations.other_urls]
    for ru in citations.reddit_urls:
        all_citations.append(ru.url)

    # Store result
    query_result = GeoQueryResult(
        prompt_id=prompt.id,
        client_id=client.id,
        execution_batch_id=batch.id,
        provider=provider,
        run_number=run_number,
        response_text=response_text,
        brand_mentioned=detection.brand_found,
        competitors_mentioned=competitors_mentioned if competitors_mentioned else None,
        reddit_urls_found=reddit_urls_data if reddit_urls_data else None,
        citation_sources=all_citations if all_citations else None,
        response_tokens=llm_result.get("output_tokens", 0),
        latency_ms=llm_result.get("duration_ms", duration_ms),
        status="success",
    )
    db.add(query_result)
    db.commit()

    # Log AI usage
    log_ai_usage(
        db=db,
        client_id=str(client.id),
        operation="geo_query",
        result=llm_result,
        triggered_by=f"geo_{triggered_by}",
    )

    return query_result


def _execute_provider_query(
    db: Session,
    batch: GeoExecutionBatch,
    prompt: GeoPrompt,
    client: Client,
    run_number: int,
    brand_name: str,
    competitors: list[dict],
    provider_config: GeoProviderConfig,
    api_key: str | None,
    triggered_by: str,
) -> GeoQueryResult | None:
    """Execute a single query via the multi-provider system.

    Uses geo_providers.execute_provider_query for the actual LLM call,
    then runs brand detection + citation parsing + stores result.
    """
    from app.services.geo_providers import execute_provider_query as exec_query

    result = exec_query(
        provider_config=provider_config,
        prompt_text=prompt.prompt_text,
        api_key=api_key,
        timeout=60,
    )

    if not result.success:
        _store_failed_result(
            db, batch, prompt, run_number,
            result.error or "unknown_error",
            provider=provider_config.name,
        )
        return None

    response_text = result.content

    # Run brand detection
    detection = detect_brand(response_text, brand_name, competitors)

    # Run citation parser
    citations = parse_citations(response_text)

    # Build competitor mentions data
    competitors_mentioned = [
        {"competitor_id": cm.competitor_id, "name": cm.name}
        for cm in detection.competitors_found
    ]

    # Build Reddit URLs data
    reddit_urls_data = [
        {"url": ru.url, "category": ru.category, "subreddit": ru.subreddit}
        for ru in citations.reddit_urls
    ]

    # All citation sources
    all_citations = list(citations.other_urls)
    for ru in citations.reddit_urls:
        all_citations.append(ru.url)

    # Store result
    query_result = GeoQueryResult(
        prompt_id=prompt.id,
        client_id=client.id,
        execution_batch_id=batch.id,
        provider=provider_config.name,
        run_number=run_number,
        response_text=response_text,
        brand_mentioned=detection.brand_found,
        competitors_mentioned=competitors_mentioned if competitors_mentioned else None,
        reddit_urls_found=reddit_urls_data if reddit_urls_data else None,
        citation_sources=all_citations if all_citations else None,
        response_tokens=result.output_tokens,
        latency_ms=result.duration_ms,
        status="success",
    )
    db.add(query_result)
    db.commit()

    # Log AI usage
    llm_result = {
        "content": result.content,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
        "duration_ms": result.duration_ms,
        "model": result.model,
    }
    log_ai_usage(
        db=db,
        client_id=str(client.id),
        operation=f"geo_query_{provider_config.name}",
        result=llm_result,
        triggered_by=f"geo_{triggered_by}",
    )

    return query_result


def _store_failed_result(
    db: Session,
    batch: GeoExecutionBatch,
    prompt: GeoPrompt,
    run_number: int,
    error_msg: str,
    provider: str = "perplexity",
) -> None:
    """Store a failed query result."""
    result = GeoQueryResult(
        prompt_id=prompt.id,
        client_id=batch.client_id,
        execution_batch_id=batch.id,
        provider=provider,
        run_number=run_number,
        response_text=f"ERROR: {error_msg}",
        brand_mentioned=False,
        status="failed",
    )
    db.add(result)
    db.commit()


def _compute_frequency_metrics(
    db: Session,
    batch: GeoExecutionBatch,
    prompts: list[GeoPrompt],
    providers: list[GeoProviderConfig] | None = None,
) -> None:
    """Compute and store frequency metrics for each prompt × provider in the batch.

    Creates one GeoFrequencyMetric per (prompt, provider) pair.
    """
    # Determine unique providers from actual results if not passed
    if providers:
        provider_names = [p.name for p in providers]
    else:
        # Fallback: discover from results
        provider_rows = (
            db.query(GeoQueryResult.provider)
            .filter(
                GeoQueryResult.execution_batch_id == batch.id,
                GeoQueryResult.status == "success",
            )
            .distinct()
            .all()
        )
        provider_names = [r[0] for r in provider_rows]

    for prompt in prompts:
        for provider_name in provider_names:
            # Get successful results for this prompt+provider in this batch
            results = (
                db.query(GeoQueryResult)
                .filter(
                    GeoQueryResult.execution_batch_id == batch.id,
                    GeoQueryResult.prompt_id == prompt.id,
                    GeoQueryResult.provider == provider_name,
                    GeoQueryResult.status == "success",
                )
                .all()
            )

            if not results:
                continue

            total_runs = len(results)
            brand_appearances = sum(1 for r in results if r.brand_mentioned)
            appearance_rate = (brand_appearances / total_runs) * 100 if total_runs > 0 else 0

            # Aggregate competitor appearances
            competitor_counts: dict[str, int] = {}
            reddit_citation_count = 0
            for r in results:
                if r.competitors_mentioned:
                    for comp in r.competitors_mentioned:
                        comp_id = comp.get("competitor_id", "unknown")
                        competitor_counts[comp_id] = competitor_counts.get(comp_id, 0) + 1
                if r.reddit_urls_found:
                    reddit_citation_count += len(r.reddit_urls_found)

            metric = GeoFrequencyMetric(
                execution_batch_id=batch.id,
                prompt_id=prompt.id,
                client_id=batch.client_id,
                provider=provider_name,
                total_runs=total_runs,
                brand_appearances=brand_appearances,
                brand_appearance_rate=Decimal(str(round(appearance_rate, 2))),
                competitor_appearances=competitor_counts if competitor_counts else None,
                reddit_citation_count=reddit_citation_count,
            )
            db.add(metric)

    db.commit()


def _compute_frequency_metrics_legacy(
    db: Session,
    batch: GeoExecutionBatch,
    prompts: list[GeoPrompt],
) -> None:
    """Legacy metrics computation (single provider — backward compat)."""
    _compute_frequency_metrics(db, batch, prompts, providers=None)
