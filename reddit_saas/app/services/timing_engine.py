"""Timing engine — calculates jittered posting times for EPG slots.

Applies ±30% jitter to scheduled times, enforces minimum intervals,
active hours, peak hour bias, and daily caps. All times are computed
in the avatar's declared timezone.

Usage:
    from app.services.timing_engine import (
        calculate_jittered_time,
        get_next_valid_posting_time,
        get_effective_daily_cap,
        is_within_active_hours,
    )
"""

from app.logging_config import get_logger
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.avatar import Avatar

logger = get_logger(__name__)

# --- Constants ---

ACTIVE_HOURS_START = 8   # 08:00 local
ACTIVE_HOURS_END = 23    # 23:00 local
SLEEP_HOURS_START = 0    # 00:00 local
SLEEP_HOURS_END = 7      # 07:00 local (never post)

MIN_INTERVAL_MINUTES = 45
JITTER_FACTOR = 0.30

# Peak hours get 2x weight when distributing posts across the day
PEAK_HOURS = [(12, 14), (18, 22)]

# Phase-based daily limits (from PhasePolicy)
PHASE_DAILY_LIMITS = {
    0: 0,   # Mentor — excluded from pipeline
    1: 3,   # Hobby only (CQS "lowest": 1)
    2: 7,   # Hobby + professional
    3: 18,  # Full brand integration
}

DEFAULT_TIMEZONE = "America/New_York"


# --- Public API ---


def is_safe_posting_time(
    subreddit_name: str, current_hour: int, db: Session
) -> bool:
    """Check if current hour is NOT in dangerous_hours for this subreddit.

    Uses cached SubredditRiskProfile data. If no profile exists or no
    dangerous_hours data, returns True (safe — fail-open).

    Args:
        subreddit_name: Subreddit to check.
        current_hour: Hour (0-23) in UTC.
        db: Database session.

    Returns:
        True if posting is safe (hour not in dangerous list), False otherwise.
    """
    from app.models.subreddit import Subreddit
    from app.models.subreddit_risk_profile import SubredditRiskProfile
    from sqlalchemy import func as sa_func

    subreddit_obj = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )
    if not subreddit_obj:
        return True  # no data = assume safe

    profile = (
        db.query(SubredditRiskProfile)
        .filter(SubredditRiskProfile.subreddit_id == subreddit_obj.id)
        .first()
    )
    if not profile or not profile.dangerous_hours:
        return True  # no data = assume safe

    return current_hour not in profile.dangerous_hours


def get_effective_daily_cap(avatar: Avatar, auto_posting_daily_cap: int = 8) -> int:
    """Calculate effective daily posting cap for an avatar.

    Returns min(phase_daily_limit, auto_posting_daily_cap).
    """
    phase_limit = PHASE_DAILY_LIMITS.get(avatar.warming_phase, 0)
    if avatar.warming_phase == 1 and avatar.cqs_level == "lowest":
        phase_limit = 1
    return min(phase_limit, auto_posting_daily_cap)


def calculate_jittered_time(
    scheduled_at: datetime,
    interval_minutes: float = 60.0,
    avatar_timezone: str = DEFAULT_TIMEZONE,
) -> datetime:
    """Apply ±30% jitter to scheduled time, clamped to active hours.

    Uses secrets.randbelow() for cryptographically secure randomness.

    Args:
        scheduled_at: The originally scheduled posting time (timezone-aware)
        interval_minutes: Interval between consecutive slots (for jitter range)
        avatar_timezone: Avatar's declared timezone string

    Returns:
        Jittered datetime, clamped to active hours in avatar's timezone
    """
    # Calculate jitter range: ±30% of interval
    max_jitter_seconds = int(interval_minutes * 60 * JITTER_FACTOR)

    if max_jitter_seconds > 0:
        # Generate random offset in range [-max_jitter, +max_jitter]
        jitter_range = max_jitter_seconds * 2
        jitter_seconds = secrets.randbelow(jitter_range + 1) - max_jitter_seconds
    else:
        jitter_seconds = 0

    jittered = scheduled_at + timedelta(seconds=jitter_seconds)

    # Clamp to active hours
    jittered = clamp_to_active_hours(jittered, avatar_timezone)

    return jittered


def get_next_valid_posting_time(
    avatar: Avatar,
    scheduled_at: datetime,
    last_posted_at: datetime | None = None,
    auto_posting_daily_cap: int = 8,
) -> datetime | None:
    """Calculate next valid posting time respecting all constraints.

    Returns None if:
    - Effective daily cap reached
    - No valid window remaining today
    - Avatar is in Phase 0

    Args:
        avatar: The avatar to schedule for
        scheduled_at: The desired posting time
        last_posted_at: When the avatar last posted (for min interval)
        auto_posting_daily_cap: System setting for max daily posts

    Returns:
        Valid posting datetime or None if not possible
    """
    tz_str = avatar.declared_timezone or DEFAULT_TIMEZONE
    tz = ZoneInfo(tz_str)

    # Phase 0 never posts
    if avatar.warming_phase == 0:
        return None

    # Check effective cap
    effective_cap = get_effective_daily_cap(avatar, auto_posting_daily_cap)
    if effective_cap <= 0:
        return None

    # Ensure scheduled_at is timezone-aware
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    # Convert to avatar's local time for active hours check
    local_time = scheduled_at.astimezone(tz)

    # If in sleep hours, defer to next active window
    if not is_within_active_hours(local_time):
        local_time = _next_active_start(local_time, tz)
        if local_time is None:
            return None

    # Enforce minimum interval from last post
    if last_posted_at:
        min_next = last_posted_at + timedelta(minutes=MIN_INTERVAL_MINUTES)
        if local_time < min_next.astimezone(tz):
            local_time = min_next.astimezone(tz)
            # Re-check active hours after adjustment
            if not is_within_active_hours(local_time):
                local_time = _next_active_start(local_time, tz)
                if local_time is None:
                    return None

    return local_time.astimezone(timezone.utc)


