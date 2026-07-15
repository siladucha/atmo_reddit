"""Telegram Webhook Route — receives bot updates via HTTPS.

Role-based command routing:
- Owner/Partner: full ops commands + draft review + settings
- Avatar Manager: draft review + /avatars
- QA: draft review
- Client Admin/Manager: draft review (own client)
- Unlinked users: /start + /help (connection instructions)

Security:
- Callback IDs are short Redis-mapped tokens (24h TTL)
- Server re-verifies user permissions on every callback action
- All actions are idempotent (duplicate press = no re-execution)
- Redis is temporary state only — no persistent data dependency
"""

import asyncio
from datetime import datetime, timezone

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

# Roles that can review drafts via Telegram
REVIEW_ROLES = ("owner", "partner", "client_admin", "client_manager", "avatar_manager", "qa")

# Roles that get system brief in /status
OPS_ROLES = ("owner", "partner")


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
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    expected = _get_webhook_secret()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        update = await request.json()
    except Exception:
        return {"ok": True}

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

    return {"ok": True}


@router.post("/register-commands")
async def register_bot_commands(request: Request):
    """Register bot command menu with Telegram. Call once after deploy."""
    bot = get_bot_service()
    if not bot:
        return {"ok": False, "error": "Bot not configured"}

    commands = [
        {"command": "start", "description": "Connect account / show Chat ID"},
        {"command": "help", "description": "Show available commands"},
        {"command": "status", "description": "Account and system status"},
        {"command": "pending", "description": "Show drafts pending review"},
        {"command": "approve_all", "description": "Approve all drafts for an avatar"},
        {"command": "settings", "description": "Notification settings"},
    ]
    await bot.set_my_commands(commands)
    return {"ok": True, "commands_registered": len(commands)}


# ------------------------------------------------------------------
# Callback Handler (button presses)
# ------------------------------------------------------------------

async def _handle_callback(callback_query: dict) -> None:
    """Handle inline keyboard button press.

    Security: re-verifies user_id match on every action (idempotent).
    """
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

    # --- Handle /settings level buttons ---
    if callback_data.startswith("level:"):
        await _handle_settings_callback(bot, chat_id, message_id, callback_data)
        return

    # --- Handle /approve_all confirmation ---
    if callback_data.startswith("confirm_approve_all:"):
        await _handle_approve_all_confirm(bot, chat_id, message_id, callback_data)
        return

    if callback_data == "cancel_approve_all":
        await bot.edit_message_text(chat_id, message_id, "❌ Bulk approve cancelled.")
        return

    # Resolve callback_id from Redis
    store = CallbackStore()
    payload = store.resolve(callback_data)
    if payload is None:
        await bot.edit_message_text(
            chat_id, message_id,
            "⏰ Session expired. Use /pending to get fresh draft cards."
        )
        return

    # Lookup user + verify permissions
    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await bot.edit_message_text(chat_id, message_id, "❌ Account not linked.")
            return

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
                new_text = formatter.format_already_reviewed(result["status"], original_text)
                await bot.edit_message_text(chat_id, message_id, new_text)
            else:
                await bot.answer_callback_query(
                    callback_query_id, text=f"⚠️ {result.get('message', 'Error')}", show_alert=True
                )

        elif action == "skip":
            result = review.skip_draft(db, user, payload["draft_id"])
            if result["status"] == "rejected":
                new_text = formatter.format_skipped(original_text)
                await bot.edit_message_text(chat_id, message_id, new_text)
            elif result["status"] in ("approved", "rejected"):
                new_text = formatter.format_already_reviewed(result["status"], original_text)
                await bot.edit_message_text(chat_id, message_id, new_text)
            else:
                await bot.answer_callback_query(
                    callback_query_id, text=f"⚠️ {result.get('message', 'Error')}", show_alert=True
                )

        elif action == "edit":
            draft_text = review.start_edit_session(
                db, user, payload["draft_id"], chat_id, message_id
            )
            if draft_text:
                edit_prompt = formatter.format_edit_prompt(draft_text)
                await bot.send_message(chat_id, edit_prompt, reply_to_message_id=message_id)
            else:
                await bot.send_message(chat_id, "⚠️ Could not start edit session.")

        elif action == "approve_all":
            avatar_username = payload.get("avatar_username", "")
            result = review.bulk_approve(db, user, avatar_username)
            if result.get("approved", 0) > 0:
                await bot.send_message(
                    chat_id, f"✅ Approved {result['approved']} drafts for u/{avatar_username}"
                )
            elif result.get("status") == "error":
                await bot.send_message(chat_id, f"⚠️ {result.get('message', 'Error')}")
            else:
                await bot.send_message(chat_id, f"No pending drafts for u/{avatar_username}")

    finally:
        db.close()


