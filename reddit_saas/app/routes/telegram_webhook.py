"""Telegram Webhook Route — receives bot updates via HTTPS.

Validates secret_token header, routes updates to appropriate handlers:
- callback_query → button press (approve/skip/edit/approve_all)
- message with reply → edit flow (user sent edited text)
- message with /command → bot commands (/pending, /help, /status, /approve_all)
"""

import asyncio

from fastapi import APIRouter, Request, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.logging_config import get_logger
from app.services.telegram.bot_service import get_bot_service
from app.services.telegram.callback_store import CallbackStore
from app.services.telegram.draft_review import TelegramDraftReview
from app.services.telegram.formatter import DraftCardFormatter

logger = get_logger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


def _get_webhook_secret() -> str:
    """Get webhook secret from DB settings."""
    from app.config import get_config
    return get_config("telegram_webhook_secret") or ""


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive Telegram updates via webhook.

    Security: validates X-Telegram-Bot-Api-Secret-Token header.
    Always returns 200 (Telegram retries on non-200).
    """
    # 1. Validate secret token
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = _get_webhook_secret()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    # 2. Parse update
    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

    # 3. Route by update type (non-blocking — errors logged, never propagated)
    try:
        if "callback_query" in update:
            await _handle_callback(update["callback_query"])
        elif "message" in update:
            message = update["message"]
            if message.get("reply_to_message"):
                await _handle_reply(message)
            elif "text" in message and message["text"].startswith("/"):
                await _handle_command(message)
    except Exception as e:
        logger.error("Telegram webhook handler error: %s", e, exc_info=True)

    # 4. Always 200
    return {"ok": True}


# ------------------------------------------------------------------
# Callback Handler (button presses)
# ------------------------------------------------------------------

async def _handle_callback(callback_query: dict) -> None:
    """Handle inline keyboard button press."""
    bot = get_bot_service()
    if not bot:
        return

    callback_query_id = callback_query.get("id", "")
    callback_data = callback_query.get("data", "")
    chat_id = str(callback_query.get("from", {}).get("id", ""))
    message = callback_query.get("message", {})
    message_id = message.get("message_id", 0)
    original_text = message.get("text", "")

    # Acknowledge immediately (Telegram requires within 10s)
    await bot.answer_callback_query(callback_query_id)

    # Resolve callback_id from Redis
    store = CallbackStore()
    payload = store.resolve(callback_data)
    if payload is None:
        await bot.edit_message_text(
            chat_id, message_id,
            "⏰ Session expired. Use /pending to get fresh draft cards."
        )
        return

    # Lookup user
    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await bot.edit_message_text(chat_id, message_id, "❌ Account not linked.")
            return

        # Verify user_id matches (security)
        if str(user.id) != payload.get("user_id"):
            await bot.edit_message_text(chat_id, message_id, "❌ Authorization error.")
            return

        action = payload.get("action", "")
        review = TelegramDraftReview()
        formatter = DraftCardFormatter()

        if action == "approve":
            result = review.approve_draft(db, user, payload["draft_id"])
            if result["status"] == "approved":
                new_text = formatter.format_approved(original_text)
                await bot.edit_message_text(chat_id, message_id, new_text)
            elif result["status"] in ("approved", "rejected"):
                # Already reviewed by another channel
                new_text = formatter.format_already_reviewed(result["status"], original_text)
                await bot.edit_message_text(chat_id, message_id, new_text)
            else:
                await bot.answer_callback_query(callback_query_id, text=f"⚠️ {result.get('message', 'Error')}", show_alert=True)

        elif action == "skip":
            result = review.skip_draft(db, user, payload["draft_id"])
            if result["status"] == "rejected":
                new_text = formatter.format_skipped(original_text)
                await bot.edit_message_text(chat_id, message_id, new_text)
            elif result["status"] in ("approved", "rejected"):
                new_text = formatter.format_already_reviewed(result["status"], original_text)
                await bot.edit_message_text(chat_id, message_id, new_text)
            else:
                await bot.answer_callback_query(callback_query_id, text=f"⚠️ {result.get('message', 'Error')}", show_alert=True)

        elif action == "edit":
            draft_text = review.start_edit_session(
                db, user, payload["draft_id"], chat_id, message_id
            )
            if draft_text:
                edit_prompt = formatter.format_edit_prompt(draft_text)
                # Send as a reply to the original message
                await bot.send_message(
                    chat_id, edit_prompt, reply_to_message_id=message_id
                )
            else:
                await bot.send_message(chat_id, "⚠️ Could not start edit session.")

        elif action == "approve_all":
            avatar_username = payload.get("avatar_username", "")
            result = review.bulk_approve(db, user, avatar_username)
            if result.get("approved", 0) > 0:
                await bot.send_message(
                    chat_id,
                    f"✅ Approved {result['approved']} drafts for u/{avatar_username}"
                )
            elif result.get("status") == "error":
                await bot.send_message(chat_id, f"⚠️ {result.get('message', 'Error')}")
            else:
                await bot.send_message(chat_id, f"No pending drafts for u/{avatar_username}")

    finally:
        db.close()


# ------------------------------------------------------------------
# Reply Handler (edit flow — user sends edited text)
# ------------------------------------------------------------------

async def _handle_reply(message: dict) -> None:
    """Handle text reply (edit flow — user's correction guidance)."""
    bot = get_bot_service()
    if not bot:
        return

    chat_id = str(message.get("from", {}).get("id", ""))
    text = message.get("text", "")
    reply_to = message.get("reply_to_message", {})
    reply_to_message_id = reply_to.get("message_id", 0)

    if not text or not reply_to_message_id:
        return

    # Check if this reply matches an active edit session
    review = TelegramDraftReview()
    session = review.get_edit_session(chat_id, reply_to_message_id)
    if not session:
        # Not a reply to an edit prompt — ignore silently
        return

    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            return

        # Verify user
        if str(user.id) != session.get("user_id"):
            return

        # Process edit (LLM regeneration)
        result = review.process_edit_reply(db, user, session["draft_id"], text)

        if result["status"] == "regenerated":
            # Send new draft card with fresh callback IDs
            store = CallbackStore()
            callback_ids = {
                "approve": store.create(result["draft_id"], "approve", str(user.id)),
                "skip": store.create(result["draft_id"], "skip", str(user.id)),
                "edit": store.create(result["draft_id"], "edit", str(user.id)),
            }
            formatter = DraftCardFormatter()
            new_text, markup = formatter.format_regenerated(result["new_text"], callback_ids)
            await bot.send_message(chat_id, new_text, reply_markup=markup)
        else:
            error_msg = result.get("message", "Regeneration failed")
            await bot.send_message(chat_id, f"⚠️ {error_msg}. Original draft unchanged — you can try again or approve as-is via /pending")

    finally:
        db.close()


# ------------------------------------------------------------------
# Command Handler (/pending, /help, /status, /approve_all, /start)
# ------------------------------------------------------------------

async def _handle_command(message: dict) -> None:
    """Handle bot commands."""
    bot = get_bot_service()
    if not bot:
        return

    chat_id = str(message.get("from", {}).get("id", ""))
    text = message.get("text", "").strip()
    command = text.split()[0].lower() if text else ""
    args = text.split()[1:] if text else []

    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)

        if command in ("/start", "/link"):
            if user:
                role_info = f"Role: {user.role}"
                if user.role in ("owner", "partner"):
                    msg = f"👋 Welcome back! You'll receive ops alerts + draft review notifications.\n{role_info}"
                else:
                    msg = f"👋 Welcome! You'll receive draft review notifications.\n{role_info}"
                await bot.send_message(chat_id, msg)
            else:
                await bot.send_message(
                    chat_id,
                    "👋 Welcome to RAMP Bot!\n\n"
                    "To link your account, go to the RAMP admin panel → Profile → Telegram section "
                    "and connect your Telegram there.\n\n"
                    "Your account will be linked automatically once configured in the admin panel."
                )
            return

        # All other commands require a linked account
        if not user:
            await bot.send_message(
                chat_id,
                "🔗 Your Telegram is not linked to a RAMP account.\n\n"
                "Go to RAMP admin panel → Profile → Telegram section to link."
            )
            return

        if command == "/help":
            help_text = (
                "📖 <b>Available Commands</b>\n\n"
                "/pending — Show pending drafts for review\n"
                "/approve_all &lt;avatar&gt; — Approve all pending drafts for avatar\n"
                "/status — Show account status and pending count\n"
                "/help — Show this help message"
            )
            await bot.send_message(chat_id, help_text)

        elif command == "/pending":
            review = TelegramDraftReview()
            pending = review.get_pending_for_user(db, user, limit=5)
            if not pending:
                await bot.send_message(chat_id, "🎉 No pending drafts!")
                return

            count = review.get_pending_count_for_user(db, user)
            await bot.send_message(chat_id, f"📋 <b>{count} pending draft(s)</b>\n\nShowing latest {len(pending)}:")

            store = CallbackStore()
            formatter = DraftCardFormatter()
            show_client = user.role in ("owner", "partner")

            for item in pending:
                draft = item["draft"]
                callback_ids = {
                    "approve": store.create(str(draft.id), "approve", str(user.id)),
                    "skip": store.create(str(draft.id), "skip", str(user.id)),
                    "edit": store.create(str(draft.id), "edit", str(user.id)),
                }
                text_msg, markup = formatter.format_draft_card(
                    draft, callback_ids, item["client_name"] if show_client else None
                )
                await bot.send_message(chat_id, text_msg, reply_markup=markup)

        elif command == "/approve_all":
            if not args:
                await bot.send_message(chat_id, "Usage: /approve_all &lt;avatar_username&gt;")
                return
            avatar_username = args[0]
            review = TelegramDraftReview()
            result = review.bulk_approve(db, user, avatar_username)
            if result.get("approved", 0) > 0:
                await bot.send_message(chat_id, f"✅ Approved {result['approved']} drafts for u/{avatar_username}")
            elif result.get("status") == "error":
                await bot.send_message(chat_id, f"⚠️ {result.get('message', 'Error')}")
            else:
                await bot.send_message(chat_id, f"No pending drafts for u/{avatar_username}")

        elif command == "/status":
            review = TelegramDraftReview()
            count = review.get_pending_count_for_user(db, user)
            level = user.telegram_notifications_level or "critical"
            status_text = (
                f"👤 <b>{user.email}</b>\n"
                f"🔑 Role: {user.role}\n"
                f"🔔 Notifications: {level}\n"
                f"📋 Pending drafts: {count}"
            )
            await bot.send_message(chat_id, status_text)

        else:
            await bot.send_message(chat_id, "❓ Unknown command. Try /help")

    finally:
        db.close()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_user_by_chat_id(db: Session, chat_id: str):
    """Lookup User by telegram_chat_id. Returns User or None."""
    from app.models.user import User
    return (
        db.query(User)
        .filter(User.telegram_chat_id == chat_id, User.is_active.is_(True))
        .first()
    )
