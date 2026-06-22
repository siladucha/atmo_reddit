"""ExternalRequestScheduler — centralized rate limiting + concurrency control for outbound calls.

All external API calls (Reddit PRAW, AI/LLM, scraping) should go through this scheduler
to enforce per-service rate limits, global concurrency caps, and priority ordering.

Architecture:
- Rate limiter: Redis sorted set sliding window (extends ScrapeRateLimiter pattern)
- Concurrency cap: Redis INCR/DECR semaphore
- Priority: Numeric levels (lower = higher priority)
- Retry: Handled by calling Celery task (scheduler only manages slot acquisition)

Usage in Celery tasks:
    scheduler = get_external_scheduler()
    if not scheduler.wait_for_slot("reddit", priority="user_facing_trial"):
        raise self.retry(countdown=30)
    try:
        result = fetch_reddit_profile(username)
    finally:
        scheduler.release("reddit")
"""

import time
from datetime import datetime, timezone

import redis

from app.logging_config import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Priority levels (lower number = higher priority)
# ---------------------------------------------------------------------------

PRIORITY_USER_FACING_PAID = 0
PRIORITY_USER_FACING_TRIAL = 1
PRIORITY_BACKGROUND_PAID = 2
PRIORITY_BACKGROUND_TRIAL = 3

PRIORITY_LEVELS = {
    "user_facing_paid": PRIORITY_USER_FACING_PAID,
    "user_facing_trial": PRIORITY_USER_FACING_TRIAL,
    "background_paid": PRIORITY_BACKGROUND_PAID,
    "background_trial": PRIORITY_BACKGROUND_TRIAL,
}


# ---------------------------------------------------------------------------
# Service configurations
# ---------------------------------------------------------------------------

SERVICE_CONFIGS = {
    "reddit": {"max_rpm": 30, "timeout_seconds": 30, "window_seconds": 60},
    "ai_llm": {"max_rpm": 60, "timeout_seconds": 60, "window_seconds": 60},
}


# ---------------------------------------------------------------------------
# Redis key prefixes
# ---------------------------------------------------------------------------

_RATE_KEY_PREFIX = "ext_scheduler:rate:"
_CONCURRENCY_KEY = "ext_scheduler:active_count"
_BACKOFF_KEY_PREFIX = "ext_scheduler:backoff:"
_LOG_KEY_PREFIX = "ext_scheduler:log:"