# ------------------------------------------------------------------
# Reply Handler (edit flow — user sends edited text or /cancel)
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
        return

    # /cancel aborts edit mode
    if text.strip().lower() == "/cancel":
        review.cancel_edit_session(chat_id, reply_to_message_id)
        await bot.send_message(chat_id, "✅ Edit cancelled. Draft unchanged.\nUse /pending to review again.")
        return

    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            return

        if str(user.id) != session.get("user_id"):
            return

        result = review.process_edit_reply(db, user, session["draft_id"], text)

        if result["status"] == "regenerated":
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
            await bot.send_message(
                chat_id, f"⚠️ {error_msg}. Original draft unchanged — try again or /pending."
            )

    finally:
        db.close()


# ------------------------------------------------------------------
# Command Handler — role-based routing
# ------------------------------------------------------------------

async def _handle_command(message: dict) -> None:
    """Handle bot commands with role-based access."""
    bot = get_bot_service()
    if not bot:
        return

    chat_id = str(message.get("from", {}).get("id", ""))
    text = message.get("text", "").strip()
    command = text.split()[0].lower().split("@")[0] if text else ""
    args = text.split()[1:] if text else []

    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)

        # --- Always available (linked or not) ---
        if command in ("/start", "/link"):
            await _cmd_start(bot, chat_id, user, db)
            return

        if command == "/help":
            await _cmd_help(bot, chat_id, user)
            return

        # /cancel outside edit mode — just acknowledge
        if command == "/cancel":
            await bot.send_message(chat_id, "Nothing to cancel. You're not in edit mode.")
            return

        # All other commands require linked account
        if not user:
            await bot.send_message(
                chat_id,
                f"🔗 <b>Account not linked</b>\n\n"
                f"Your Chat ID: <code>{chat_id}</code>\n\n"
                f"Go to RAMP → Profile → Telegram, paste this ID and click Connect.\n"
                f"Use /help for instructions.",
            )
            return

        # Route by command
        if command == "/status":
            await _cmd_status(bot, chat_id, user, db)
        elif command == "/pending":
            await _cmd_pending(bot, chat_id, user, db)
        elif command == "/approve_all":
            await _cmd_approve_all(bot, chat_id, user, db, args)
        elif command == "/settings":
            await _cmd_settings(bot, chat_id, user)
        # --- Ops commands ---
        elif command == "/costs":
            await _cmd_ops_only(bot, chat_id, user, db, "costs")
        elif command == "/avatars":
            await _cmd_ops_only(bot, chat_id, user, db, "avatars")
        elif command == "/errors":
            await _cmd_ops_only(bot, chat_id, user, db, "errors")
        elif command == "/pipelines":
            await _cmd_ops_only(bot, chat_id, user, db, "pipelines")
        else:
            await bot.send_message(chat_id, "❓ Unknown command. Try /help")

    finally:
        db.close()


# ------------------------------------------------------------------
# /start — always available
# ------------------------------------------------------------------

async def _cmd_start(bot, chat_id: str, user, db: Session) -> None:
    """Show chat_id + welcome. Works for linked and unlinked users.

    Point #12: If user just linked (telegram_connected_at recent), send confirmation.
    """
    if user:
        role = user.role
        if role in OPS_ROLES:
            msg = (
                f"👋 <b>Welcome back!</b>\n\n"
                f"📱 Chat ID: <code>{chat_id}</code>\n"
                f"🔑 Role: {role}\n"
                f"🔔 Notifications: {user.telegram_notifications_level or 'critical'}\n\n"
                f"You receive: ops alerts + draft review.\n"
                f"Type /help for commands."
            )
        elif role in REVIEW_ROLES:
            msg = (
                f"👋 <b>Welcome!</b>\n\n"
                f"📱 Chat ID: <code>{chat_id}</code>\n"
                f"🔑 Role: {role}\n"
                f"🔔 Notifications: {user.telegram_notifications_level or 'critical'}\n\n"
                f"You receive: draft review notifications.\n"
                f"Type /help for commands."
            )
        else:
            msg = (
                f"👋 <b>Welcome!</b>\n\n"
                f"📱 Chat ID: <code>{chat_id}</code>\n"
                f"🔑 Role: {role}\n"
                f"🔔 Notifications: {user.telegram_notifications_level or 'critical'}\n\n"
                f"Type /help for commands."
            )
    else:
        msg = (
            f"👋 <b>Welcome to RAMP Bot!</b>\n\n"
            f"📱 Your Chat ID: <code>{chat_id}</code>\n\n"
            f"<b>To link your account:</b>\n"
            f"1. Log in to RAMP panel\n"
            f"2. Go to Profile → Telegram section\n"
            f"3. Paste the Chat ID above and click Connect\n\n"
            f"Type /help for more info."
        )
    await bot.send_message(chat_id, msg)


