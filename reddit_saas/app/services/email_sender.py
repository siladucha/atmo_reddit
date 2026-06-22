"""SMTP email sender — channel implementation for task delivery.

Sends emails via configured SMTP server (GoRampIT.com for production).
Uses stdlib only: smtplib + email.mime. No new dependencies.

Usage:
    from app.services.email_sender import send_email
    success, message_id = send_email(
        to="executor@example.com",
        subject="[RAMP Task] ...",
        body_text="...",
        body_html="<html>...</html>",
        headers={"X-RAMP-Task-ID": "abc123"},
    )
"""

import hashlib
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from app.logging_config import get_logger

logger = get_logger(__name__)


def _get_smtp_config() -> dict:
    """Load SMTP configuration from system_settings (DB)."""
    from app.config import get_config

    return {
        "host": get_config("smtp_host") or "",
        "port": int(get_config("smtp_port") or "587"),
        "user": get_config("smtp_user") or "",
        "password": get_config("smtp_password") or "",
        "from_email": get_config("smtp_from_email") or "tasks@gorampit.com",
        "from_name": get_config("smtp_from_name") or "RAMP Task System",
        "use_tls": (get_config("smtp_use_tls") or "true").lower() in ("true", "1"),
    }


def send_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    headers: dict[str, str] | None = None,
    reply_to: str | None = None,
) -> tuple[bool, str | None]:
    """Send an email via SMTP.

    Args:
        to: Recipient email address
        subject: Email subject line
        body_text: Plain text body (required)
        body_html: Optional HTML body (multipart/alternative if provided)
        headers: Optional custom headers (e.g. X-RAMP-Task-ID)
        reply_to: Optional Reply-To address

    Returns:
        Tuple of (success: bool, message_id: str | None)
        message_id is the SMTP Message-ID header value on success.
    """
    config = _get_smtp_config()

    if not config["host"]:
        logger.error("SMTP not configured: smtp_host is empty")
        return False, None

    if not config["user"] or not config["password"]:
        logger.error("SMTP not configured: smtp_user or smtp_password is empty")
        return False, None

    # Build message
    if body_html:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
    else:
        msg = MIMEText(body_text, "plain", "utf-8")

    message_id = make_msgid(domain=config["from_email"].split("@")[-1] if "@" in config["from_email"] else "gorampit.com")

    msg["From"] = formataddr((config["from_name"], config["from_email"]))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id

    if reply_to:
        msg["Reply-To"] = reply_to

    # Custom headers
    if headers:
        for key, value in headers.items():
            msg[key] = value

    # Send
    try:
        if config["use_tls"] and config["port"] == 465:
            # Direct SSL (port 465)
            server = smtplib.SMTP_SSL(config["host"], config["port"], timeout=30)
        else:
            # STARTTLS (port 587) or plain
            server = smtplib.SMTP(config["host"], config["port"], timeout=30)
            if config["use_tls"]:
                server.starttls()

        server.login(config["user"], config["password"])
        server.sendmail(config["from_email"], [to], msg.as_string())
        server.quit()

        logger.info(
            "Email sent: to=%s subject=%s message_id=%s",
            to, subject[:80], message_id,
        )
        return True, message_id

    except smtplib.SMTPAuthenticationError as e:
        logger.error("SMTP auth failed: %s", str(e)[:200])
        return False, None
    except smtplib.SMTPRecipientsRefused as e:
        logger.error("SMTP recipient refused: to=%s error=%s", to, str(e)[:200])
        return False, None
    except smtplib.SMTPException as e:
        logger.error("SMTP error: %s", str(e)[:200])
        return False, None
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error("SMTP connection error: %s", str(e)[:200])
        return False, None


def compute_payload_hash(body_text: str) -> str:
    """Compute SHA-256 hash of email body for dedup/audit."""
    return hashlib.sha256(body_text.encode("utf-8")).hexdigest()
