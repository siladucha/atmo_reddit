"""Posting safety gates — pre-posting validation checks.

All checks run BEFORE any Reddit API call. If any check fails, the post
is refused and the reason is logged. Checks are ordered from cheapest to
most expensive (DB queries, then network calls).

Usage:
    result = check_posting_safety(db, avatar, epg_slot)
    if not result.allowed:
        log(result.reason)
        return
"""

import hashlib
import ipaddress
import logging
import re
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.epg_slot import EPGSlot
from app.models.posting_event import PostingEvent

logger = logging.getLogger(__name__)


@dataclass
class SafetyResult:
    """Result of safety gate evaluation."""
    allowed: bool
    reason: str = ""


def check_posting_safety(
    db: Session,
    avatar: Avatar,
    epg_slot: EPGSlot,
    resolved_ip: str | None = None,
) -> SafetyResult:
    """Run all pre-posting safety checks in order.

    Checks (cheapest first):
    1. Global kill switch (auto_posting_enabled)
    2. Avatar posting_mode == 'auto'
    3. Avatar not frozen
    4. Avatar health_status not in (shadowbanned, suspended)
    5. Phase 0 (Mentor) excluded
    6. Daily post count < effective cap
    7. Proxy URL configured
    8. User-agent string configured
    9. IP subnet consistency (/24 check)

    Phase policy (brand mentions, subreddit restrictions) is checked separately
    by PhasePolicy.check_comment_allowed() in the posting service — it needs
    the actual comment text which isn't available here.

    Args:
        db: Database session
        avatar: The avatar attempting to post
        epg_slot: The EPG slot being posted
        resolved_ip: The resolved proxy exit IP (if already resolved)

    Returns:
        SafetyResult with allowed=True or allowed=False + reason
    """
    # 0. Environment-level kill switch (cannot be toggled from admin UI)
    from app.config import get_settings
    if get_settings().posting_disabled:
        return SafetyResult(False, "Posting disabled at environment level (POSTING_DISABLED=true)")

    # 1. Global kill switch
    from app.services.settings import get_setting
    auto_posting_enabled = get_setting(db, "auto_posting_enabled")
    if auto_posting_enabled in ("false", "False", "0", False):
        return SafetyResult(False, "Global kill switch: auto_posting_enabled is disabled")

    # 2. Avatar posting mode
    if avatar.posting_mode != "auto":
        return SafetyResult(False, f"Avatar posting_mode is '{avatar.posting_mode}', not 'auto'")

    # 3. Avatar frozen
    if avatar.is_frozen:
        return SafetyResult(False, f"Avatar is frozen: {avatar.freeze_reason or 'no reason'}")

    # 4. Health status
    if avatar.health_status in ("shadowbanned", "suspended"):
        return SafetyResult(False, f"Avatar health_status is '{avatar.health_status}'")

    # 5. Phase 0 (Mentor) excluded from automated posting
    if avatar.warming_phase == 0:
        return SafetyResult(False, "Phase 0 (Mentor): excluded from automated posting")

    # 6. Daily cap check
    effective_cap = get_effective_daily_cap(db, avatar)
    today_count = get_today_post_count(db, avatar)
    if today_count >= effective_cap:
        return SafetyResult(
            False,
            f"Daily cap reached: {today_count}/{effective_cap} (phase={avatar.warming_phase})"
        )

    # 7. Proxy URL configured
    if not avatar.proxy_url_encrypted:
        return SafetyResult(False, "Proxy URL not configured (proxy_url_encrypted is empty)")

    # 8. User-agent configured
    if not avatar.user_agent_string:
        return SafetyResult(False, "User-agent string not configured")

    # 9. IP subnet consistency
    if resolved_ip and avatar.last_posted_ip:
        if not is_same_subnet(resolved_ip, avatar.last_posted_ip):
            return SafetyResult(
                False,
                f"IP subnet changed: {resolved_ip} vs last {avatar.last_posted_ip} (different /24)"
            )

    return SafetyResult(True)


# --- Helper functions ---


def get_effective_daily_cap(db: Session, avatar: Avatar) -> int:
    """Calculate effective daily posting cap: min(phase_limit, system_cap).

    Phase limits:
        Phase 0: 0 (Mentor, excluded)
        Phase 1: 3 (CQS "lowest": 1)
        Phase 2: 7
        Phase 3: 18
    """
    from app.services.settings import get_setting

    PHASE_DAILY_LIMITS = {0: 0, 1: 3, 2: 7, 3: 18}

    phase_limit = PHASE_DAILY_LIMITS.get(avatar.warming_phase, 0)
    if avatar.warming_phase == 1 and avatar.cqs_level == "lowest":
        phase_limit = 1

    # System setting cap (default 8)
    try:
        system_cap = int(get_setting(db, "auto_posting_daily_cap") or 8)
    except (ValueError, TypeError):
        system_cap = 8

    return min(phase_limit, system_cap)


def get_today_post_count(db: Session, avatar: Avatar) -> int:
    """Count successful posts today for this avatar."""
    from datetime import datetime, timezone

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = (
        db.query(func.count(PostingEvent.id))
        .filter(
            PostingEvent.avatar_id == avatar.id,
            PostingEvent.outcome == "success",
            PostingEvent.posted_at >= today_start,
        )
        .scalar()
    )
    return count or 0


def is_same_subnet(ip1: str, ip2: str, prefix_length: int = 24) -> bool:
    """Check if two IPs are in the same /24 subnet.

    Allows normal residential proxy IP rotation within the same provider block.
    """
    try:
        net1 = ipaddress.ip_network(f"{ip1}/{prefix_length}", strict=False)
        net2 = ipaddress.ip_network(f"{ip2}/{prefix_length}", strict=False)
        return net1.network_address == net2.network_address
    except (ValueError, TypeError):
        # If IPs are malformed, fail open (don't block posting for bad data)
        logger.warning("Could not compare IPs: %s vs %s", ip1, ip2)
        return True


def validate_proxy_url(url: str) -> tuple[bool, str]:
    """Validate proxy URL format.

    Accepts: socks5://user:pass@host:port or http://user:pass@host:port
    Returns: (valid: bool, error_message: str)
    """
    if not url:
        return False, "Proxy URL is empty"

    if not (url.startswith("socks5://") or url.startswith("http://")):
        return False, "Proxy URL must start with 'socks5://' or 'http://'"

    # Basic structure check: scheme://[user:pass@]host:port
    pattern = r'^(socks5|http)://([^:]+:[^@]+@)?[\w\.\-]+:\d+$'
    if not re.match(pattern, url):
        return False, "Proxy URL format invalid. Expected: scheme://[user:pass@]host:port"

    return True, ""


def redact_proxy_url(url: str) -> str:
    """Redact credentials from proxy URL for logging.

    socks5://user:pass@1.2.3.4:1080 → socks5://***:***@1.2.3.4:1080
    """
    if not url:
        return ""
    # Replace user:pass@ with ***:***@
    return re.sub(r'://[^:]+:[^@]+@', '://***:***@', url)


def hash_proxy_url(url: str) -> str:
    """SHA-256 hash of proxy URL for audit correlation without exposing credentials."""
    if not url:
        return ""
    return hashlib.sha256(url.encode()).hexdigest()