# ------------------------------------------------------------------
# /help — available to everyone (point #1: unlinked gets link instructions)
# ------------------------------------------------------------------

async def _cmd_help(bot, chat_id: str, user) -> None:
    """Show commands available for user's role. Unlinked = link instructions."""
    if not user:
        msg = (
            "📖 <b>RAMP Bot Help</b>\n\n"
            "<b>How to connect:</b>\n"
            "1. Copy your Chat ID (shown in /start)\n"
            "2. Log in to RAMP panel → Profile → Telegram\n"
            "3. Paste Chat ID → Connect\n\n"
            "<b>Available after connection:</b>\n"
            "/status — Account status\n"
            "/pending — Drafts for review\n"
            "/settings — Notification preferences\n"
            "/help — This message"
        )
        await bot.send_message(chat_id, msg)
        return

    role = user.role
    lines = ["📖 <b>Available Commands</b>\n"]

    # General (all linked users)
    lines.append("<b>— General —</b>")
    lines.append("/start — Show Chat ID and connection info")
    lines.append("/status — Account and system status")
    lines.append("/settings — Notification level (change inline)")
    lines.append("/help — This help message")
    lines.append("")

    # Draft review
    if role in REVIEW_ROLES:
        lines.append("<b>— Draft Review —</b>")
        lines.append("/pending — Show drafts pending review")
        lines.append("/approve_all &lt;avatar&gt; — Approve all for an avatar")
        lines.append("")

    # Ops commands
    if role in OPS_ROLES:
        lines.append("<b>— Operations —</b>")
        lines.append("/costs — AI spend today")
        lines.append("/avatars — Avatar fleet status")
        lines.append("/errors — Pipeline errors (24h, max 10)")
        lines.append("/pipelines — Latest pipeline run per type")
    elif role == "avatar_manager":
        lines.append("<b>— Operations —</b>")
        lines.append("/avatars — Avatar fleet status")

    await bot.send_message(chat_id, "\n".join(lines))


# ------------------------------------------------------------------
# /status — account + system brief for ops roles
# ------------------------------------------------------------------

async def _cmd_status(bot, chat_id: str, user, db: Session) -> None:
    """Account status + pending count. System brief for owner/partner."""
    review = TelegramDraftReview()
    count = review.get_pending_count_for_user(db, user)
    level = user.telegram_notifications_level or "critical"

    lines = [
        f"👤 <b>{user.email}</b>",
        f"🔑 Role: {user.role}",
        f"🔔 Notifications: {level}",
        f"📋 Pending drafts: {count}",
    ]

    if user.role in OPS_ROLES:
        sys_info = _get_system_status_brief(db)
        if sys_info:
            lines.append("")
            lines.append("<b>— System —</b>")
            lines.extend(sys_info)

    await bot.send_message(chat_id, "\n".join(lines))


# ------------------------------------------------------------------
# /settings — inline notification level change (point #9)
# ------------------------------------------------------------------

async def _cmd_settings(bot, chat_id: str, user) -> None:
    """Show current notification settings with inline buttons to change."""
    current = user.telegram_notifications_level or "critical"
    level_labels = {
        "all": "📢 All",
        "warning": "⚠️ Warning + Critical",
        "critical": "🔴 Critical only",
        "off": "🔇 Off",
    }

    msg = (
        f"⚙️ <b>Notification Settings</b>\n\n"
        f"Current level: <b>{level_labels.get(current, current)}</b>\n\n"
        f"Tap a button to change:"
    )

    # Build inline keyboard — highlight current with checkmark
    buttons = []
    for level_key, label in level_labels.items():
        prefix = "✓ " if level_key == current else ""
        buttons.append([{"text": f"{prefix}{label}", "callback_data": f"level:{level_key}"}])

    reply_markup = {"inline_keyboard": buttons}
    await bot.send_message(chat_id, msg, reply_markup=reply_markup)


