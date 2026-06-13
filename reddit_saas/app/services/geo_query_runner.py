"""GEO Query Runner — orchestrates prompt execution against Perplexity Sonar.

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
from app.services import settings as settings_service

logger = get_logger(__name__)

# Perplexity Sonar model string for LiteLLM
PERPLEXITY_MODEL = "perplexity/sonar"

# System prompt for GEO queries
GEO_SYSTEM_PROMPT = (
    "You are an AI assistant helping a user research solutions. "
    "Answer the question comprehensively, citing sources where possible."
)

# Add Perplexity model cost (approximate — Perplexity Sonar pricing)
MODEL_COSTS.setdefault(PERPLEXITY_MODEL, {"input": 1.00, "output": 1.00})


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

    Steps:
    1. Create GeoExecutionBatch
    2. For each active prompt x N runs:
       a. Call Perplexity Sonar via LiteLLM
       b. Run brand detection on response
       c. Run citation parser on response
       d. Store GeoQueryResult
       e. Log to AIUsageLog
    3. Compute frequency metrics
    4. Update batch status

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

    # Get settings
    runs_per_prompt = settings_service.get_setting_int(db, "geo_runs_per_prompt", default=3)
    max_rpm = settings_service.get_setting_int(db, "geo_rate_limit_perplexity_rpm", default=20)
    perplexity_enabled = settings_service.get_setting(db, "geo_provider_perplexity_enabled")
    if perplexity_enabled and perplexity_enabled.lower() == "false":
        logger.info("GEO: Perplexity provider disabled, skipping")
        return None

    # Get API key
    api_key = _get_perplexity_api_key(db)
    if not api_key:
        logger.error("GEO: No Perplexity API key configured (geo_perplexity_api_key)")
        return None

    # Load competitors
    competitors = _get_competitors_for_client(db, client.id)
    brand_name = client.brand_name

    # Calculate total queries
    total_queries = len(prompts) * runs_per_prompt

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

    logger.info(
        "GEO: Starting batch %s for client %s — %d prompts x %d runs = %d queries",
        batch.id, client.client_name, len(prompts), runs_per_prompt, total_queries,
    )

    # Set up rate limiter
    try:
        redis_client = _get_redis_client()
        rate_limiter = GeoRateLimiter(redis_client, "perplexity")
    except Exception as e:
        logger.warning("GEO: Could not connect to Redis for rate limiting: %s", e)
        rate_limiter = None

    successful = 0
    failed = 0

    for prompt in prompts:
        for run_num in range(1, runs_per_prompt + 1):
            # Rate limiting
            if rate_limiter:
                if not rate_limiter.wait_for_slot(max_rpm, timeout=120):
                    logger.warning("GEO: Rate limit timeout for batch %s", batch.id)
                    # Store failed result
                    _store_failed_result(db, batch, prompt, run_num, "rate_limit_timeout")
                    failed += 1
                    continue

            # Execute query
            try:
                result = _execute_single_query(
                    db=db,
                    batch=batch,
                    prompt=prompt,
                    client=client,
                    run_number=run_num,
                    brand_name=brand_name,
                    competitors=competitors,
                    api_key=api_key,
                    triggered_by=triggered_by,
                )
                if result:
                    successful += 1
                else:
                    failed += 1

                # Record rate limit usage
                if rate_limiter:
                    rate_limiter.record_request()

            except Exception as e:
                logger.error("GEO: Query failed for prompt %s run %d: %s", prompt.id, run_num, e)
                _store_failed_result(db, batch, prompt, run_num, str(e)[:500])
                failed += 1

    # Compute frequency metrics
    _compute_frequency_metrics(db, batch, prompts)

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
        "GEO: Batch %s completed — status=%s, success=%d, failed=%d",
        batch.id, batch.status, successful, failed,
    )

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
) -> GeoQueryResult | None:
    """Execute a single LLM query and store the result."""
    messages = [
        {"role": "system", "content": GEO_SYSTEM_PROMPT},
        {"role": "user", "content": prompt.prompt_text},
    ]

    start_ms = time.time()
    try:
        llm_result = call_llm(
            messages=messages,
            model=PERPLEXITY_MODEL,
            temperature=0.7,
            max_tokens=2048,
        )
    except Exception as e:
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
        provider="perplexity",
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


def _store_failed_result(
    db: Session,
    batch: GeoExecutionBatch,
    prompt: GeoPrompt,
    run_number: int,
    error_msg: str,
) -> None:
    """Store a failed query result."""
    result = GeoQueryResult(
        prompt_id=prompt.id,
        client_id=batch.client_id,
        execution_batch_id=batch.id,
        provider="perplexity",
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
) -> None:
    """Compute and store frequency metrics for each prompt in the batch."""
    for prompt in prompts:
        # Get successful results for this prompt in this batch
        results = (
            db.query(GeoQueryResult)
            .filter(
                GeoQueryResult.execution_batch_id == batch.id,
                GeoQueryResult.prompt_id == prompt.id,
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
            provider="perplexity",
            total_runs=total_runs,
            brand_appearances=brand_appearances,
            brand_appearance_rate=Decimal(str(round(appearance_rate, 2))),
            competitor_appearances=competitor_counts if competitor_counts else None,
            reddit_citation_count=reddit_citation_count,
        )
        db.add(metric)

    db.commit()
