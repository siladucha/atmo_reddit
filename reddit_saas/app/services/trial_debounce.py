"""Trial Score Debounce Manager.

Redis-based debouncing to prevent score recomputation storms.
Key pattern: trial:debounce:{client_id} with 60s TTL.

Behavior:
- First signal in window: SET key, dispatch recompute task → returns True
- Subsequent signals in 60s window: skip (key exists) → returns False
- After TTL expires: next signal triggers new recompute
- If Redis unavailable: always allow recompute (fallback)
"""

import logging
from uuid import UUID

import redis

logger = logging.getLogger(__name__)

DEBOUNCE_TTL = 60  # seconds
LOCK_TTL = 5  # seconds for recompute lock


class DebounceManager:
    """Redis-based debounce for trial score recomputation."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def should_recompute(self, client_id: UUID) -> bool:
        """Check if scoring should be triggered for this client.

        Returns True if no debounce key exists (first signal in window).
        Returns False if key exists (already pending recompute).
        Falls back to True if Redis is unavailable.
        """
        key = f"trial:debounce:{client_id}"
        try:
            # SET NX returns True if key was set (no existing key)
            result = self.redis.set(key, "1", nx=True, ex=DEBOUNCE_TTL)
            return bool(result)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.warning("Redis unavailable for debounce, allowing recompute: %s", e)
            return True

    def clear(self, client_id: UUID) -> None:
        """Clear debounce after recomputation completes.

        Called at the end of recompute_trial_score task.
        """
        key = f"trial:debounce:{client_id}"
        try:
            self.redis.delete(key)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.warning("Redis unavailable, cannot clear debounce key: %s", e)

    def acquire_recompute_lock(self, client_id: UUID) -> bool:
        """Acquire distributed lock to prevent concurrent recomputes.

        Key pattern: trial:lock:score:{client_id} with 5s TTL.
        Returns True if lock acquired, False if another worker holds it.
        """
        key = f"trial:lock:score:{client_id}"
        try:
            result = self.redis.set(key, "1", nx=True, ex=LOCK_TTL)
            return bool(result)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.warning("Redis unavailable for lock, allowing recompute: %s", e)
            return True

    def release_recompute_lock(self, client_id: UUID) -> None:
        """Release the distributed recompute lock."""
        key = f"trial:lock:score:{client_id}"
        try:
            self.redis.delete(key)
        except (redis.ConnectionError, redis.TimeoutError):
            pass  # Lock will expire via TTL anyway
