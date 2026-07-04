"""Email verification and password reset token service.

Generates secure tokens, stores hashes in DB, sends emails via existing email_sender.
Tokens are URL-safe random strings (32 bytes = 43 chars base64url).
Only the SHA-256 hash of the token is stored in DB (prevents leak if DB is compromised).
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.user import User
from app.services.email_sender import send_task_email

logger = get_logger(__name__)

# Token validity periods
VERIFICATION_TOKEN_EXPIRES_HOURS = 48
PASSWORD_RESET_TOKEN_EXPIRES_HOURS = 1


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


# ---------------------------------------------------------------------------
# Email Verification
# ---------------------------------------------------------------------------


def create_verification_token(db: Session, user: User) -> str:
    """Generate a verification token, store hash in DB, return raw token."""
    token = _generate_token()
    user.verification_token_hash = _hash_token(token)
    user.verification_token_expires = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_EXPIRES_HOURS)
    db.commit()
    logger.info("Verification token created for user=%s email=%s", user.id, user.email)
    return token


def verify_email_token(db: Session, token: str) -> User | None:
    """Validate a verification token. Returns the user if valid, None otherwise."""
    token_hash = _hash_token(token)
    user = db.query(User).filter(
        User.verification_token_hash == token_hash,
    ).first()

    if not user:
        logger.warning("Verification token not found (invalid token)")
        return None

    if user.verification_token_expires and user.verification_token_expires < datetime.now(timezone.utc):
        logger.warning("Verification token expired for user=%s", user.id)
        return None

    # Mark as verified
    user.email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    user.verification_token_hash = None
    user.verification_token_expires = None
    db.commit()

    logger.info("Email verified for user=%s email=%s", user.id, user.email)
    return user


def send_verification_email(user: User, token: str) -> bool:
    """Send verification email with the token link."""
    base_url = _get_base_url()
    verify_url = f"{base_url}/verify-email?token={token}"

    subject = "Verify your email — RAMP"
    body_text = f"""Hi {user.full_name or 'there'},

Please verify your email address to activate your RAMP account.

Click this link to verify:
{verify_url}

This link expires in {VERIFICATION_TOKEN_EXPIRES_HOURS} hours.

If you didn't create an account, you can safely ignore this email.

— RAMP Team
"""

    body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1f2937;">
    <div style="text-align: center; margin-bottom: 32px;">
        <span style="font-size: 24px; font-weight: 700; color: #4f46e5;">RAMP</span>
    </div>
    <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 16px;">Verify your email</h2>
    <p style="color: #4b5563; line-height: 1.6;">Hi {user.full_name or 'there'},</p>
    <p style="color: #4b5563; line-height: 1.6;">Please verify your email address to activate your RAMP account and start the onboarding wizard.</p>
    <div style="text-align: center; margin: 32px 0;">
        <a href="{verify_url}" style="display: inline-block; background: #4f46e5; color: white; padding: 12px 32px; border-radius: 8px; text-decoration: none; font-weight: 500; font-size: 16px;">Verify Email Address</a>
    </div>
    <p style="color: #6b7280; font-size: 14px;">This link expires in {VERIFICATION_TOKEN_EXPIRES_HOURS} hours. If you didn't create an account, you can safely ignore this email.</p>
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">
    <p style="color: #9ca3af; font-size: 12px; text-align: center;">RAMP — Managed Reddit Engagement Platform</p>
</body>
</html>"""

    success, message_id = send_task_email(
        to=user.email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        headers={"X-RAMP-Type": "email-verification"},
    )

    if success:
        logger.info("Verification email sent to %s (message_id=%s)", user.email, message_id)
    else:
        logger.error("Failed to send verification email to %s", user.email)

    return success


def resend_verification(db: Session, user: User) -> bool:
    """Generate a new token and resend verification email."""
    if user.email_verified:
        return False
    token = create_verification_token(db, user)
    return send_verification_email(user, token)


# ---------------------------------------------------------------------------
# Password Reset
# ---------------------------------------------------------------------------


def create_password_reset_token(db: Session, user: User) -> str:
    """Generate a password reset token, store hash in DB, return raw token."""
    token = _generate_token()
    user.password_reset_token_hash = _hash_token(token)
    user.password_reset_token_expires = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRES_HOURS)
    db.commit()
    logger.info("Password reset token created for user=%s email=%s", user.id, user.email)
    return token


def validate_reset_token(db: Session, token: str) -> User | None:
    """Validate a password reset token. Returns the user if valid, None otherwise.

    Does NOT consume the token — call reset_password() to actually change the password.
    """
    token_hash = _hash_token(token)
    user = db.query(User).filter(
        User.password_reset_token_hash == token_hash,
    ).first()

    if not user:
        logger.warning("Password reset token not found (invalid token)")
        return None

    if user.password_reset_token_expires and user.password_reset_token_expires < datetime.now(timezone.utc):
        logger.warning("Password reset token expired for user=%s", user.id)
        return None

    return user


def reset_password(db: Session, token: str, new_password: str) -> User | None:
    """Validate token and set new password. Returns user on success, None on failure."""
    user = validate_reset_token(db, token)
    if not user:
        return None

    from app.services.auth import hash_password
    user.hashed_password = hash_password(new_password)
    user.password_reset_token_hash = None
    user.password_reset_token_expires = None
    db.commit()

    logger.info("Password reset completed for user=%s email=%s", user.id, user.email)
    return user


def send_password_reset_email(user: User, token: str) -> bool:
    """Send password reset email with the token link."""
    base_url = _get_base_url()
    reset_url = f"{base_url}/reset-password?token={token}"

    subject = "Reset your password — RAMP"
    body_text = f"""Hi {user.full_name or 'there'},

You requested a password reset for your RAMP account.

Click this link to set a new password:
{reset_url}

This link expires in {PASSWORD_RESET_TOKEN_EXPIRES_HOURS} hour(s).

If you didn't request this, you can safely ignore this email — your password will not change.

— RAMP Team
"""

    body_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #1f2937;">
    <div style="text-align: center; margin-bottom: 32px;">
        <span style="font-size: 24px; font-weight: 700; color: #4f46e5;">RAMP</span>
    </div>
    <h2 style="font-size: 20px; font-weight: 600; margin-bottom: 16px;">Reset your password</h2>
    <p style="color: #4b5563; line-height: 1.6;">Hi {user.full_name or 'there'},</p>
    <p style="color: #4b5563; line-height: 1.6;">You requested a password reset for your RAMP account. Click the button below to set a new password.</p>
    <div style="text-align: center; margin: 32px 0;">
        <a href="{reset_url}" style="display: inline-block; background: #4f46e5; color: white; padding: 12px 32px; border-radius: 8px; text-decoration: none; font-weight: 500; font-size: 16px;">Reset Password</a>
    </div>
    <p style="color: #6b7280; font-size: 14px;">This link expires in {PASSWORD_RESET_TOKEN_EXPIRES_HOURS} hour(s). If you didn't request this reset, you can safely ignore this email.</p>
    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0;">
    <p style="color: #9ca3af; font-size: 12px; text-align: center;">RAMP — Managed Reddit Engagement Platform</p>
</body>
</html>"""

    success, message_id = send_task_email(
        to=user.email,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        headers={"X-RAMP-Type": "password-reset"},
    )

    if success:
        logger.info("Password reset email sent to %s (message_id=%s)", user.email, message_id)
    else:
        logger.error("Failed to send password reset email to %s", user.email)

    return success