def is_within_active_hours(local_dt: datetime) -> bool:
    """Check if a local datetime falls within active posting hours (08:00-23:00)."""
    hour = local_dt.hour
    return ACTIVE_HOURS_START <= hour < ACTIVE_HOURS_END


def is_peak_hour(local_dt: datetime) -> bool:
    """Check if a local datetime falls within peak hours (2x weight)."""
    hour = local_dt.hour
    return any(start <= hour < end for start, end in PEAK_HOURS)


def should_dispatch_slot(
    avatar: Avatar,
    slot_scheduled_at: datetime,
    now: datetime | None = None,
) -> bool:
    """Determine if an EPG slot should be dispatched for posting now.

    Called by execute_pending_posts to decide whether to dispatch a task.
    Checks:
    - scheduled_at is in the past (slot is due)
    - Minimum interval since last post is respected

    Args:
        avatar: The avatar for this slot
        slot_scheduled_at: When the slot was scheduled
        now: Current time (defaults to utcnow)

    Returns:
        True if the slot should be dispatched now
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Ensure timezone-aware
    if slot_scheduled_at.tzinfo is None:
        slot_scheduled_at = slot_scheduled_at.replace(tzinfo=timezone.utc)

    # Slot must be due (scheduled time in the past)
    if slot_scheduled_at > now:
        return False

    # Minimum interval check
    if avatar.last_posted_at:
        min_next = avatar.last_posted_at + timedelta(minutes=MIN_INTERVAL_MINUTES)
        if now < min_next:
            return False

    return True


# --- Internal helpers ---


def clamp_to_active_hours(dt: datetime, avatar_timezone: str) -> datetime:
    """Clamp a datetime to active hours (08:00-23:00) in avatar's timezone.

    If the time falls in sleep hours (00:00-07:59), moves to 08:00 same day.
    If the time falls after 23:00, moves to 08:00 next day.
    """
    tz = ZoneInfo(avatar_timezone)

    # Convert to local
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(tz)

    hour = local.hour

    if hour < ACTIVE_HOURS_START:
        # Before 08:00 → move to 08:00 same day
        local = local.replace(hour=ACTIVE_HOURS_START, minute=0, second=0, microsecond=0)
    elif hour >= ACTIVE_HOURS_END:
        # After 23:00 → move to 08:00 next day
        local = (local + timedelta(days=1)).replace(
            hour=ACTIVE_HOURS_START, minute=0, second=0, microsecond=0
        )

    return local.astimezone(timezone.utc)


def _next_active_start(local_dt: datetime, tz: ZoneInfo) -> datetime | None:
    """Find the next active hours start from a given local time.

    Returns None if we've exhausted today and tomorrow (shouldn't happen in practice).
    """
    # If before active hours today, use today's start
    if local_dt.hour < ACTIVE_HOURS_START:
        return local_dt.replace(hour=ACTIVE_HOURS_START, minute=0, second=0, microsecond=0)

    # If after active hours, use tomorrow's start
    if local_dt.hour >= ACTIVE_HOURS_END:
        next_day = local_dt + timedelta(days=1)
        return next_day.replace(hour=ACTIVE_HOURS_START, minute=0, second=0, microsecond=0)

    # Already in active hours
    return local_dt


def generate_time_slots_for_day(
    count: int,
    avatar_timezone: str = DEFAULT_TIMEZONE,
    date: datetime | None = None,
) -> list[datetime]:
    """Generate evenly-spaced time slots across active hours with peak bias.

    Used by EPG to create initial scheduled_at values before jitter is applied.

    Args:
        count: Number of slots to generate
        avatar_timezone: Timezone for active hours calculation
        date: The date to generate slots for (defaults to today)

    Returns:
        List of timezone-aware datetimes (in UTC) distributed across active hours
    """
    if count <= 0:
        return []

    tz = ZoneInfo(avatar_timezone)

    if date is None:
        date = datetime.now(tz)

    # Active window: 08:00 to 23:00 = 15 hours = 900 minutes
    start = date.replace(hour=ACTIVE_HOURS_START, minute=0, second=0, microsecond=0)
    end = date.replace(hour=ACTIVE_HOURS_END, minute=0, second=0, microsecond=0)
    window_minutes = (end - start).total_seconds() / 60  # 900

    # Generate weighted time points (peak hours get 2x probability)
    # Simple approach: divide window into equal segments, then jitter
    interval = window_minutes / count

    slots = []
    for i in range(count):
        offset_minutes = interval * (i + 0.5)  # Center of each segment
        slot_time = start + timedelta(minutes=offset_minutes)

        # Add small random offset within segment (±25% of interval)
        segment_jitter = int(interval * 0.25 * 60)
        if segment_jitter > 0:
            jitter_sec = secrets.randbelow(segment_jitter * 2 + 1) - segment_jitter
            slot_time += timedelta(seconds=jitter_sec)

        # Ensure still within active hours
        if slot_time < start:
            slot_time = start
        if slot_time >= end:
            slot_time = end - timedelta(minutes=1)

        slots.append(slot_time.astimezone(timezone.utc))

    return slots
