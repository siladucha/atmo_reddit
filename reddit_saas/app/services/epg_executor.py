"""EPG Executor — generates comments for persisted EPG slots.

This is the bridge between EPG planning and LLM generation.
Each slot is generated independently: hobby via Flash, professional via Sonnet pipeline.

Key principle: generate_epg_slot() takes a slot_id and produces a CommentDraft.
It doesn't decide WHAT to generate — that's EPG's job. It only executes.
"""

from app.logging_config import get_logger
import uuid
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.hobby import HobbySubreddit
from app.models.thread import RedditThread

logger = get_logger(__name__)


def generate_epg_slot(db: Session, slot_id: uuid.UUID) -> CommentDraft | None:
    """Generate a comment for a single EPG slot.

    Handles both hobby and professional slots:
    - Hobby: inline Gemini Flash call (cheap, fast)
    - Professional: select_persona → generate_comment → edit_comment (Sonnet pipeline)

    Returns the created CommentDraft, or None if skipped.
    Updates slot status to 'generated' or 'skipped'.
    """
    slot = db.query(EPGSlot).filter(EPGSlot.id == slot_id).first()
    if not slot:
        logger.error(f"EPG slot {slot_id} not found")
        return None

    if slot.status != "planned":
        logger.info(f"EPG slot {slot_id} is not planned (status={slot.status}), skipping")
        return None

    avatar = db.query(Avatar).filter(Avatar.id == slot.avatar_id).first()
    if not avatar:
        _skip_slot(db, slot, "avatar_not_found")
        return None

    # Health gates
    if avatar.is_frozen:
        _skip_slot(db, slot, f"avatar_frozen: {avatar.freeze_reason or 'no reason'}")
        return None
    if avatar.health_status in ("shadowbanned", "suspended"):
        _skip_slot(db, slot, f"avatar_health: {avatar.health_status}")
        return None

    if slot.slot_type == "hobby":
        return _generate_hobby_slot(db, slot, avatar)
    elif slot.slot_type == "professional":
        return _generate_professional_slot(db, slot, avatar)
    else:
        _skip_slot(db, slot, f"unknown_slot_type: {slot.slot_type}")
        return None


def _generate_hobby_slot(db: Session, slot: EPGSlot, avatar: Avatar) -> CommentDraft | None:
    """Generate a hobby comment for an EPG slot."""
    from app.config import get_config
    from app.services.ai import call_llm_json, log_ai_usage

    # Find the hobby post
    hobby_post = db.query(HobbySubreddit).filter(HobbySubreddit.id == slot.hobby_post_id).first()
    if not hobby_post:
        _skip_slot(db, slot, "hobby_post_not_found")
        return None

    # Skip image-only posts — LLM cannot see images
    if not hobby_post.post_body or len(hobby_post.post_body.strip()) < 20:
        _skip_slot(db, slot, "image_only_post_no_text")
        return None

    # Already generated?
    if hobby_post.ai_comment:
        _skip_slot(db, slot, "hobby_already_generated")
        return None

    # Get previous comments for diversity
    previous = (
        db.query(CommentDraft.ai_draft)
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.ai_draft.isnot(None),
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(10)
        .all()
    )
    prev_comments = [p[0] for p in previous if p[0]]

    try:
        voice = avatar.voice_profile_md or "Casual, helpful community member"
        system_prompt = f"""You are writing a Reddit comment as a regular community member.
Your voice: {voice}

Rules:
- Be SHORT (20-60 words, max 80)
- Be genuine and helpful — this is a hobby subreddit
- No brand mentions, no marketing, no self-promotion
- Match the tone of the subreddit
- Never use em-dashes (—)
- IMPORTANT: Output ONLY valid JSON, no extra text

Previous comments (avoid repetition):
{chr(10).join(f'- {c[:80]}' for c in prev_comments[:5])}

Respond with a JSON object: {{"comment": "your comment text here"}}"""

        user_prompt = f"""Subreddit: r/{hobby_post.subreddit}
Post title: {hobby_post.post_title}
Post body: {(hobby_post.post_body or '')[:500]}
Upvotes: {hobby_post.post_ups or 0}"""

        gen_model = get_config("llm_scoring_model") or get_config("llm_generation_model")

        # call_llm_json handles retries and model fallback internally
        result = call_llm_json(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            model=gen_model,
            temperature=0.85,
            max_tokens=300,
        )

        log_ai_usage(
            db, None, "hobby_comment_epg", result,
            avatar_id=str(avatar.id),
            subreddit_name=hobby_post.subreddit,
        )

        data = result.get("data", {})
        comment_text = data.get("comment", result.get("content", ""))

        # Save to hobby post
        hobby_post.ai_comment = comment_text
        hobby_post.status = "pending"

        # Create CommentDraft
        draft_client_id = None
        if avatar.client_ids:
            draft_client_id = avatar.client_ids[0]

        draft = CommentDraft(
            id=uuid.uuid4(),
            thread_id=None,
            hobby_post_id=hobby_post.id,
            avatar_id=avatar.id,
            client_id=draft_client_id,
            type="hobby",
            ai_draft=comment_text,
            original_ai_draft=comment_text,
            status="pending",
            comment_approach="hobby_engagement",
        )
        db.add(draft)

        # Update slot
        slot.draft_id = draft.id
        slot.generated_at = datetime.now(timezone.utc)

        # Autopilot: auto-approve if client has autopilot_enabled
        if _should_auto_approve(db, slot.client_id, slot.avatar_id):
            slot.status = "approved"
            draft.status = "approved"
            logger.info(
                "EPG hobby slot AUTO-APPROVED (autopilot): avatar=%s sub=r/%s slot=%s",
                avatar.reddit_username, hobby_post.subreddit, slot.id,
            )
            # Commit draft+slot so create_execution_task can find them via DB query
            db.commit()
            _dispatch_email_task_if_enabled(db, slot)
        else:
            slot.status = "generated"
            db.commit()

        db.refresh(draft)

        # Audit: log successful generation for pipeline transparency
        _log_slot_generated(db, slot, avatar, hobby_post.subreddit)

        logger.info(
            "EPG hobby slot generated: avatar=%s sub=r/%s slot=%s status=%s",
            avatar.reddit_username, hobby_post.subreddit, slot.id, slot.status,
        )
        return draft

    except Exception as e:
        logger.error(f"EPG hobby generation failed: {e}")
        _skip_slot(db, slot, f"generation_error: {str(e)[:100]}")
        return None


