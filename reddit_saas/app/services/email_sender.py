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



def send_email_brevo_api(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    headers: dict[str, str] | None = None,
    reply_to: str | None = None,
) -> tuple[bool, str | None]:
    """Send email via Brevo HTTP API (port 443, bypasses DO SMTP block).

    Falls back to this when SMTP ports 587/465 are blocked (DigitalOcean default).
    Uses brevo_api_key from system_settings.

    Returns:
        Tuple of (success: bool, message_id: str | None)
    """
    import json
    import urllib.request
    import urllib.error

    from app.config import get_config

    api_key = get_config("brevo_api_key") or ""
    if not api_key:
        logger.error("Brevo API key not configured (brevo_api_key setting)")
        return False, None

    from_email = get_config("smtp_from_email") or "tasks@gorampit.com"
    from_name = get_config("smtp_from_name") or "RAMP Task System"

    payload: dict = {
        "sender": {"name": from_name, "email": from_email},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body_text,
    }

    if body_html:
        payload["htmlContent"] = body_html

    if reply_to:
        payload["replyTo"] = {"email": reply_to}

    if headers:
        payload["headers"] = headers

    url = "https://api.brevo.com/v3/smtp/email"
    req_headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        message_id = result.get("messageId", "")
        logger.info("Brevo email sent: to=%s subject=%s messageId=%s", to, subject[:80], message_id)
        return True, message_id
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:500]
        logger.error("Brevo API error %d: %s", e.code, body)
        return False, None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        logger.error("Brevo API connection error: %s", str(e)[:200])
        return False, None


# Default send function — tries Brevo API first (works on DO), falls back to SMTP
def send_task_email(
    to: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    headers: dict[str, str] | None = None,
    reply_to: str | None = None,
) -> tuple[bool, str | None]:
    """Send email using best available method.

    Priority: Brevo HTTP API (works on DO) → SMTP (if ports unblocked).
    """
    from app.config import get_config

    # Try Brevo API first (always works on DO)
    api_key = get_config("brevo_api_key")
    if api_key:
        return send_email_brevo_api(to, subject, body_text, body_html, headers, reply_to)

    # Fallback to SMTP (only works if ports are unblocked)
    return send_email(to, subject, body_text, body_html, headers, reply_to)
