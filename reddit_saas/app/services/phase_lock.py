"""Per-avatar distributed lock for phase transitions using Redis SETNX.

Prevents concurrent phase transitions for the same avatar (e.g., daily batch
and on-demand check both trying to promote simultaneously). Uses a Lua script
for atomic release to ensure only the lock owner can release it.

Follows the same pattern as ScrapeDistributedLock in distributed_lock.py.
"""

from app.logging_config import get_logger
import time
from uuid import uuid4

import redis

logger = get_logger(__name__)

# Lua script for atomic lock release — only releases if value matches
_RELEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


class PhaseTransitionLock:
    """Per-avatar distributed lock for phase transitions."""

    KEY_PREFIX = "phase_lock:"
    DEFAULT_TTL = 30  # 30 seconds — transitions are fast

    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis = redis_client
        # Register the Lua script
        self._release_script = self.redis.register_script(_RELEASE_SCRIPT)
        # Track which locks this instance owns (for atomic release)
        self._owned_values: dict[str, str] = {}

    def _make_key(self, avatar_id: str) -> str:
        """Build the Redis key for an avatar transition lock."""
        return f"{self.KEY_PREFIX}{avatar_id}"

    def _make_value(self) -> str:
        """Generate a unique value for lock ownership tracking."""
        return str(uuid4())

    def acquire(self, avatar_id: str, timeout: int = 5) -> bool:
        """Try to acquire lock for an avatar with polling timeout.

        Polls every 0.5s up to `timeout` seconds.

        Args:
            avatar_id: The avatar ID to lock.
            timeout: Maximum seconds to wait for lock acquisition (default 5s).

        Returns:
            True if lock was acquired, False if timeout exceeded.
        """
        key = self._make_key(avatar_id)
        value = self._make_value()
        deadline = time.monotonic() + timeout

        while True:
            # SET key value NX EX ttl — atomic set-if-not-exists with expiry
            acquired = self.redis.set(key, value, nx=True, ex=self.DEFAULT_TTL)

            if acquired:
                self._owned_values[avatar_id] = value
                logger.debug(
                    "Phase lock acquired for avatar %s (TTL=%ds)",
                    avatar_id,
                    self.DEFAULT_TTL,
                )
                return True

            # Check if we've exceeded the timeout
            if time.monotonic() >= deadline:
                logger.warning(
                    "Phase lock timeout for avatar %s after %ds",
                    avatar_id,
                    timeout,
                )
                return False

            # Poll again after 0.5s
            time.sleep(0.5)

    def release(self, avatar_id: str) -> None:
        """Release lock for an avatar.

        Uses a Lua script to ensure only the owner can release the lock.
        If the lock was already released or expired, this is a no-op.

        Args:
            avatar_id: The avatar ID to unlock.
        """
        key = self._make_key(avatar_id)
        value = self._owned_values.pop(avatar_id, None)

        if value is None:
            logger.warning(
                "Releasing phase lock for avatar %s without ownership tracking",
                avatar_id,
            )
            return

        # Atomic release: only delete if value matches
        result = self._release_script(keys=[key], args=[value])
        if result:
            logger.debug("Phase lock released for avatar %s", avatar_id)
        else:
            logger.warning(
                "Phase lock release failed for avatar %s "
                "(value mismatch — lock may have expired)",
                avatar_id,
            )