def _generate_professional_slot(db: Session, slot: EPGSlot, avatar: Avatar) -> CommentDraft | None:
    """Generate a professional comment for an EPG slot using full Sonnet pipeline."""
    from app.services.generation import select_persona, generate_comment, edit_comment
    from app.services.safety import check_avatar_can_post, check_subreddit_limit

    thread = db.query(RedditThread).filter(RedditThread.id == slot.thread_id).first()
    if not thread:
        _skip_slot(db, slot, "thread_not_found")
        return None

    # Skip image-only posts — LLM cannot see images
    if not thread.post_body or len(thread.post_body.strip()) < 20:
        _skip_slot(db, slot, "image_only_post_no_text")
        return None

    # Liveness check
    if thread.is_locked:
        _skip_slot(db, slot, "thread_locked")
        return None

    from app.services.thread_liveness import check_and_filter_thread
    if not check_and_filter_thread(db, thread):
        _skip_slot(db, slot, "thread_locked_or_removed")
        return None

    # Client context
    client = db.query(Client).filter(Client.id == slot.client_id).first()
    if not client:
        _skip_slot(db, slot, "client_not_found")
        return None

    # Safety gate
    safety = check_avatar_can_post(
        db, avatar, "professional",
        target_subreddit=thread.subreddit,
        comment_text="",
        client=client,
    )
    if not safety:
        _skip_slot(db, slot, f"safety_blocked: {safety.reason}")
        return None

    sub_safety = check_subreddit_limit(db, avatar, thread.subreddit)
    if not sub_safety:
        _skip_slot(db, slot, f"subreddit_limit: {sub_safety.reason}")
        return None

    try:
        # Get all client avatars for persona selection
        all_avatars = (
            db.query(Avatar)
            .filter(Avatar.active.is_(True))
            .all()
        )
        client_avatars = [
            a for a in all_avatars
            if a.client_ids and str(client.id) in a.client_ids
            and not a.is_frozen
            and not a.is_shadowbanned
            and a.health_status not in ("shadowbanned", "suspended")
        ]

        # Persona selection (skip for single avatar)
        if len(client_avatars) <= 1:
            selection = {
                "persona_username": avatar.reddit_username,
                "mode": "helpful_peer",
                "thread_angle": "",
                "pov_opportunity": "",
                "selection_reasoning": "single avatar — skipped persona selection",
            }
        else:
            selection = select_persona(db, thread, client, client_avatars)
            # Use the selected avatar
            selected_username = selection.get("persona_username")
            selected = next(
                (a for a in client_avatars if a.reddit_username == selected_username),
                avatar,
            )
            avatar = selected

        # Get previous comments for diversity
        previous = (
            db.query(CommentDraft.ai_draft)
            .filter(
                CommentDraft.avatar_id == avatar.id,
                CommentDraft.ai_draft.isnot(None),
                CommentDraft.status.in_(["posted", "approved", "pending"]),
            )
            .order_by(CommentDraft.created_at.desc())
            .limit(20)
            .all()
        )
        prev_comments = [r[0] for r in previous if r[0]]

        # Generate comment (full pipeline: strategy + learning + approach diversity)
        draft = generate_comment(db, thread, client, avatar, selection, prev_comments)

        # Edit/clean
        edit_comment(db, draft, thread, client)

        # Update slot
        slot.draft_id = draft.id
        slot.generated_at = datetime.now(timezone.utc)

        # Autopilot: auto-approve if client has autopilot_enabled
        if _should_auto_approve(db, slot.client_id, slot.avatar_id):
            slot.status = "approved"
            draft.status = "approved"
            logger.info(
                "EPG pro slot AUTO-APPROVED (autopilot): avatar=%s sub=r/%s slot=%s",
                avatar.reddit_username, thread.subreddit, slot.id,
            )
            # Commit so create_execution_task can find the draft via DB query
            db.commit()
            _dispatch_email_task_if_enabled(db, slot)
        else:
            slot.status = "generated"
            db.commit()

        # Audit: log successful generation for pipeline transparency
        _log_slot_generated(db, slot, avatar, thread.subreddit)

        logger.info(
            "EPG pro slot generated: avatar=%s sub=r/%s thread='%s' slot=%s status=%s",
            avatar.reddit_username, thread.subreddit, thread.post_title[:40], slot.id, slot.status,
        )
        return draft

    except Exception as e:
        logger.error(f"EPG professional generation failed for slot {slot.id}: {e}")
        _skip_slot(db, slot, f"generation_error: {str(e)[:100]}")
        return None


