"""Client Email Notifications — transactional emails to portal users.

Sends notifications about pending drafts, weekly reports, voice alerts.
Uses Brevo API via send_task_email().

Triggered by Celery tasks after EPG build or on schedule.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.user import User
from app.services.email_sender import send_task_email

logger = get_logger(__name__)


def notify_pending_drafts(db: Session, client_id: UUID) -> dict:
    """Send 'drafts waiting for review' email to client admins/managers.

    Only sends if:
    - Client has autopilot_enabled=False (otherwise drafts auto-approve)
    - There are pending drafts
    - At least one user with email exists for this client

    Returns dict with status and details.
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        return {"status": "skip", "reason": "client_not_found"}

    if client.autopilot_enabled:
        return {"status": "skip", "reason": "autopilot_enabled"}

    # Count pending drafts (fresh, last 24h)
    pending_count = (
        db.query(func.count(CommentDraft.id))
        .join(Avatar, CommentDraft.avatar_id == Avatar.id)
        .filter(
            Avatar.client_ids.any(str(client_id)),
            CommentDraft.status == "pending",
            Avatar.active.is_(True),
            Avatar.is_frozen.is_(False),
        )
        .scalar()
    ) or 0

    if pending_count == 0:
        return {"status": "skip", "reason": "no_pending_drafts"}

    # Find client users to notify (client_admin + client_manager)
    from app.models.user_role import UserRole
    users = (
        db.query(User)
        .filter(
            User.client_id == client_id,
            User.is_active.is_(True),
            User.email_verified.is_(True),
            User.role.in_([UserRole.client_admin.value, UserRole.client_manager.value, UserRole.owner.value, UserRole.partner.value]),
        )
        .all()
    )

    # Also include platform owners/partners (client_id=None) who manage all clients
    platform_admins = (
        db.query(User)
        .filter(
            User.client_id.is_(None),
            User.is_active.is_(True),
            User.email_verified.is_(True),
            User.role.in_([UserRole.owner.value, UserRole.partner.value]),
        )
        .all()
    )
    # Merge, dedup by email
    seen_emails = {u.email for u in users}
    for u in platform_admins:
        if u.email and u.email not in seen_emails:
            users.append(u)
            seen_emails.add(u.email)

    if not users:
        return {"status": "skip", "reason": "no_eligible_users"}

    # Build email
    portal_url = f"https://gorampit.com/clients/{client_id}/review"
    subject = f"📥 {pending_count} draft{'s' if pending_count != 1 else ''} waiting for your review — {client.client_name}"

    body_text = f"""Hi,

Your RAMP voices have generated {pending_count} new comment draft{'s' if pending_count != 1 else ''} for {client.client_name}.

Review and approve them here:
{portal_url}

Drafts that aren't reviewed within 48 hours are automatically expired to keep content fresh.

— RAMP
"""

    body_html = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 0;">
    <div style="margin-bottom: 24px;">
        <span style="font-size: 14px; color: #6B7280;">RAMP · {client.client_name}</span>
    </div>

    <h1 style="font-size: 20px; font-weight: 600; color: #1f2937; margin: 0 0 12px;">
        {pending_count} draft{'s' if pending_count != 1 else ''} waiting for review
    </h1>

    <p style="font-size: 15px; color: #4B5563; line-height: 1.6; margin: 0 0 24px;">
        Your voices have new comments ready. Approve, edit, or skip — takes about 2 minutes.
    </p>

    <a href="{portal_url}" style="display: inline-block; padding: 12px 24px; background: #2563C4; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600;">
        Review drafts →
    </a>

    <p style="font-size: 13px; color: #9CA3AF; margin-top: 24px; line-height: 1.5;">
        Drafts expire after 48 hours to keep content relevant.
        <br>You're receiving this because you manage {client.client_name} on RAMP.
    </p>
</div>
"""

    sent_count = 0
    for user in users:
        if not user.email:
            continue
        success, msg_id = send_task_email(
            to=user.email,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        if success:
            sent_count += 1
            logger.info("Pending drafts email sent: client=%s user=%s count=%d", client.client_name, user.email, pending_count)
        else:
            logger.warning("Failed to send drafts email: user=%s", user.email)

    return {"status": "sent", "pending_count": pending_count, "recipients": sent_count}


def notify_voice_alert(db: Session, client_id: UUID, avatar_id: UUID, reason: str) -> dict:
    """Send alert when a voice is paused/frozen.

    Args:
        reason: Human-readable reason (e.g. 'possible platform restriction detected')
    """
    client = db.query(Client).filter(Client.id == client_id).first()
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not client or not avatar:
        return {"status": "skip", "reason": "not_found"}

    voice_name = avatar.display_name or "A voice"
    portal_url = f"https://gorampit.com/clients/{client_id}/avatars/{avatar_id}"

    from app.models.user_role import UserRole
    users = (
        db.query(User)
        .filter(
            User.client_id == client_id,
            User.is_active.is_(True),
            User.email_verified.is_(True),
            User.role.in_([UserRole.client_admin.value, UserRole.client_manager.value, UserRole.owner.value, UserRole.partner.value]),
        )
        .all()
    )

    if not users:
        return {"status": "skip", "reason": "no_eligible_users"}

    subject = f"⚠️ {voice_name} has been paused — {client.client_name}"

    body_text = f"""Hi,

{voice_name} has been temporarily paused.
Reason: {reason}

Our team is investigating. No action needed from you — we'll update you when it's resolved.

View voice status: {portal_url}

— RAMP
"""

    body_html = f"""
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 520px; margin: 0 auto; padding: 32px 0;">
    <div style="margin-bottom: 24px;">
        <span style="font-size: 14px; color: #6B7280;">RAMP · {client.client_name}</span>
    </div>

    <h1 style="font-size: 20px; font-weight: 600; color: #1f2937; margin: 0 0 12px;">
        {voice_name} has been paused
    </h1>

    <p style="font-size: 15px; color: #4B5563; line-height: 1.6; margin: 0 0 8px;">
        <strong>Reason:</strong> {reason}
    </p>

    <p style="font-size: 15px; color: #4B5563; line-height: 1.6; margin: 0 0 24px;">
        Our team is investigating. No action needed from you — we'll notify you when it's resolved.
    </p>

    <a href="{portal_url}" style="display: inline-block; padding: 12px 24px; background: #6B7280; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px; font-weight: 600;">
        View voice status
    </a>

    <p style="font-size: 13px; color: #9CA3AF; margin-top: 24px;">
        You're receiving this because you manage {client.client_name} on RAMP.
    </p>
</div>
"""

    sent_count = 0
    for user in users:
        if not user.email:
            continue
        success, _ = send_task_email(to=user.email, subject=subject, body_text=body_text, body_html=body_html)
        if success:
            sent_count += 1

    return {"status": "sent", "voice": voice_name, "reason": reason, "recipients": sent_count}
