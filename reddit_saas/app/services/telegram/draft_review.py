"""Telegram Draft Review — core business logic.

Handles: notification delivery, approve, skip, edit (LLM regeneration), bulk approve.
Reuses same approval logic as extension_api endpoints for consistency.
"""

import asyncio
import json
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from app.config import get_config, get_settings
from app.logging_config import get_logger
from app.services.telegram.bot_service import TelegramBotService, get_bot_service
from app.services.telegram.callback_store import CallbackStore
from app.services.telegram.formatter import DraftCardFormatter

logger = get_logger(__name__)

_EDIT_SESSION_PREFIX = "tg:edit:"
_EDIT_SESSION_TTL = 1800  # 30 minutes
_FAIL_COUNTER_PREFIX = "tg:fail:"
_FAIL_COUNTER_TTL = 86400  # 24 hours
_MAX_CONSECUTIVE_FAILURES = 3

EDIT_SYSTEM_PROMPT = """You are a Reddit comment editor. The user has provided feedback on an existing draft comment. Regenerate the comment incorporating their corrections and guidance while maintaining the same voice, tone, and style as the original. Keep it natural and authentic for Reddit. Output ONLY the new comment text with no preamble or explanation."""


class TelegramDraftReview:
    """Draft review operations triggered from Telegram."""

    def __init__(self):
        self._formatter = DraftCardFormatter()
        self._callback_store = CallbackStore()
        self._redis = redis.from_url(get_settings().redis_url, decode_responses=True)

    # ------------------------------------------------------------------
    # Notification Delivery
    # ------------------------------------------------------------------

    def notify_pending_drafts(self, db: Session, client_id: str, drafts: list) -> int:
        """Send draft notifications to all eligible users for this client.

        Returns count of messages sent. Non-blocking, fire-and-forget.
        """
        # Check kill switch
        from app.services.settings import get_setting
        if get_setting(db, "telegram_draft_review_enabled") != "true":
            return 0

        bot = get_bot_service()
        if not bot:
            return 0

        # Find eligible users
        eligible_users = self._get_eligible_users(db, client_id)
        if not eligible_users:
            return 0

        # Filter drafts that are still pending
        pending_drafts = [d for d in drafts if d.status == "pending"]
        if not pending_drafts:
            return 0

        # Get client name for multi-client users
        from app.models.client import Client
        client = db.query(Client).filter(Client.id == client_id).first()
        client_name = client.company_name if client else None

        sent_count = 0
        for user in eligible_users:
            try:
                count = self._send_drafts_to_user(
                    bot, user, pending_drafts, client_name, db
                )
                sent_count += count
            except Exception as e:
                logger.warning("Telegram notify failed for user %s: %s", user.id, e)
                self._record_failure(str(user.id), db)

        return sent_count

    def _send_drafts_to_user(
        self, bot: TelegramBotService, user, drafts: list, client_name: str | None, db: Session
    ) -> int:
        """Send draft cards to a single user. Returns messages sent."""
        chat_id = user.telegram_chat_id
        if not chat_id:
            return 0

        # Determine if user has multi-client access
        show_client = user.role in ("owner", "partner")

        # Group by avatar for summary
        drafts_by_avatar: dict[str, list] = {}
        for draft in drafts:
            avatar = getattr(draft, "avatar", None)
            avatar_name = avatar.reddit_username if avatar else "unknown"
            drafts_by_avatar.setdefault(avatar_name, []).append(draft)

        sent = 0

        # If >5 drafts, send summary first
        if len(drafts) > 5:
            summary_counts = {k: len(v) for k, v in drafts_by_avatar.items()}
            summary_cbs = {}
            for avatar_name in drafts_by_avatar:
                cb_id = self._callback_store.create_bulk(avatar_name, "approve_all", str(user.id))
                summary_cbs[f"approve_all:{avatar_name}"] = cb_id

            text, markup = self._formatter.format_summary(
                summary_counts, summary_cbs, client_name if show_client else None
            )
            asyncio.get_event_loop().run_until_complete(
                bot.send_message(chat_id, text, reply_markup=markup)
            )
            sent += 1

        # Send individual draft cards
        for draft in drafts:
            # Re-check status (might have been approved during sending)
            if draft.status != "pending":
                continue

            callback_ids = {
                "approve": self._callback_store.create(str(draft.id), "approve", str(user.id)),
                "skip": self._callback_store.create(str(draft.id), "skip", str(user.id)),
                "edit": self._callback_store.create(str(draft.id), "edit", str(user.id)),
            }
            text, markup = self._formatter.format_draft_card(
                draft, callback_ids, client_name if show_client else None
            )
            asyncio.get_event_loop().run_until_complete(
                bot.send_message(chat_id, text, reply_markup=markup)
            )
            sent += 1

        # Reset failure counter on success
        self._redis.delete(f"{_FAIL_COUNTER_PREFIX}{user.id}")
        return sent

    # ------------------------------------------------------------------
    # Approve
    # ------------------------------------------------------------------

    def approve_draft(self, db: Session, user, draft_id: str) -> dict:
        """Approve a single draft. Returns status dict."""
        from app.models.comment_draft import CommentDraft
        from app.models.epg_slot import EPGSlot
        from app.services.epg_executor import _dispatch_email_task_if_enabled
        from app.services.transparency import record_activity_event

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return {"status": "error", "message": "Draft not found"}

        # P7: verify access
        if not _user_can_review_draft(db, user, draft):
            return {"status": "error", "message": "Access denied"}

        # Idempotent: already reviewed
        if draft.status != "pending":
            return {"status": draft.status, "message": f"Already {draft.status}"}

        # Approve
        draft.status = "approved"
        slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
        if slot:
            slot.status = "approved"
            db.commit()
            _dispatch_email_task_if_enabled(db, slot)
        else:
            db.commit()

        # Activity event
        try:
            record_activity_event(
                db, "review",
                f"Draft approved via Telegram for r/{draft.thread.subreddit if draft.thread else '?'}",
                draft.client_id,
                {"draft_id": str(draft.id), "action": "approved", "by": "telegram", "user_id": str(user.id)},
            )
        except Exception:
            pass

        # Self-learning capture
        try:
            from app.services.learning import LearningService
            thread = draft.thread
            if thread:
                LearningService().capture_edit_record(db=db, draft=draft, thread=thread, status="approved_unchanged")
                db.commit()
        except Exception:
            pass

        return {"status": "approved", "draft_id": str(draft.id)}

    # ------------------------------------------------------------------
    # Skip
    # ------------------------------------------------------------------

    def skip_draft(self, db: Session, user, draft_id: str) -> dict:
        """Skip/reject a single draft. Returns status dict."""
        from app.models.comment_draft import CommentDraft
        from app.models.epg_slot import EPGSlot
        from app.services.transparency import record_activity_event

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return {"status": "error", "message": "Draft not found"}

        if not _user_can_review_draft(db, user, draft):
            return {"status": "error", "message": "Access denied"}

        if draft.status != "pending":
            return {"status": draft.status, "message": f"Already {draft.status}"}

        draft.status = "rejected"
        slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
        if slot:
            slot.status = "skipped"
            slot.skip_reason = "rejected_via_telegram"
        db.commit()

        try:
            record_activity_event(
                db, "review",
                f"Draft skipped via Telegram for r/{draft.thread.subreddit if draft.thread else '?'}",
                draft.client_id,
                {"draft_id": str(draft.id), "action": "rejected", "by": "telegram", "user_id": str(user.id)},
            )
        except Exception:
            pass

        return {"status": "rejected", "draft_id": str(draft.id)}

    # ------------------------------------------------------------------
    # Bulk Approve (per avatar)
    # ------------------------------------------------------------------

    def bulk_approve(self, db: Session, user, avatar_username: str) -> dict:
        """Approve all pending drafts for a specific avatar."""
        from app.models.avatar import Avatar
        from app.models.comment_draft import CommentDraft
        from app.models.epg_slot import EPGSlot
        from app.services.epg_executor import _dispatch_email_task_if_enabled
        from app.services.transparency import record_activity_event
        import sqlalchemy as sa

        avatar = (
            db.query(Avatar)
            .filter(sa.func.lower(Avatar.reddit_username) == avatar_username.lower())
            .first()
        )
        if not avatar:
            return {"status": "error", "message": "Avatar not found"}

        # P7: verify access to avatar's client
        # Avatar may have multiple client_ids — check first one
        avatar_client_id = avatar.client_ids[0] if avatar.client_ids else None
        if avatar_client_id:
            from app.models.comment_draft import CommentDraft as CD
            # Build a fake draft-like object for access check
            class _FakeDraft:
                client_id = avatar_client_id
            if not _user_can_review_draft(db, user, _FakeDraft()):
                return {"status": "error", "message": "Access denied"}

        pending = (
            db.query(CommentDraft)
            .filter(CommentDraft.avatar_id == avatar.id, CommentDraft.status == "pending")
            .all()
        )

        if not pending:
            return {"approved": 0, "message": "No pending drafts"}

        approved_count = 0
        for draft in pending:
            draft.status = "approved"
            slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
            if slot:
                slot.status = "approved"
            approved_count += 1

        db.commit()

        # Create execution tasks for approved slots
        for draft in pending:
            try:
                slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft.id).first()
                if slot:
                    _dispatch_email_task_if_enabled(db, slot)
            except Exception:
                pass

        try:
            record_activity_event(
                db, "review",
                f"Bulk approved {approved_count} drafts via Telegram for u/{avatar_username}",
                avatar_client_id,
                {"avatar": avatar_username, "count": approved_count, "by": "telegram", "user_id": str(user.id)},
            )
        except Exception:
            pass

        return {"approved": approved_count, "failed": 0}

    # ------------------------------------------------------------------
    # Edit Session (LLM Regeneration)
    # ------------------------------------------------------------------

    def start_edit_session(
        self, db: Session, user, draft_id: str, chat_id: str, message_id: int
    ) -> str | None:
        """Start an edit session. Stores context in Redis. Returns full draft text."""
        from app.models.comment_draft import CommentDraft

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return None

        if not _user_can_review_draft(db, user, draft):
            return None

        # Store edit session in Redis
        session_key = f"{_EDIT_SESSION_PREFIX}{chat_id}:{message_id}"
        session_data = json.dumps({
            "draft_id": str(draft.id),
            "original_text": draft.body,
            "user_id": str(user.id),
        })
        self._redis.setex(session_key, _EDIT_SESSION_TTL, session_data)

        return draft.body

    def get_edit_session(self, chat_id: str, message_id: int) -> dict | None:
        """Retrieve edit session by reply_to_message_id."""
        session_key = f"{_EDIT_SESSION_PREFIX}{chat_id}:{message_id}"
        raw = self._redis.get(session_key)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    def cancel_edit_session(self, chat_id: str, message_id: int) -> None:
        """Cancel an active edit session (user sent /cancel)."""
        session_key = f"{_EDIT_SESSION_PREFIX}{chat_id}:{message_id}"
        self._redis.delete(session_key)

    def process_edit_reply(self, db: Session, user, draft_id: str, guidance_text: str) -> dict:
        """Regenerate draft via LLM with user guidance. Returns new text or error."""
        from app.models.comment_draft import CommentDraft
        from app.services.ai import call_llm, log_ai_usage

        draft = db.query(CommentDraft).filter(CommentDraft.id == draft_id).first()
        if not draft:
            return {"status": "error", "message": "Draft not found"}

        if not _user_can_review_draft(db, user, draft):
            return {"status": "error", "message": "Access denied"}

        # Build LLM context
        thread = draft.thread or getattr(draft, "hobby_post", None)
        thread_title = thread.title if thread else "Unknown"
        thread_body = (thread.body or "")[:500] if thread else ""

        model = get_config("llm_generation_model")
        original_text = draft.body

        messages = [
            {"role": "system", "content": EDIT_SYSTEM_PROMPT},
            {"role": "user", "content": f"""Original draft:
{original_text}

Thread context: "{thread_title}" in r/{thread.subreddit if thread else '?'}
{thread_body}

User's feedback/guidance:
{guidance_text}

Regenerate the comment incorporating the user's feedback. Keep the same voice and style as the original. Output ONLY the new comment text."""},
        ]

        try:
            result = call_llm(messages=messages, model=model, max_tokens=500)
            new_text = result.choices[0].message.content.strip()
        except Exception as e:
            logger.error("LLM regeneration failed for draft %s: %s", draft_id, e)
            return {"status": "error", "message": "Regeneration failed, please try again"}

        # Log AI usage (P3 compliance)
        try:
            log_ai_usage(
                db, draft.client_id, "telegram_draft_edit",
                result, model=model, triggered_by="telegram",
            )
        except Exception:
            pass

        # Update draft body
        draft.body = new_text
        db.commit()

        # Record edit for learning service
        try:
            from app.models.edit_record import EditRecord
            edit_record = EditRecord(
                avatar_id=draft.avatar_id,
                client_id=draft.client_id,
                draft_id=draft.id,
                original_text=original_text,
                edited_text=new_text,
                edit_source="telegram",
                guidance_text=guidance_text,
            )
            db.add(edit_record)
            db.commit()
        except Exception:
            pass  # Learning is non-critical

        return {"status": "regenerated", "new_text": new_text, "draft_id": str(draft.id)}

    # ------------------------------------------------------------------
    # Pending Query (for /pending command)
    # ------------------------------------------------------------------

    def get_pending_for_user(self, db: Session, user, limit: int = 5) -> list[dict]:
        """Get pending drafts for this user, grouped by client → avatar."""
        from app.models.comment_draft import CommentDraft
        from app.models.avatar import Avatar
        from app.models.client import Client
        import sqlalchemy as sa

        # Determine accessible client IDs
        client_ids = _get_accessible_client_ids(db, user)
        if not client_ids:
            return []

        # Query pending drafts
        query = (
            db.query(CommentDraft)
            .filter(
                CommentDraft.status == "pending",
                CommentDraft.client_id.in_(client_ids),
            )
            .order_by(CommentDraft.created_at.desc())
            .limit(limit)
        )
        drafts = query.all()

        results = []
        for draft in drafts:
            avatar = db.query(Avatar).filter(Avatar.id == draft.avatar_id).first()
            client = db.query(Client).filter(Client.id == draft.client_id).first()
            results.append({
                "draft": draft,
                "avatar_name": avatar.reddit_username if avatar else "?",
                "client_name": client.company_name if client else "?",
            })
        return results

    def get_pending_count_for_user(self, db: Session, user) -> int:
        """Get total pending draft count for this user."""
        from app.models.comment_draft import CommentDraft

        client_ids = _get_accessible_client_ids(db, user)
        if not client_ids:
            return 0

        return (
            db.query(CommentDraft)
            .filter(
                CommentDraft.status == "pending",
                CommentDraft.client_id.in_(client_ids),
            )
            .count()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_eligible_users(self, db: Session, client_id: str) -> list:
        """Find users eligible for Telegram draft review notifications for this client."""
        from app.models.user import User
        from app.models.user_client_assignment import UserClientAssignment

        # Users with telegram linked + appropriate notification level
        users = (
            db.query(User)
            .filter(
                User.telegram_chat_id.isnot(None),
                User.telegram_chat_id != "",
                User.is_active.is_(True),
            )
            .all()
        )

        eligible = []
        for user in users:
            # Check notification level (review = non-critical → needs "all" or "warning")
            level = user.telegram_notifications_level or "critical"
            if level in ("off", "critical"):
                continue

            # Check role allows review
            if user.role not in ("owner", "partner", "client_admin", "client_manager", "avatar_manager", "qa"):
                continue

            # Check access to this client
            if user.role in ("owner", "partner", "avatar_manager", "qa"):
                eligible.append(user)
            elif str(user.client_id) == str(client_id):
                eligible.append(user)
            else:
                # Check multi-client assignment
                assigned = (
                    db.query(UserClientAssignment.client_id)
                    .filter(
                        UserClientAssignment.user_id == user.id,
                        UserClientAssignment.is_active.is_(True),
                    )
                    .all()
                )
                if str(client_id) in {str(a.client_id) for a in assigned}:
                    eligible.append(user)

        return eligible

    def _record_failure(self, user_id: str, db: Session) -> None:
        """Record Telegram delivery failure. Clear chat_id after 3 consecutive failures."""
        key = f"{_FAIL_COUNTER_PREFIX}{user_id}"
        count = self._redis.incr(key)
        self._redis.expire(key, _FAIL_COUNTER_TTL)

        if count >= _MAX_CONSECUTIVE_FAILURES:
            try:
                from app.models.user import User
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    logger.warning(
                        "Clearing telegram_chat_id for user %s after %d consecutive failures",
                        user.email, count,
                    )
                    user.telegram_chat_id = None
                    db.commit()
            except Exception:
                pass


def _user_can_review_draft(db: Session, user, draft) -> bool:
    """Check if user has review access to this draft's client (P7 enforcement).

    Rules:
    - owner, partner, avatar_manager, qa → access to ALL clients
    - client_admin, client_manager → access only to their assigned client(s)
    - Other roles → no access
    """
    if user.role in ("owner", "partner", "avatar_manager", "qa"):
        return True
    if user.role in ("client_admin", "client_manager"):
        if str(user.client_id) == str(draft.client_id):
            return True
        from app.models.user_client_assignment import UserClientAssignment
        assigned = (
            db.query(UserClientAssignment.client_id)
            .filter(
                UserClientAssignment.user_id == user.id,
                UserClientAssignment.is_active.is_(True),
            )
            .all()
        )
        return str(draft.client_id) in {str(a.client_id) for a in assigned}
    return False


def _get_accessible_client_ids(db: Session, user) -> list[str]:
    """Get all client IDs this user can access."""
    if user.role in ("owner", "partner", "avatar_manager", "qa"):
        from app.models.client import Client
        clients = db.query(Client.id).filter(Client.is_active.is_(True)).all()
        return [str(c.id) for c in clients]
    elif user.role in ("client_admin", "client_manager"):
        ids = set()
        if user.client_id:
            ids.add(str(user.client_id))
        from app.models.user_client_assignment import UserClientAssignment
        assigned = (
            db.query(UserClientAssignment.client_id)
            .filter(
                UserClientAssignment.user_id == user.id,
                UserClientAssignment.is_active.is_(True),
            )
            .all()
        )
        ids.update(str(a.client_id) for a in assigned)
        return list(ids)
    return []