def generate_all_planned_slots(
    db: Session,
    avatar_id: uuid.UUID,
    plan_date: date | None = None,
) -> int:
    """Generate comments for all planned slots of an avatar for a given day.

    Returns count of successfully generated slots.
    """
    if plan_date is None:
        plan_date = date.today()

    slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.avatar_id == avatar_id,
            EPGSlot.plan_date == plan_date,
            EPGSlot.status == "planned",
        )
        .order_by(EPGSlot.scheduled_at.asc().nullslast())
        .all()
    )

    generated = 0
    for slot in slots:
        result = generate_epg_slot(db, slot.id)
        if result:
            generated += 1

    logger.info(
        "generate_all_planned_slots: avatar=%s date=%s generated=%d/%d",
        avatar_id, plan_date, generated, len(slots),
    )
    return generated


def sync_slot_status(db: Session, draft_id: uuid.UUID, new_status: str) -> None:
    """Sync EPG slot status when a CommentDraft status changes.

    Called from review routes when approve/reject/posted happens.
    Maps draft status → slot status:
      approved → approved
      rejected → skipped (skip_reason = "rejected_by_reviewer")
      posted   → posted (posted_at = now)
    """
    slot = db.query(EPGSlot).filter(EPGSlot.draft_id == draft_id).first()
    if not slot:
        return  # Draft not linked to an EPG slot (legacy draft)

    if new_status == "approved":
        slot.status = "approved"
        # --- Email Task Delivery hook ---
        _dispatch_email_task_if_enabled(db, slot)
    elif new_status == "rejected":
        slot.status = "skipped"
        slot.skip_reason = "rejected_by_reviewer"
    elif new_status == "posted":
        slot.status = "posted"
        slot.posted_at = datetime.now(timezone.utc)

    # No commit here — caller is responsible for committing


