"""Draft Card formatting for Telegram messages.

Formats CommentDraft/PostDraft as HTML messages with inline keyboards.
Handles truncation, HTML escaping, and Telegram message size limits (4096 chars).
"""

import html
from typing import Any


_MAX_TITLE_LEN = 80
_MAX_BODY_LEN = 300
_MAX_MESSAGE_LEN = 4000  # Leave margin below 4096


class DraftCardFormatter:
    """Format drafts as Telegram messages with inline keyboards."""

    def format_draft_card(
        self,
        draft: Any,
        callback_ids: dict[str, str],
        client_name: str | None = None,
    ) -> tuple[str, dict]:
        """Format a single draft as HTML text + InlineKeyboardMarkup.

        Args:
            draft: CommentDraft or PostDraft object
            callback_ids: {"approve": "cb_id", "skip": "cb_id", "edit": "cb_id"}
            client_name: Include if user has multi-client access (disambiguation)

        Returns:
            (text, reply_markup) tuple for bot.send_message()
        """
        # Extract data from draft
        thread = getattr(draft, "thread", None) or getattr(draft, "hobby_post", None)
        subreddit = thread.subreddit if thread else "?"
        thread_title = thread.title if thread else "Unknown thread"
        thread_url = f"https://www.reddit.com{thread.permalink}" if thread and hasattr(thread, "permalink") and thread.permalink else None

        avatar = getattr(draft, "avatar", None)
        avatar_name = avatar.reddit_username if avatar else "?"

        body = draft.body or ""

        # Build message text (HTML)
        lines = []
        lines.append(f"📝 <b>Draft for r/{html.escape(subreddit)}</b>")

        meta_parts = [f"👤 {html.escape(avatar_name)}"]
        if client_name:
            meta_parts.append(f"🏢 {html.escape(client_name)}")
        lines.append(" | ".join(meta_parts))

        # Thread title with link
        title_display = _truncate(thread_title, _MAX_TITLE_LEN)
        if thread_url:
            lines.append(f'📌 <a href="{html.escape(thread_url)}">{html.escape(title_display)}</a>')
        else:
            lines.append(f"📌 {html.escape(title_display)}")

        lines.append("")  # blank line
        body_display = _truncate(body, _MAX_BODY_LEN)
        lines.append(f"<i>{html.escape(body_display)}</i>")

        text = "\n".join(lines)

        # Ensure within Telegram limit
        if len(text) > _MAX_MESSAGE_LEN:
            text = text[:_MAX_MESSAGE_LEN] + "…</i>"

        # Inline keyboard
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": callback_ids["approve"]},
                    {"text": "❌ Skip", "callback_data": callback_ids["skip"]},
                    {"text": "✏️ Edit", "callback_data": callback_ids["edit"]},
                ]
            ]
        }

        return text, reply_markup

    def format_summary(
        self,
        drafts_by_avatar: dict[str, int],
        callback_ids: dict[str, str],
        client_name: str | None = None,
    ) -> tuple[str, dict]:
        """Format summary message when >5 drafts. Per-avatar "Approve All" buttons.

        Args:
            drafts_by_avatar: {"avatar_username": count}
            callback_ids: {"approve_all:avatar_username": "cb_id", ...}
            client_name: For multi-client users

        Returns:
            (text, reply_markup)
        """
        total = sum(drafts_by_avatar.values())
        lines = [f"📋 <b>{total} drafts pending review</b>"]
        if client_name:
            lines.append(f"🏢 {html.escape(client_name)}")
        lines.append("")
        for avatar, count in drafts_by_avatar.items():
            lines.append(f"  • {html.escape(avatar)}: {count} drafts")

        text = "\n".join(lines)

        # Per-avatar Approve All buttons
        buttons = []
        for avatar in drafts_by_avatar:
            cb_key = f"approve_all:{avatar}"
            if cb_key in callback_ids:
                buttons.append([{
                    "text": f"✅ Approve All ({avatar})",
                    "callback_data": callback_ids[cb_key],
                }])

        reply_markup = {"inline_keyboard": buttons} if buttons else None
        return text, reply_markup

    def format_approved(self, original_text: str) -> str:
        """Format message text after approval (no buttons needed)."""
        # Strip old italic body, add approved badge
        return f"✅ <b>Approved</b>\n\n{_strip_to_short(original_text)}"

    def format_skipped(self, original_text: str) -> str:
        """Format message text after skip (no buttons needed)."""
        return f"❌ <b>Skipped</b>\n\n{_strip_to_short(original_text)}"

    def format_already_reviewed(self, status: str, original_text: str) -> str:
        """Format message when draft was already reviewed by another channel."""
        icon = "✅" if status == "approved" else "❌"
        return f"{icon} <b>Already {html.escape(status)}</b> (via another channel)\n\n{_strip_to_short(original_text)}"

    def format_edit_prompt(self, full_text: str) -> str:
        """Format the edit prompt message showing full draft text."""
        escaped = html.escape(full_text)
        return (
            f"✏️ <b>Edit mode</b>\n\n"
            f"<code>{escaped}</code>\n\n"
            f"💡 Reply to this message with your corrections or guidance — "
            f"the AI will regenerate the draft.\n\n"
            f"Type /cancel to abort editing."
        )

    def format_regenerated(self, new_text: str, callback_ids: dict[str, str]) -> tuple[str, dict]:
        """Format message after LLM regeneration with new Approve/Skip/Edit buttons."""
        lines = [
            "🔄 <b>Draft regenerated</b>",
            "",
            f"<i>{html.escape(_truncate(new_text, _MAX_BODY_LEN))}</i>",
        ]
        text = "\n".join(lines)
        reply_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": callback_ids["approve"]},
                    {"text": "❌ Skip", "callback_data": callback_ids["skip"]},
                    {"text": "✏️ Edit", "callback_data": callback_ids["edit"]},
                ]
            ]
        }
        return text, reply_markup

    def format_error(self, error_msg: str) -> str:
        """Format error message."""
        return f"⚠️ {html.escape(error_msg)}"


def _truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _strip_to_short(html_text: str) -> str:
    """Keep first 150 chars of a message for post-action display."""
    # Find the italic body part and truncate
    plain = html_text[:200] if len(html_text) > 200 else html_text
    return plain