async def _handle_settings_callback(bot, chat_id: str, message_id: int, callback_data: str) -> None:
    """Handle /settings level button press."""
    level = callback_data.split(":", 1)[1] if ":" in callback_data else ""
    valid_levels = {"all", "warning", "critical", "off"}
    if level not in valid_levels:
        return

    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            return

        user.telegram_notifications_level = level
        db.commit()

        level_labels = {"all": "📢 All", "warning": "⚠️ Warning + Critical", "critical": "🔴 Critical only", "off": "🔇 Off"}
        await bot.edit_message_text(
            chat_id, message_id,
            f"✅ Notification level updated: <b>{level_labels.get(level, level)}</b>\n\n"
            f"Use /settings to change again.",
        )
    finally:
        db.close()


# ------------------------------------------------------------------
# /pending — draft review
# ------------------------------------------------------------------

async def _cmd_pending(bot, chat_id: str, user, db: Session) -> None:
    """Show pending drafts. Point #4: explicit 'no drafts' message."""
    if user.role not in REVIEW_ROLES:
        await bot.send_message(chat_id, "❌ Draft review is not available for your role.")
        return

    review = TelegramDraftReview()
    pending = review.get_pending_for_user(db, user, limit=5)
    if not pending:
        await bot.send_message(chat_id, "📭 No drafts pending review.")
        return

    count = review.get_pending_count_for_user(db, user)
    header = f"📋 <b>{count} pending draft(s)</b>"
    if count > 5:
        header += f"\n\nShowing latest 5 of {count}:"
    await bot.send_message(chat_id, header)

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


# ------------------------------------------------------------------
# /approve_all — with confirmation (point #3)
# ------------------------------------------------------------------

async def _cmd_approve_all(bot, chat_id: str, user, db: Session, args: list) -> None:
    """Approve all pending drafts for avatar — with confirmation step."""
    if user.role not in REVIEW_ROLES:
        await bot.send_message(chat_id, "❌ Draft review is not available for your role.")
        return

    if not args:
        await bot.send_message(chat_id, "Usage: /approve_all &lt;avatar_username&gt;")
        return

    avatar_username = args[0].lstrip("u/").lstrip("/")

    # Count pending first
    review = TelegramDraftReview()
    from app.models.avatar import Avatar
    from app.models.comment_draft import CommentDraft
    import sqlalchemy as sa

    avatar = (
        db.query(Avatar)
        .filter(sa.func.lower(Avatar.reddit_username) == avatar_username.lower())
        .first()
    )
    if not avatar:
        await bot.send_message(chat_id, f"❌ Avatar u/{avatar_username} not found.")
        return

    pending_count = (
        db.query(CommentDraft)
        .filter(CommentDraft.avatar_id == avatar.id, CommentDraft.status == "pending")
        .count()
    )

    if pending_count == 0:
        await bot.send_message(chat_id, f"📭 No pending drafts for u/{avatar_username}.")
        return

    # Confirmation step (point #3)
    msg = f"⚡ Approve <b>{pending_count}</b> drafts for u/{avatar_username}?"
    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ Yes, approve all", "callback_data": f"confirm_approve_all:{avatar_username}"},
            {"text": "❌ Cancel", "callback_data": "cancel_approve_all"},
        ]]
    }
    await bot.send_message(chat_id, msg, reply_markup=reply_markup)


