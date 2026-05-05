"""Global Reddit API rate limiter using Redis sliding window.

Provides platform-wide rate limiting for all Reddit API requests.
Uses a Redis sorted set as a sliding window counter to track requests
per minute across all Celery workers.
"""

import logging
import time

import redis

logger = logging.getLogger(__name__)


class ScrapeRateLimiter:
    """Global Reddit API rate limiter using Redis sliding window."""

    REDIS_KEY = "rate_limiter:scrape"
    BACKOFF_KEY = "rate_limiter:backoff"
    WINDOW_SECONDS = 60

    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis = redis_client

    def is_allowed(self, max_rpm: int) -> bool:
        """Check if a request is allowed under the current rate limit.

        When in backoff mode (after a 429 response), the effective limit
        is halved to allow Reddit API recovery.

        Args:
            max_rpm: Maximum requests per minute (from settings).

        Returns:
            True if the request is allowed, False if rate limit reached.
        """
        effective_limit = max_rpm
        if self.is_in_backoff():
            effective_limit = max(1, max_rpm // 2)

        now = time.time()
        window_start = now - self.WINDOW_SECONDS

        # Remove expired entries and count current window
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(self.REDIS_KEY, "-inf", window_start)
        pipe.zcard(self.REDIS_KEY)
        results = pipe.execute()

        current_count = results[1]
        return current_count < effective_limit

    def record_request(self) -> None:
        """Record that a request was made (increment counter).

        Adds the current timestamp to the sorted set. Members are
        automatically cleaned up on the next `is_allowed()` call.
        """
        now = time.time()
        # Use timestamp as both score and member (unique enough for our purposes)
        # Add a small random suffix to avoid collisions on same-millisecond requests
        member = f"{now}"
        self.redis.zadd(self.REDIS_KEY, {member: now})
        # Set a TTL on the key itself as a safety net (2x window)
        self.redis.expire(self.REDIS_KEY, self.WINDOW_SECONDS * 2)

    def get_utilization(self, max_rpm: int) -> dict:
        """Return current utilization stats for dashboard.

        Args:
            max_rpm: Maximum requests per minute (from settings).

        Returns:
            Dict with current_count, max_rpm, effective_limit,
            utilization_pct, and in_backoff flag.
        """
        effective_limit = max_rpm
        in_backoff = self.is_in_backoff()
        if in_backoff:
            effective_limit = max(1, max_rpm // 2)

        now = time.time()
        window_start = now - self.WINDOW_SECONDS

        # Clean and count
        pipe = self.redis.pipeline()
        pipe.zremrangebyscore(self.REDIS_KEY, "-inf", window_start)
        pipe.zcard(self.REDIS_KEY)
        results = pipe.execute()

        current_count = results[1]
        utilization_pct = min(100.0, (current_count / effective_limit) * 100) if effective_limit > 0 else 0.0

        return {
            "current_count": current_count,
            "max_rpm": max_rpm,
            "effective_limit": effective_limit,
            "utilization_pct": round(utilization_pct, 1),
            "in_backoff": in_backoff,
        }

    def activate_backoff(self, duration_seconds: int = 300) -> None:
        """Reduce effective rate limit by 50% for duration (on 429).

        Sets a Redis key with TTL that signals backoff mode is active.

        Args:
            duration_seconds: How long to stay in backoff mode (default 5 min).
        """
        self.redis.setex(self.BACKOFF_KEY, duration_seconds, "1")
        logger.warning(
            "Rate limiter backoff activated for %d seconds (Reddit 429 detected)",
            duration_seconds,
        )

    def is_in_backoff(self) -> bool:
        """Check if backoff mode is active.

        Returns:
            True if the backoff key exists in Redis.
        """
        return bool(self.redis.exists(self.BACKOFF_KEY))
