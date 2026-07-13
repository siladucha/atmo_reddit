"""Telegram Bot API wrapper — low-level HTTP calls to Bot API.

Uses httpx (already in project) for async HTTP. No external Telegram libraries.
Consistent with existing ops_notifications.py pattern but async-capable.
"""

import asyncio
from typing import Any

import httpx

from app.logging_config import get_logger

logger = get_logger(__name__)

_SEND_DELAY = 0.05  # 50ms between sends to same chat (Telegram rate limit)


class TelegramBotService:
    """Low-level Telegram Bot API wrapper."""

    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._last_send_time: dict[str, float] = {}

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
        reply_to_message_id: int | None = None,
    ) -> dict | None:
        """Send a message with optional inline keyboard.

        Returns the sent Message object or None on failure.
        """
        await self._rate_limit(chat_id)
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if reply_markup:
            import json
            data["reply_markup"] = json.dumps(reply_markup)
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id

        return await self._post("sendMessage", data)

    async def edit_message_text(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str = "HTML",
    ) -> dict | None:
        """Edit an existing message's text and/or inline keyboard."""
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
        if reply_markup:
            import json
            data["reply_markup"] = json.dumps(reply_markup)

        return await self._post("editMessageText", data)

    async def edit_message_reply_markup(
        self,
        chat_id: str,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> dict | None:
        """Edit only the inline keyboard of an existing message."""
        import json
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        else:
            data["reply_markup"] = json.dumps({"inline_keyboard": []})

        return await self._post("editMessageReplyMarkup", data)

    async def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        """Acknowledge a callback query (must be called within 10s of button press)."""
        data: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        if show_alert:
            data["show_alert"] = True
        await self._post("answerCallbackQuery", data)

    async def register_webhook(self, url: str, secret_token: str) -> bool:
        """Register webhook URL with Telegram. Returns True on success."""
        data = {
            "url": url,
            "secret_token": secret_token,
            "allowed_updates": ["message", "callback_query"],
            "drop_pending_updates": False,
        }
        result = await self._post("setWebhook", data)
        if result:
            logger.info("Telegram webhook registered: %s", url)
            return True
        return False

    async def set_my_commands(self, commands: list[dict[str, str]]) -> bool:
        """Set bot command menu. commands = [{"command": "/help", "description": "..."}]."""
        data = {"commands": commands}
        import json
        result = await self._post_json("setMyCommands", {"commands": json.dumps(commands)})
        return result is not None

    async def delete_webhook(self) -> bool:
        """Remove webhook (useful for switching to polling during dev)."""
        result = await self._post("deleteWebhook", {"drop_pending_updates": True})
        return result is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _rate_limit(self, chat_id: str) -> None:
        """Enforce minimum delay between sends to same chat."""
        import time
        now = time.time()
        last = self._last_send_time.get(chat_id, 0)
        diff = now - last
        if diff < _SEND_DELAY:
            await asyncio.sleep(_SEND_DELAY - diff)
        self._last_send_time[chat_id] = time.time()

    async def _post(self, method: str, data: dict) -> dict | None:
        """POST to Telegram Bot API. Returns result dict or None on error."""
        url = f"{self.base_url}/{method}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, data=data)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("ok"):
                    return body.get("result")
                else:
                    logger.warning("Telegram %s not ok: %s", method, body.get("description", ""))
                    return None
            else:
                logger.warning(
                    "Telegram %s HTTP %d: %s", method, resp.status_code, resp.text[:200]
                )
                return None
        except httpx.TimeoutException:
            logger.warning("Telegram %s timeout", method)
            return None
        except Exception as e:
            logger.warning("Telegram %s error: %s", method, e)
            return None

    async def _post_json(self, method: str, data: dict) -> dict | None:
        """POST with JSON body (for complex payloads like setMyCommands)."""
        url = f"{self.base_url}/{method}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json=data)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("ok"):
                    return body.get("result")
            logger.warning("Telegram %s failed: %s", method, resp.text[:200] if resp else "no response")
            return None
        except Exception as e:
            logger.warning("Telegram %s error: %s", method, e)
            return None


def get_bot_service() -> TelegramBotService | None:
    """Get TelegramBotService instance if bot_token is configured. Returns None otherwise."""
    from app.config import get_config
    bot_token = get_config("telegram_bot_token")
    if not bot_token:
        return None
    return TelegramBotService(bot_token)