async def _handle_approve_all_confirm(bot, chat_id: str, message_id: int, callback_data: str) -> None:
    """Handle confirmed bulk approve after user tapped 'Yes'."""
    avatar_username = callback_data.split(":", 1)[1] if ":" in callback_data else ""
    if not avatar_username:
        return

    db = SessionLocal()
    try:
        user = _get_user_by_chat_id(db, chat_id)
        if not user:
            await bot.edit_message_text(chat_id, message_id, "❌ Account not linked.")
            return

        review = TelegramDraftReview()
        result = review.bulk_approve(db, user, avatar_username)

        if result.get("approved", 0) > 0:
            await bot.edit_message_text(
                chat_id, message_id,
                f"✅ Approved {result['approved']} drafts for u/{avatar_username}",
            )
        elif result.get("status") == "error":
            await bot.edit_message_text(chat_id, message_id, f"⚠️ {result.get('message', 'Error')}")
        else:
            await bot.edit_message_text(chat_id, message_id, f"📭 No pending drafts for u/{avatar_username}")
    finally:
        db.close()


# ------------------------------------------------------------------
# Ops Commands (owner/partner + avatar_manager for /avatars)
# ------------------------------------------------------------------

async def _cmd_ops_only(bot, chat_id: str, user, db: Session, cmd: str) -> None:
    """Route ops commands with role checks."""
    # avatar_manager can access /avatars only
    if user.role == "avatar_manager" and cmd == "avatars":
        await _ops_avatars(bot, chat_id, db)
        return

    if user.role not in OPS_ROLES:
        await bot.send_message(chat_id, "❌ This command is available to owner/partner only.")
        return

    if cmd == "costs":
        await _ops_costs(bot, chat_id, db)
    elif cmd == "avatars":
        await _ops_avatars(bot, chat_id, db)
    elif cmd == "errors":
        await _ops_errors(bot, chat_id, db)
    elif cmd == "pipelines":
        await _ops_pipelines(bot, chat_id, db)


async def _ops_costs(bot, chat_id: str, db: Session) -> None:
    """AI costs today — point #6: show budget percentage."""
    from app.models.ai_usage import AIUsageLog
    from sqlalchemy import func, cast, Date

    today = datetime.now(timezone.utc).date()
    row = (
        db.query(
            func.coalesce(func.sum(AIUsageLog.cost_usd), 0).label("total"),
            func.count().label("calls"),
            func.coalesce(func.max(AIUsageLog.cost_usd), 0).label("max_call"),
        )
        .filter(cast(AIUsageLog.created_at, Date) == today)
        .first()
    )

    total = float(row.total) if row else 0
    calls = int(row.calls) if row else 0
    max_call = float(row.max_call) if row else 0

    # Daily budget estimate (~$20/day at current scale)
    daily_budget = 20.0
    pct = (total / daily_budget * 100) if daily_budget > 0 else 0
    bar = _progress_bar(pct)

    await bot.send_message(
        chat_id,
        f"💰 <b>AI Costs Today</b>\n\n"
        f"  Spent: <b>${total:.2f}</b> / ${daily_budget:.0f}\n"
        f"  {bar} {pct:.0f}%\n"
        f"  Calls: {calls}\n"
        f"  Max single: ${max_call:.4f}",
    )


async def _ops_avatars(bot, chat_id: str, db: Session) -> None:
    """Avatar fleet status — point #5: summary stats."""
    from app.models.avatar import Avatar
    from sqlalchemy import func

    total = db.query(func.count(Avatar.id)).filter(Avatar.is_active.is_(True)).scalar() or 0
    active = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.is_active.is_(True), Avatar.is_frozen.is_(False))
        .scalar() or 0
    )
    frozen = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.is_active.is_(True), Avatar.is_frozen.is_(True))
        .scalar() or 0
    )
    banned = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.is_active.is_(True), Avatar.is_shadowbanned.is_(True))
        .scalar() or 0
    )
    suspended = (
        db.query(func.count(Avatar.id))
        .filter(Avatar.is_active.is_(True), Avatar.health_status == "suspended")
        .scalar() or 0
    )

    await bot.send_message(
        chat_id,
        f"👤 <b>Avatar Fleet</b>\n\n"
        f"  🟢 Active: {active}\n"
        f"  🧊 Frozen: {frozen}\n"
        f"  🚫 Shadowbanned: {banned}\n"
        f"  ☠️ Suspended: {suspended}\n"
        f"  ─────────────\n"
        f"  Total active: {total}",
    )