def get_budget_used_today(db: Session, avatar_id: uuid.UUID, plan_date: date | None = None) -> int:
    """Count slots that consumed budget today.

    Budget is consumed by:
    - generated, approved, posted — successful generation
    - skipped WITH draft_id — generation succeeded but posting failed (still counts as slot used)
    - skipped WITHOUT draft_id but with generation_error — a failed LLM attempt (counts to prevent infinite retry loops)

    Only 'planned' slots are free (not yet attempted).
    """
    from sqlalchemy import func as sa_func

    if plan_date is None:
        plan_date = date.today()

    # Count slots that actually consumed budget:
    # - generated/approved/posted = successful generation
    # - skipped WITH draft_id = generation succeeded, posting failed
    # Skipped WITHOUT draft_id = never generated, does NOT consume budget
    from sqlalchemy import or_, and_

    count = (
        db.query(sa_func.count(EPGSlot.id))
        .filter(
            EPGSlot.avatar_id == avatar_id,
            EPGSlot.plan_date == plan_date,
            or_(
                EPGSlot.status.in_(["generated", "approved", "posted"]),
                and_(EPGSlot.status == "skipped", EPGSlot.draft_id.isnot(None)),
            ),
        )
        .scalar()
    )
    return count or 0


def _skip_slot(db: Session, slot: EPGSlot, reason: str) -> None:
    """Mark a slot as skipped with a reason."""
    slot.status = "skipped"
    slot.skip_reason = reason
    db.commit()
    logger.info(f"EPG slot {slot.id} skipped: {reason}")

    # Log generation errors to audit for admin visibility
    if "generation_error" in reason or "error" in reason.lower():
        try:
            from app.services.audit import log_system_action

            # Resolve avatar username for searchability in audit logs
            avatar_username = None
            try:
                avatar = db.query(Avatar).filter(Avatar.id == slot.avatar_id).first()
                avatar_username = avatar.reddit_username if avatar else None
            except Exception:
                pass

            log_system_action(
                db=db,
                action="generation_error",
                entity_type="epg_slot",
                entity_id=slot.id,
                client_id=slot.client_id,
                details={
                    "slot_id": str(slot.id),
                    "avatar_id": str(slot.avatar_id),
                    "avatar_username": avatar_username,
                    "thread_id": str(slot.thread_id) if slot.thread_id else None,
                    "reason": reason,
                },
            )
        except Exception:
            db.rollback()


def _should_auto_approve(db: Session, client_id: uuid.UUID | None, avatar_id: uuid.UUID | None = None) -> bool:
    """Check if client or avatar has auto-approve enabled.

    Auto-approve triggers if:
    - Client has autopilot_enabled=True (all avatars for that client), OR
    - Avatar has auto_approve_drafts=True (per-avatar override)
    """
    # Avatar-level override
    if avatar_id:
        try:
            from app.models.avatar import Avatar
            avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
            if avatar and avatar.auto_approve_drafts:
                return True
        except Exception:
            pass

    # Client-level autopilot
    if not client_id:
        return False
    try:
        from app.models.client import Client
        client = db.query(Client).filter(Client.id == client_id).first()
        return bool(client and client.autopilot_enabled)
    except Exception:
        return False


def _log_slot_generated(db: Session, slot: EPGSlot, avatar: Avatar, subreddit: str) -> None:
    """Log successful slot generation to audit for pipeline transparency."""
    try:
        from app.services.audit import log_system_action
        log_system_action(
            db=db,
            action="epg_slot_generated",
            entity_type="epg_slot",
            entity_id=slot.id,
            client_id=slot.client_id,
            details={
                "slot_id": str(slot.id),
                "avatar_id": str(slot.avatar_id),
                "avatar_username": avatar.reddit_username,
                "subreddit": subreddit,
                "slot_type": slot.slot_type,
                "status": slot.status,  # "generated" or "approved" (autopilot)
                "plan_date": str(slot.plan_date),
            },
        )
    except Exception:
        pass  # Non-critical — don't fail generation on audit error

def _dispatch_email_task_if_enabled(db, slot) -> None:
    """Create an execution task if email_tasks_enabled=true.

    The task is created with status='generated' but NOT delivered immediately.
    A separate Beat task (dispatch_due_email_tasks, every 5 min) handles actual
    email delivery ~30 min before slot.scheduled_at.

    This prevents email spam — executor gets ONE email at a time, close to when
    they need to act, not a batch dump at EPG generation time.

    Fire-and-forget: errors here never break the approval flow.
    """
    try:
        from app.services.settings import get_setting
        if get_setting(db, "email_tasks_enabled") != "true":
            return

        from app.services.execution_tasks import create_execution_task
        task = create_execution_task(db, slot.id)
        if task:
            db.commit()  # Ensure task is persisted
            # NOTE: No immediate deliver_execution_task.delay() here.
            # dispatch_due_email_tasks Beat task will send the email
            # ~30 min before slot.scheduled_at.
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(
            "Email task creation failed for slot %s (non-critical): %s", slot.id, e
        )
