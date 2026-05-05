"""Per-subreddit distributed lock using Redis SETNX.

Prevents concurrent scraping of the same subreddit by multiple workers.
Uses a Lua script for atomic release to ensure only the lock owner can
release it.
"""

import logging
import socket
import time

import redis

logger = logging.getLogger(__name__)

# Lua script for atomic lock release — only releases if value matches
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


class ScrapeDistributedLock:
    """Per-subreddit distributed lock using Redis SETNX."""

    KEY_PREFIX = "scrape_lock:"
    DEFAULT_TTL = 300  # 5 minutes

    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis = redis_client
        self._hostname = socket.gethostname()
        # Register the Lua script
        self._release_script = self.redis.register_script(_RELEASE_SCRIPT)
        # Track which locks this instance owns (for atomic release)
        self._owned_values: dict[str, str] = {}

    def _make_key(self, subreddit_name: str) -> str:
        """Build the Redis key for a subreddit lock."""
        return f"{self.KEY_PREFIX}{subreddit_name}"

    def _make_value(self) -> str:
        """Generate a unique value for lock ownership tracking."""
        return f"{self._hostname}:{time.time()}"

    def acquire(self, subreddit_name: str, ttl: int = DEFAULT_TTL) -> bool:
        """Try to acquire lock for a subreddit.

        Args:
            subreddit_name: The subreddit to lock.
            ttl: Lock TTL in seconds (default 300s / 5 min).

        Returns:
            True if lock was acquired, False if already held.
        """
        key = self._make_key(subreddit_name)
        value = self._make_value()

        # SET key value NX EX ttl — atomic set-if-not-exists with expiry
        acquired = self.redis.set(key, value, nx=True, ex=ttl)

        if acquired:
            self._owned_values[subreddit_name] = value
            logger.debug("Lock acquired for r/%s (TTL=%ds)", subreddit_name, ttl)
            return True

        logger.debug("Lock NOT acquired for r/%s (already held)", subreddit_name)
        return False

    def release(self, subreddit_name: str) -> None:
        """Release lock for a subreddit.

        Uses a Lua script to ensure only the owner can release the lock.
        If the lock was already released or expired, this is a no-op.

        Args:
            subreddit_name: The subreddit to unlock.
        """
        key = self._make_key(subreddit_name)
        value = self._owned_values.pop(subreddit_name, None)

        if value is None:
            # We don't own this lock — just try to delete it (fallback)
            logger.warning(
                "Releasing lock for r/%s without ownership tracking (fallback DEL)",
                subreddit_name,
            )
            self.redis.delete(key)
            return

        # Atomic release: only delete if value matches
        result = self._release_script(keys=[key], args=[value])
        if result:
            logger.debug("Lock released for r/%s", subreddit_name)
        else:
            logger.warning(
                "Lock release failed for r/%s (value mismatch — lock may have expired)",
                subreddit_name,
            )

    def is_locked(self, subreddit_name: str) -> bool:
        """Check if a subreddit is currently locked.

        Args:
            subreddit_name: The subreddit to check.

        Returns:
            True if the lock key exists in Redis.
        """
        key = self._make_key(subreddit_name)
        return bool(self.redis.exists(key))

    def get_all_locks(self) -> list[str]:
        """Return list of currently locked subreddit names.

        Uses Redis SCAN to find all keys with the lock prefix.
        Useful for the admin dashboard to show which subreddits
        are currently being processed.

        Returns:
            List of subreddit names that have active locks.
        """
        pattern = f"{self.KEY_PREFIX}*"
        prefix_len = len(self.KEY_PREFIX)
        locked_subreddits: list[str] = []

        cursor = 0
        while True:
            cursor, keys = self.redis.scan(cursor=cursor, match=pattern, count=100)
            for key in keys:
                # key is bytes or str depending on decode_responses
                key_str = key.decode() if isinstance(key, bytes) else key
                subreddit_name = key_str[prefix_len:]
                locked_subreddits.append(subreddit_name)
            if cursor == 0:
                break

        return locked_subreddits