class ExternalRequestScheduler:
    """Centralized scheduler for all outbound external API calls.

    Provides:
    1. Per-service rate limiting (Redis sorted set sliding window)
    2. Global concurrency cap (Redis atomic counter)
    3. Priority-aware slot acquisition
    4. Request logging for observability
    """

    def __init__(self, redis_client: redis.Redis, global_concurrency_cap: int = 10):
        """Initialize scheduler.

        Args:
            redis_client: Redis connection for coordination.
            global_concurrency_cap: Maximum concurrent outbound requests across all services.
        """
        self.redis = redis_client
        self.global_concurrency_cap = global_concurrency_cap

    # -----------------------------------------------------------------------
    # Rate limiting (per-service, sliding window)
    # -----------------------------------------------------------------------

    def _rate_key(self, service: str) -> str:
        return f"{_RATE_KEY_PREFIX}{service}"

    def _is_rate_allowed(self, service: str) -> bool:
        """Check if service rate limit allows another request.
        
        On Redis connection failure, returns True (fail-open to avoid blocking callers).
        """
        try:
            config = SERVICE_CONFIGS.get(service, {"max_rpm": 30, "window_seconds": 60})
            max_rpm = config["max_rpm"]
            window = config["window_seconds"]

            # Check backoff mode (halve limit on 429)
            backoff_key = f"{_BACKOFF_KEY_PREFIX}{service}"
            if self.redis.exists(backoff_key):
                max_rpm = max(1, max_rpm // 2)

            now = time.time()
            key = self._rate_key(service)
            window_start = now - window

            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zcard(key)
            results = pipe.execute()

            current_count = results[1]
            return current_count < max_rpm
        except (redis.ConnectionError, redis.TimeoutError, redis.RedisError) as e:
            logger.warning("EXT_SCHEDULER | service=%s | redis_error=%s | action=fail_open", service, str(e)[:100])
            return True  # Fail-open: allow request if Redis unavailable

    def _record_rate(self, service: str) -> None:
        """Record a request in the rate limiter window."""
        now = time.time()
        key = self._rate_key(service)
        config = SERVICE_CONFIGS.get(service, {"window_seconds": 60})
        window = config["window_seconds"]

        self.redis.zadd(key, {str(now): now})
        self.redis.expire(key, window * 2)

    # -----------------------------------------------------------------------
    # Concurrency cap (global semaphore)
    # -----------------------------------------------------------------------

    def _get_active_count(self) -> int:
        """Get current number of active outbound requests."""
        try:
            val = self.redis.get(_CONCURRENCY_KEY)
            return int(val) if val else 0
        except (redis.ConnectionError, redis.TimeoutError, redis.RedisError):
            return 0  # Assume empty on Redis failure

    def _increment_active(self) -> int:
        """Atomically increment active count. Returns new value.
        
        Sets a TTL of 120s as safety net: if all workers crash without
        releasing, the counter auto-resets after 2 minutes.
        """
        val = self.redis.incr(_CONCURRENCY_KEY)
        # Safety TTL: counter expires if no activity for 120s
        # Each acquire/release refreshes the TTL
        self.redis.expire(_CONCURRENCY_KEY, 120)
        return val

    def _decrement_active(self) -> int:
        """Atomically decrement active count. Returns new value (min 0)."""
        val = self.redis.decr(_CONCURRENCY_KEY)
        # Safety: never go below 0 (can happen if release called without acquire)
        if val < 0:
            self.redis.set(_CONCURRENCY_KEY, 0)
            return 0
        # Refresh TTL on activity
        self.redis.expire(_CONCURRENCY_KEY, 120)
        return val

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def acquire(self, service: str, priority: str = "background_trial") -> bool:
        """Try to acquire a slot for an external call.

        Checks both per-service rate limit and global concurrency cap.
        Uses atomic increment-then-check to avoid TOCTOU race conditions.

        Args:
            service: Service name ("reddit" or "ai_llm")
            priority: Priority level string (for logging; slot acquisition is FIFO)

        Returns:
            True if slot acquired (caller should proceed with the call),
            False if not available (caller should retry later).
        """
        # Check per-service rate limit first (cheap check)
        if not self._is_rate_allowed(service):
            logger.debug(
                "EXT_SCHEDULER | service=%s | priority=%s | action=rate_limited",
                service, priority,
            )
            return False

        # Atomic: increment first, then check if over cap
        # This prevents TOCTOU race between check and increment
        new_count = self._increment_active()
        if new_count > self.global_concurrency_cap:
            # Over cap — release immediately and deny
            self._decrement_active()
            logger.debug(
                "EXT_SCHEDULER | service=%s | priority=%s | action=concurrency_full | active=%d | cap=%d",
                service, priority, new_count - 1, self.global_concurrency_cap,
            )
            return False

        # Slot acquired — record rate
        self._record_rate(service)

        logger.debug(
            "EXT_SCHEDULER | service=%s | priority=%s | action=acquired | active=%d",
            service, priority, new_count,
        )
        return True

    def release(self, service: str) -> None:
        """Release a slot after an external call completes.

        Must be called in a finally block after acquire() returns True.

        Args:
            service: Service name (for logging)
        """
        new_count = self._decrement_active()
        logger.debug(
            "EXT_SCHEDULER | service=%s | action=released | active=%d",
            service, new_count,
        )

    def wait_for_slot(
        self,
        service: str,
        priority: str = "background_trial",
        max_wait: int = 30,
    ) -> bool:
        """Block until a slot is available or timeout.

        Polls every 1 second for availability.

        Args:
            service: Service name ("reddit" or "ai_llm")
            priority: Priority level string
            max_wait: Maximum seconds to wait before giving up

        Returns:
            True if slot was acquired, False if timed out.
        """
        start = time.time()
        waited = 0

        while waited < max_wait:
            if self.acquire(service, priority):
                if waited > 0:
                    logger.info(
                        "EXT_SCHEDULER | service=%s | priority=%s | action=acquired_after_wait | waited_seconds=%d",
                        service, priority, waited,
                    )
                return True
            time.sleep(1)
            waited = int(time.time() - start)

        logger.warning(
            "EXT_SCHEDULER | service=%s | priority=%s | action=wait_timeout | max_wait=%d",
            service, priority, max_wait,
        )
        return False

    def activate_backoff(self, service: str, duration_seconds: int = 300) -> None:
        """Halve effective rate limit for a service (on 429 response).

        Args:
            service: Service that received rate limit error
            duration_seconds: How long to stay in backoff mode
        """
        backoff_key = f"{_BACKOFF_KEY_PREFIX}{service}"
        self.redis.setex(backoff_key, duration_seconds, "1")
        logger.warning(
            "EXT_SCHEDULER | service=%s | action=backoff_activated | duration=%ds",
            service, duration_seconds,
        )

    def get_stats(self) -> dict:
        """Get current scheduler statistics for dashboard/monitoring.

        Returns:
            Dict with active_count, per-service utilization, backoff status.
        """
        active = self._get_active_count()
        stats = {
            "active_count": active,
            "global_cap": self.global_concurrency_cap,
            "utilization_pct": round((active / self.global_concurrency_cap) * 100, 1) if self.global_concurrency_cap > 0 else 0,
            "services": {},
        }

        for service, config in SERVICE_CONFIGS.items():
            now = time.time()
            key = self._rate_key(service)
            window_start = now - config["window_seconds"]

            pipe = self.redis.pipeline()
            pipe.zremrangebyscore(key, "-inf", window_start)
            pipe.zcard(key)
            results = pipe.execute()

            current_count = results[1]
            backoff_key = f"{_BACKOFF_KEY_PREFIX}{service}"
            in_backoff = bool(self.redis.exists(backoff_key))
            effective_limit = max(1, config["max_rpm"] // 2) if in_backoff else config["max_rpm"]

            stats["services"][service] = {
                "current_rpm": current_count,
                "max_rpm": config["max_rpm"],
                "effective_limit": effective_limit,
                "in_backoff": in_backoff,
                "utilization_pct": round((current_count / effective_limit) * 100, 1) if effective_limit > 0 else 0,
            }

        return stats

    def log_request(
        self,
        service: str,
        duration_ms: int,
        success: bool,
        priority: str = "background_trial",
        retry_count: int = 0,
        details: str = "",
    ) -> None:
        """Log an outbound request for observability.

        Args:
            service: Service name
            duration_ms: Call duration in milliseconds
            success: Whether the call succeeded
            priority: Priority level used
            retry_count: Number of retries before this attempt
            details: Optional detail string (error message on failure)
        """
        logger.info(
            "EXT_REQUEST | service=%s | duration_ms=%d | success=%s | priority=%s | retries=%d | details=%s",
            service, duration_ms, success, priority, retry_count, details[:200] if details else "",
        )


# ---------------------------------------------------------------------------
# Module-level singleton (lazy init)
# ---------------------------------------------------------------------------

_scheduler_instance: ExternalRequestScheduler | None = None


def get_external_scheduler() -> ExternalRequestScheduler:
    """Get or create the global ExternalRequestScheduler instance.

    Uses Redis from app settings. Falls back to a permissive no-op if Redis
    is unavailable (logs warning, allows all calls).
    """
    global _scheduler_instance
    if _scheduler_instance is not None:
        return _scheduler_instance

    try:
        from app.config import get_settings
        settings = get_settings()
        redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

        # Try to read global cap from DB settings
        cap = 10  # default
        try:
            from app.database import SessionLocal
            from app.services.settings import get_setting_int
            db = SessionLocal()
            try:
                cap = get_setting_int(db, "external_scheduler_concurrency_cap", 10)
            finally:
                db.close()
        except Exception:
            pass

        _scheduler_instance = ExternalRequestScheduler(redis_client, global_concurrency_cap=cap)
        return _scheduler_instance
    except Exception as e:
        logger.warning("Failed to initialize ExternalRequestScheduler: %s — using permissive fallback", e)
        # Return a no-op scheduler that allows everything
        return _PermissiveScheduler()


class _PermissiveScheduler(ExternalRequestScheduler):
    """Fallback scheduler that allows all requests (used when Redis unavailable)."""

    def __init__(self):
        # Don't call super().__init__ — no redis client
        self.global_concurrency_cap = 999

    def acquire(self, service: str, priority: str = "background_trial") -> bool:
        return True

    def release(self, service: str) -> None:
        pass

    def wait_for_slot(self, service: str, priority: str = "background_trial", max_wait: int = 30) -> bool:
        return True

    def activate_backoff(self, service: str, duration_seconds: int = 300) -> None:
        pass

    def get_stats(self) -> dict:
        return {"active_count": 0, "global_cap": 999, "utilization_pct": 0, "services": {}, "fallback": True}

    def log_request(self, service: str, duration_ms: int, success: bool, **kwargs) -> None:
        logger.info("EXT_REQUEST (fallback) | service=%s | duration_ms=%d | success=%s", service, duration_ms, success)
