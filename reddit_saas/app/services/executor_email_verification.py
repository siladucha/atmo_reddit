"""Executor email verification service.

Sends a verification email to the avatar's executor when their email is set or changed.
Until verified, no execution tasks (email or CQS) are created for the avatar.

Pattern mirrors app/services/email_verification.py but targets Avatar.executor_email.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.services.email_sender import send_task_email

logger = get_logger(__name__)

EXECUTOR_VERIFICATION_TOKEN_EXPIRES_HOURS = 72  # 3 days — executor may be slow


def _generate_token() -> str:
    """Generate a URL-safe random token (32 bytes = 43 chars)."""
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    """SHA-256 hash of the token for DB storage."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _get_base_url() -> str:
    """Return base URL for links in emails."""
    from app.config import get_config
    base_url = get_config("base_url")
    if base_url:
        return base_url.rstrip("/")
    return "https://gorampit.com"


def create_executor_verification_token(db: Session, avatar: Avatar) -> str:
    """Generate a verification token for executor email, store hash on Avatar."""
    token = _generate_token()
    avatar.executor_verification_token_hash = _hash_token(token)
    avatar.executor_verification_token_expires = datetime.now(timezone.utc) + timedelta(
        hours=EXECUTOR_VERIFICATION_TOKEN_EXPIRES_HOURS
    )
    db.commit()
    logger.info(
        "Executor verification token created for avatar=%s email=%s",
        avatar.reddit_username,
        avatar.executor_email,
    )
    return token


def verify_executor_email_token(db: Session, token: str) -> Avatar | None:
    """Validate an executor verification token. Returns the Avatar if valid, None otherwise."""
    token_hash = _hash_token(token)
    avatar = db.query(Avatar).filter(
        Avatar.executor_verification_token_hash == token_hash,
    ).first()

    if not avatar:
        logger.warning("Executor verification token not found (invalid token)")
        return None

    if avatar.executor_verification_token_expires and avatar.executor_verification_token_expires < datetime.now(timezone.utc):
        logger.warning("Executor verification token expired for avatar=%s", avatar.reddit_username)
        return None

    # Mark as verified
    avatar.executor_email_verified = True
    avatar.executor_verification_token_hash = None
    avatar.executor_verification_token_expires = None
    db.commit()

    logger.info(
        "Executor email verified for avatar=%s email=%s",
        avatar.reddit_username,
        avatar.executor_email,
    )
    return avatar


def send_executor_verification_email(avatar: Avatar, token: str) -> bool:
    """Send verification email to the executor."""
    if not avatar.executor_email:
        return False

    base_url = _get_base_url()
    verify_url = f"{base_url}/verify-executor-email?token={token}"
    avatar_name = avatar.display_name or avatar.reddit_username or "an avatar"

    subject = "Verify your email — RAMP Task Delivery"
    body_text = f"""Hi,

You've been assigned as the executor for {avatar_name} on RAMP.

Please verify your email address so we can send you posting tasks.

Click this link to verify:
{verify_url}

This link expires in {EXECUTOR_VERIFICATION_TOKEN_EXPIRES_HOURS} hours.

If you didn't expect this email, you can safely ignore it.

— RAMP Team
"""

    body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1f2937;">
    <div style="text-align: center; margin-bottom: 32px;">
        <span style="font-size: 24px; font-weight: 700; color: #4f46e5;">RAMP</span>
    </div>
    <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 16px;">Verify your email for task delivery</h2>
    <p style="color: #4b5563; line-height: 1.6;">Hi,</p>
    <p style="color: #4b5563; line-height: 1.6;">You've been assigned as the executor for <strong>{avatar_name}</strong> on RAMP. Please verify your email so we can send you posting tasks.</p>
    <div style="text-align: center; margin: 32px 0;">
        <a href="{verify_url}" style="display: inline-block; background: #4f46e5; color: white; padding: 12px 32px; border-radius: 8px; text-decoration: none; font-weight: 500; font-size: 16px;">Verify Email Address</a>
    </div>
    <p style="color: #6b7280; font-size: 14px;">This link expires in {EXECUTOR_VERIFICATION_TOKEN_EXPIRES_HOURS} hours. If you didn't expect this, you can safely ignore it.</p>
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">
    <p style="color: #9ca3af; font-size: 12px; text-align: center;">RAMP — Managed Reddit Engagement Platform</p>
</body>
</html>"""

    success, message_id = send_task_email(
        to=avatar.executor_email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        headers={"X-RAMP-Type": "executor-email-verification"},
    )

    if success:
        logger.info(
            "Executor verification email sent to %s for avatar=%s (message_id=%s)",
            avatar.executor_email,
            avatar.reddit_username,
            message_id,
        )
    else:
        logger.error(
            "Failed to send executor verification email to %s for avatar=%s",
            avatar.executor_email,
            avatar.reddit_username,
        )

    return success


def send_executor_verification(db: Session, avatar: Avatar) -> bool:
    """Generate token and send verification email. Returns True on success."""
    if not avatar.executor_email:
        return False
    if avatar.executor_email_verified:
        return False
    token = create_executor_verification_token(db, avatar)
    return send_executor_verification_email(avatar, token)
