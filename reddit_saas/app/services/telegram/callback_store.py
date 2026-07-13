"""Redis-based Callback_ID mapping for Telegram inline keyboard buttons.

Telegram limits callback_data to 64 bytes. We use short Redis-mapped IDs
(16 chars) that resolve to draft_id + action + user_id.

Keys: tg:cb:{callback_id} → JSON payload (24h TTL)
"""

import json
import secrets
from typing import Any

import redis

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_KEY_PREFIX = "tg:cb:"
_TTL_SECONDS = 86400  # 24 hours


class CallbackStore:
    """Redis-based short ID mapping for Telegram callback_data (64-byte limit)."""

    def __init__(self):
        self._redis = redis.from_url(get_settings().redis_url, decode_responses=True)

    def create(self, draft_id: str, action: str, user_id: str) -> str:
        """Generate a short callback_id, store mapping in Redis with 24h TTL.

        Args:
            draft_id: UUID of the CommentDraft or PostDraft
            action: One of "approve", "skip", "edit", "approve_all"
            user_id: UUID of the User performing the action

        Returns:
            A 16-char URL-safe callback_id that fits within 64-byte limit.
        """
        callback_id = secrets.token_urlsafe(12)  # 16 chars
        payload = json.dumps({
            "draft_id": draft_id,
            "action": action,
            "user_id": user_id,
        })
        self._redis.setex(f"{_KEY_PREFIX}{callback_id}", _TTL_SECONDS, payload)
        return callback_id

    def create_bulk(self, avatar_username: str, action: str, user_id: str) -> str:
        """Generate callback_id for bulk operations (approve_all per avatar).

        Args:
            avatar_username: Reddit username of the avatar
            action: "approve_all"
            user_id: UUID of the User

        Returns:
            A 16-char URL-safe callback_id.
        """
        callback_id = secrets.token_urlsafe(12)
        payload = json.dumps({
            "avatar_username": avatar_username,
            "action": action,
            "user_id": user_id,
        })
        self._redis.setex(f"{_KEY_PREFIX}{callback_id}", _TTL_SECONDS, payload)
        return callback_id

    def resolve(self, callback_id: str) -> dict[str, Any] | None:
        """Resolve callback_id to its stored payload.

        Returns:
            Dict with draft_id/avatar_username, action, user_id — or None if expired/missing.
        """
        raw = self._redis.get(f"{_KEY_PREFIX}{callback_id}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Malformed callback payload for %s", callback_id)
            return None

    def invalidate(self, callback_id: str) -> None:
        """Delete a callback_id after processing (optional cleanup)."""
        self._redis.delete(f"{_KEY_PREFIX}{callback_id}")

    def close(self) -> None:
        """Close Redis connection."""
        self._redis.close()