async def _ops_errors(bot, chat_id: str, db: Session) -> None:
    """Pipeline errors — point #7: max 10, clear 'no errors' state."""
    from app.models.pipeline_run import PipelineRun
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    errors = (
        db.query(PipelineRun)
        .filter(
            PipelineRun.status.in_(["failed", "partial"]),
            PipelineRun.started_at >= cutoff,
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(10)
        .all()
    )

    if not errors:
        await bot.send_message(chat_id, "✅ <b>No errors in 24h</b> — all clear!")
        return

    # Count total (may be more than 10)
    from sqlalchemy import func
    total_errors = (
        db.query(func.count(PipelineRun.id))
        .filter(
            PipelineRun.status.in_(["failed", "partial"]),
            PipelineRun.started_at >= cutoff,
        )
        .scalar() or 0
    )

    lines = [f"🚨 <b>Errors (24h): {total_errors}</b>\n<i>Showing latest 10:</i>\n"]
    for run in errors:
        icon = "❌" if run.status == "failed" else "⚠️"
        time_str = run.started_at.strftime("%H:%M") if run.started_at else "?"
        err = (run.error_message or "no details")[:60]
        lines.append(f"  {icon} {time_str} <code>{run.pipeline_type}</code>")
        lines.append(f"     {err}")

    await bot.send_message(chat_id, "\n".join(lines))


async def _ops_pipelines(bot, chat_id: str, db: Session) -> None:
    """Latest pipeline runs — point #8: clear status per type."""
    from app.models.pipeline_run import PipelineRun
    from sqlalchemy import func

    subq = (
        db.query(
            PipelineRun.pipeline_type,
            func.max(PipelineRun.started_at).label("latest"),
        )
        .group_by(PipelineRun.pipeline_type)
        .subquery()
    )

    runs = (
        db.query(PipelineRun)
        .join(
            subq,
            (PipelineRun.pipeline_type == subq.c.pipeline_type)
            & (PipelineRun.started_at == subq.c.latest),
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(12)
        .all()
    )

    if not runs:
        await bot.send_message(chat_id, "📭 No pipeline runs found.")
        return

    icon_map = {"completed": "✅", "failed": "❌", "partial": "⚠️", "running": "🔄"}
    lines = ["⚙️ <b>Pipeline Status</b>\n"]

    for run in runs:
        icon = icon_map.get(run.status, "❓")
        time_str = run.started_at.strftime("%H:%M") if run.started_at else "?"
        dur = ""
        if run.duration_ms:
            if run.duration_ms < 60000:
                dur = f" ({run.duration_ms / 1000:.1f}s)"
            else:
                dur = f" ({run.duration_ms / 60000:.1f}m)"
        lines.append(f"  {icon} <code>{run.pipeline_type:18s}</code> {time_str}{dur}")

    await bot.send_message(chat_id, "\n".join(lines))


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


def _get_system_status_brief(db: Session) -> list[str]:
    """System status brief for owner/partner /status command."""
    lines = []
    try:
        from app.models.avatar import Avatar
        from app.models.comment_draft import CommentDraft
        from app.models.ai_usage import AIUsageLog
        from sqlalchemy import func, cast, Date

        today = datetime.now(timezone.utc).date()

        active = (
            db.query(func.count(Avatar.id))
            .filter(Avatar.is_active.is_(True), Avatar.is_frozen.is_(False))
            .scalar() or 0
        )
        frozen = (
            db.query(func.count(Avatar.id))
            .filter(Avatar.is_active.is_(True), Avatar.is_frozen.is_(True))
            .scalar() or 0
        )
        lines.append(f"👤 Avatars: {active} active, {frozen} frozen")

        pending = (
            db.query(func.count(CommentDraft.id))
            .filter(CommentDraft.status == "pending")
            .scalar() or 0
        )
        posted_today = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.status == "posted",
                cast(CommentDraft.posted_at, Date) == today,
            )
            .scalar() or 0
        )
        lines.append(f"📝 Drafts: {pending} pending, {posted_today} posted today")

        cost_today = (
            db.query(func.coalesce(func.sum(AIUsageLog.cost_usd), 0))
            .filter(cast(AIUsageLog.created_at, Date) == today)
            .scalar() or 0
        )
        lines.append(f"💰 AI cost today: ${float(cost_today):.2f}")

    except Exception as e:
        lines.append(f"⚠️ System info unavailable: {str(e)[:50]}")

    return lines


def _progress_bar(pct: float, width: int = 10) -> str:
    """Simple text progress bar for Telegram messages."""
    filled = int(pct / 100 * width)
    filled = max(0, min(width, filled))
    return "█" * filled + "░" * (width - filled)
