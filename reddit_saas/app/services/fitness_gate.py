"""Fitness Gate service — pre-generation avatar-subreddit safety check.

Evaluates whether an avatar is safe to post in a specific subreddit based on:
- Extracted subreddit rules (min_karma, min_account_age, posting_frequency_limit)
- Moderation aggressiveness + karma thresholds
- Dangerous hours + karma thresholds

Returns a FitnessResult with pass/block decision and fitness score (0-100).

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10, 8.5
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.avatar import Avatar
from app.models.avatar_subreddit_compatibility import AvatarSubredditCompatibility
from app.models.comment_draft import CommentDraft
from app.models.subreddit import Subreddit
from app.models.subreddit_karma import SubredditKarma
from app.models.subreddit_risk_profile import SubredditRiskProfile
from app.models.thread import RedditThread
from app.services.transparency import record_activity_event

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FITNESS_KARMA_HEADROOM_MAX = 1000
FITNESS_AGE_HEADROOM_MAX_DAYS = 365

# Thresholds for moderation-based blocks
EXTREME_AGGRESSIVENESS_KARMA_THRESHOLD = 50  # Req 3.7
DANGEROUS_HOURS_KARMA_THRESHOLD = 200  # Req 3.8


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class FitnessResult:
    """Result of a fitness gate evaluation."""

    passed: bool
    score: int  # 0-100
    blocked_by: str | None  # rule name that blocked
    reason: str | None  # human-readable explanation


# ---------------------------------------------------------------------------
# Helper: parse threshold values from extracted rules
# ---------------------------------------------------------------------------


def _parse_days(value: str) -> int | None:
    """Parse a duration string like '30 days', '30d', '30' into days."""
    if not value:
        return None
    # Try to extract numeric part
    match = re.search(r"(\d+)", str(value))
    if match:
        return int(match.group(1))
    return None


def _parse_int(value: str) -> int | None:
    """Parse a numeric string like '500', '1000' into int."""
    if not value:
        return None
    match = re.search(r"(\d+)", str(value))
    if match:
        return int(match.group(1))
    return None


def _parse_frequency_limit(value: str) -> tuple[int, int] | None:
    """Parse frequency limit like '3 per day', '5/week', '3 per 24h'.

    Returns (max_posts, window_hours) or None if unparseable.
    """
    if not value:
        return None

    value_lower = str(value).lower().strip()

    # Try patterns like "3 per day", "3/day", "3 posts per day"
    match = re.search(r"(\d+)\s*(?:posts?\s*)?(?:per|/)\s*(\w+)", value_lower)
    if match:
        count = int(match.group(1))
        period = match.group(2)
        if period in ("day", "24h", "24hours"):
            return (count, 24)
        elif period in ("week", "7d", "7days"):
            return (count, 168)
        elif period in ("hour", "1h"):
            return (count, 1)
        elif period in ("12h", "12hours"):
            return (count, 12)
        # Default: assume daily
        return (count, 24)

    # Try just a number (assume per day)
    match = re.search(r"^(\d+)$", value_lower)
    if match:
        return (int(match.group(1)), 24)

    return None


# ---------------------------------------------------------------------------
# Helper: get rules from profile
# ---------------------------------------------------------------------------


def _get_rule_threshold(
    extracted_rules: list[dict], category: str
) -> str | None:
    """Get threshold_value for the first rule matching category."""
    for rule in extracted_rules:
        if rule.get("category") == category:
            return rule.get("threshold_value")
    return None


def _has_rule_category(extracted_rules: list[dict], category: str) -> bool:
    """Check if a rule with this category exists."""
    return any(r.get("category") == category for r in extracted_rules)


# ---------------------------------------------------------------------------
# Core: evaluate_fitness (Req 3.1-3.10)
# ---------------------------------------------------------------------------


def evaluate_fitness(
    db: Session,
    avatar: Avatar,
    subreddit_name: str,
    *,
    current_hour: int | None = None,
) -> FitnessResult:
    """Evaluate avatar-subreddit fitness. Returns pass/block decision.

    Checks (in order):
    1. Profile exists? (fail-open if not — Req 3.10)
    2. min_karma rule vs SubredditKarma.comment_karma (Req 3.2)
    3. min_account_age rule vs avatar.reddit_account_created (Req 3.3, 3.4)
    4. posting_frequency_limit vs recent post count (Req 3.5)
    5. Extreme aggressiveness + <50 karma -> block (Req 3.7)
    6. Dangerous hours + <200 karma -> block (Req 3.8)

    Returns FitnessResult with score (0-100) and block reason if any.
    """

    # --- Check 0: Subreddit ban (hard block, no fail-open) ---
    try:
        from app.services.subreddit_ban import get_banned_subreddits
        banned = get_banned_subreddits(db, avatar.id)
        if subreddit_name.lower() in banned:
            logger.info(
                "FITNESS_GATE | action=blocked | avatar=%s | subreddit=%s | reason=subreddit_ban",
                avatar.reddit_username, subreddit_name,
            )
            return FitnessResult(
                passed=False, score=0,
                blocked_by="subreddit_ban",
                reason=f"Avatar is banned from r/{subreddit_name}",
            )
    except Exception as e:
        logger.warning("fitness_gate subreddit_ban check failed: %s", str(e)[:100])
    # --- Load SubredditRiskProfile ---
    subreddit_obj = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name) == subreddit_name.lower())
        .first()
    )

    profile: SubredditRiskProfile | None = None
    if subreddit_obj:
        profile = (
            db.query(SubredditRiskProfile)
            .filter(SubredditRiskProfile.subreddit_id == subreddit_obj.id)
            .first()
        )

    # --- Check 1: fail-open if no profile (Req 3.10) ---
    if profile is None:
        logger.info(
            "FITNESS_GATE | action=fail_open | avatar=%s | subreddit=%s | reason=no_profile",
            avatar.reddit_username,
            subreddit_name,
        )
        record_activity_event(
            db,
            event_type="fitness_gate_warning",
            message=f"No risk profile for r/{subreddit_name} — allowing generation (fail-open)",
            metadata={
                "avatar": avatar.reddit_username,
                "subreddit": subreddit_name,
                "reason": "missing_risk_profile",
            },
        )
        return FitnessResult(passed=True, score=50, blocked_by=None, reason=None)

    # --- Load avatar's karma in this subreddit ---
    karma_record = (
        db.query(SubredditKarma)
        .filter(
            SubredditKarma.avatar_id == avatar.id,
            sa_func.lower(SubredditKarma.subreddit_name) == subreddit_name.lower(),
        )
        .first()
    )
    avatar_karma = karma_record.comment_karma if karma_record else 0

    # --- Extract rules ---
    extracted_rules = profile.extracted_rules or []

    # --- Check 2: min_karma (Req 3.2) ---
    min_karma_value = _get_rule_threshold(extracted_rules, "min_karma")
    if min_karma_value is not None:
        min_karma = _parse_int(min_karma_value)
        if min_karma is not None and avatar_karma < min_karma:
            result = FitnessResult(
                passed=False,
                score=0,
                blocked_by="min_karma",
                reason=f"Avatar karma ({avatar_karma}) < required ({min_karma}) in r/{subreddit_name}",
            )
            _emit_blocked_event(db, avatar, subreddit_name, result)
            _store_fitness_score(db, avatar, subreddit_name, result.score)
            return result

    # --- Check 3: min_account_age (Req 3.3, 3.4) ---
    min_age_value = _get_rule_threshold(extracted_rules, "min_account_age")
    if min_age_value is not None and avatar.reddit_account_created is not None:
        min_age_days = _parse_days(min_age_value)
        if min_age_days is not None:
            now = datetime.now(timezone.utc)
            account_age_days = (now - avatar.reddit_account_created).days
            if account_age_days < min_age_days:
                result = FitnessResult(
                    passed=False,
                    score=0,
                    blocked_by="min_account_age",
                    reason=f"Account age ({account_age_days}d) < required ({min_age_days}d) for r/{subreddit_name}",
                )
                _emit_blocked_event(db, avatar, subreddit_name, result)
                _store_fitness_score(db, avatar, subreddit_name, result.score)
                return result

    # --- Check 4: posting_frequency_limit (Req 3.5) ---
    freq_value = _get_rule_threshold(extracted_rules, "posting_frequency_limit")
    if freq_value is not None:
        parsed = _parse_frequency_limit(freq_value)
        if parsed is not None:
            max_posts, window_hours = parsed
            window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)

            # Count posted comments by this avatar in this subreddit within window
            posted_count = (
                db.query(sa_func.count(CommentDraft.id))
                .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
                .filter(
                    CommentDraft.avatar_id == avatar.id,
                    CommentDraft.status == "posted",
                    CommentDraft.posted_at >= window_start,
                    sa_func.lower(RedditThread.subreddit) == subreddit_name.lower(),
                )
                .scalar()
            ) or 0

            if posted_count >= max_posts:
                result = FitnessResult(
                    passed=False,
                    score=0,
                    blocked_by="posting_frequency_limit",
                    reason=f"Posted {posted_count} times in r/{subreddit_name} within {window_hours}h (limit: {max_posts})",
                )
                _emit_blocked_event(db, avatar, subreddit_name, result)
                _store_fitness_score(db, avatar, subreddit_name, result.score)
                return result

    # --- Check 5: Extreme aggressiveness + <50 karma (Req 3.7) ---
    moderation_profile = profile.moderation_profile or {}
    aggressiveness = moderation_profile.get("aggressiveness", "low")

    if aggressiveness == "extreme" and avatar_karma < EXTREME_AGGRESSIVENESS_KARMA_THRESHOLD:
        result = FitnessResult(
            passed=False,
            score=0,
            blocked_by="extreme_aggressiveness",
            reason=(
                f"Extreme moderation in r/{subreddit_name} and avatar karma ({avatar_karma}) "
                f"< {EXTREME_AGGRESSIVENESS_KARMA_THRESHOLD}"
            ),
        )
        _emit_blocked_event(db, avatar, subreddit_name, result)
        _store_fitness_score(db, avatar, subreddit_name, result.score)
        return result

    # --- Check 6: Dangerous hours + <200 karma (Req 3.8) ---
    dangerous_hours = profile.dangerous_hours or []
    if dangerous_hours and avatar_karma < DANGEROUS_HOURS_KARMA_THRESHOLD:
        # Determine current hour in subreddit's dominant timezone
        if current_hour is None:
            current_hour = _get_current_hour_in_timezone(profile.dominant_timezone)

        if current_hour in dangerous_hours:
            result = FitnessResult(
                passed=False,
                score=0,
                blocked_by="dangerous_hours",
                reason=(
                    f"Current hour ({current_hour}:00) is dangerous in r/{subreddit_name} "
                    f"and avatar karma ({avatar_karma}) < {DANGEROUS_HOURS_KARMA_THRESHOLD}"
                ),
            )
            _emit_blocked_event(db, avatar, subreddit_name, result)
            _store_fitness_score(db, avatar, subreddit_name, result.score)
            return result

    # --- All checks passed: compute fitness score (Req 3.9) ---
    score = _compute_fitness_score(
        extracted_rules=extracted_rules,
        avatar_karma=avatar_karma,
        avatar=avatar,
    )

    _store_fitness_score(db, avatar, subreddit_name, score)

    return FitnessResult(passed=True, score=score, blocked_by=None, reason=None)


# ---------------------------------------------------------------------------
# Batch evaluation (Req 8.5)
# ---------------------------------------------------------------------------


def batch_evaluate_fitness(
    db: Session,
    avatar: Avatar,
    thread_subreddit_pairs: list[tuple],
) -> list[FitnessResult]:
    """Evaluate multiple threads for a single avatar in one pass.

    Preloads SubredditKarma and SubredditRiskProfile in bulk
    to avoid N+1 queries. Max 50ms per thread.

    Args:
        db: Database session.
        avatar: The avatar being evaluated.
        thread_subreddit_pairs: List of (thread_id, subreddit_name) tuples.

    Returns:
        List of FitnessResult in the same order as input pairs.
    """
    if not thread_subreddit_pairs:
        return []

    # Collect unique subreddit names
    subreddit_names = list({pair[1].lower() for pair in thread_subreddit_pairs})

    # Preload SubredditKarma for this avatar in all relevant subreddits
    karma_records = (
        db.query(SubredditKarma)
        .filter(
            SubredditKarma.avatar_id == avatar.id,
            sa_func.lower(SubredditKarma.subreddit_name).in_(subreddit_names),
        )
        .all()
    )
    karma_map: dict[str, int] = {
        record.subreddit_name.lower(): record.comment_karma
        for record in karma_records
    }

    # Preload Subreddit records
    subreddit_records = (
        db.query(Subreddit)
        .filter(sa_func.lower(Subreddit.subreddit_name).in_(subreddit_names))
        .all()
    )
    subreddit_id_map: dict[str, Subreddit] = {
        s.subreddit_name.lower(): s for s in subreddit_records
    }

    # Preload SubredditRiskProfiles in bulk
    subreddit_ids = [s.id for s in subreddit_records]
    profiles = (
        db.query(SubredditRiskProfile)
        .filter(SubredditRiskProfile.subreddit_id.in_(subreddit_ids))
        .all()
    ) if subreddit_ids else []

    profile_map: dict[str, SubredditRiskProfile] = {}
    for p in profiles:
        sub = next(
            (s for s in subreddit_records if s.id == p.subreddit_id), None
        )
        if sub:
            profile_map[sub.subreddit_name.lower()] = p

    # Determine current hour once for all evaluations
    # Use the first profile's timezone, or UTC as fallback
    dominant_tz = "UTC"
    if profiles:
        dominant_tz = profiles[0].dominant_timezone or "UTC"
    current_hour = _get_current_hour_in_timezone(dominant_tz)

    # Evaluate each pair using preloaded data
    results: list[FitnessResult] = []
    for _thread_id, subreddit_name in thread_subreddit_pairs:
        sub_lower = subreddit_name.lower()
        profile = profile_map.get(sub_lower)

        if profile is None:
            # Fail-open (Req 3.10)
            logger.info(
                "FITNESS_GATE | action=batch_fail_open | avatar=%s | subreddit=%s",
                avatar.reddit_username,
                subreddit_name,
            )
            record_activity_event(
                db,
                event_type="fitness_gate_warning",
                message=f"No risk profile for r/{subreddit_name} — allowing generation (fail-open)",
                metadata={
                    "avatar": avatar.reddit_username,
                    "subreddit": subreddit_name,
                    "reason": "missing_risk_profile",
                },
            )
            results.append(FitnessResult(passed=True, score=50, blocked_by=None, reason=None))
            continue

        avatar_karma = karma_map.get(sub_lower, 0)
        extracted_rules = profile.extracted_rules or []

        # Check min_karma (Req 3.2)
        min_karma_value = _get_rule_threshold(extracted_rules, "min_karma")
        if min_karma_value is not None:
            min_karma = _parse_int(min_karma_value)
            if min_karma is not None and avatar_karma < min_karma:
                result = FitnessResult(
                    passed=False,
                    score=0,
                    blocked_by="min_karma",
                    reason=f"Avatar karma ({avatar_karma}) < required ({min_karma}) in r/{subreddit_name}",
                )
                _emit_blocked_event(db, avatar, subreddit_name, result)
                _store_fitness_score(db, avatar, subreddit_name, result.score)
                results.append(result)
                continue

        # Check min_account_age (Req 3.3, 3.4)
        min_age_value = _get_rule_threshold(extracted_rules, "min_account_age")
        if min_age_value is not None and avatar.reddit_account_created is not None:
            min_age_days = _parse_days(min_age_value)
            if min_age_days is not None:
                now = datetime.now(timezone.utc)
                account_age_days = (now - avatar.reddit_account_created).days
                if account_age_days < min_age_days:
                    result = FitnessResult(
                        passed=False,
                        score=0,
                        blocked_by="min_account_age",
                        reason=f"Account age ({account_age_days}d) < required ({min_age_days}d) for r/{subreddit_name}",
                    )
                    _emit_blocked_event(db, avatar, subreddit_name, result)
                    _store_fitness_score(db, avatar, subreddit_name, result.score)
                    results.append(result)
                    continue

        # Check posting_frequency_limit (Req 3.5)
        freq_value = _get_rule_threshold(extracted_rules, "posting_frequency_limit")
        if freq_value is not None:
            parsed = _parse_frequency_limit(freq_value)
            if parsed is not None:
                max_posts, window_hours = parsed
                window_start = datetime.now(timezone.utc) - timedelta(hours=window_hours)

                posted_count = (
                    db.query(sa_func.count(CommentDraft.id))
                    .join(RedditThread, CommentDraft.thread_id == RedditThread.id)
                    .filter(
                        CommentDraft.avatar_id == avatar.id,
                        CommentDraft.status == "posted",
                        CommentDraft.posted_at >= window_start,
                        sa_func.lower(RedditThread.subreddit) == sub_lower,
                    )
                    .scalar()
                ) or 0

                if posted_count >= max_posts:
                    result = FitnessResult(
                        passed=False,
                        score=0,
                        blocked_by="posting_frequency_limit",
                        reason=f"Posted {posted_count} times in r/{subreddit_name} within {window_hours}h (limit: {max_posts})",
                    )
                    _emit_blocked_event(db, avatar, subreddit_name, result)
                    _store_fitness_score(db, avatar, subreddit_name, result.score)
                    results.append(result)
                    continue

        # Check extreme aggressiveness (Req 3.7)
        moderation_profile = profile.moderation_profile or {}
        aggressiveness = moderation_profile.get("aggressiveness", "low")

        if aggressiveness == "extreme" and avatar_karma < EXTREME_AGGRESSIVENESS_KARMA_THRESHOLD:
            result = FitnessResult(
                passed=False,
                score=0,
                blocked_by="extreme_aggressiveness",
                reason=(
                    f"Extreme moderation in r/{subreddit_name} and avatar karma ({avatar_karma}) "
                    f"< {EXTREME_AGGRESSIVENESS_KARMA_THRESHOLD}"
                ),
            )
            _emit_blocked_event(db, avatar, subreddit_name, result)
            _store_fitness_score(db, avatar, subreddit_name, result.score)
            results.append(result)
            continue

        # Check dangerous hours (Req 3.8)
        dangerous_hours = profile.dangerous_hours or []
        if dangerous_hours and avatar_karma < DANGEROUS_HOURS_KARMA_THRESHOLD:
            # Use per-profile timezone for current hour
            profile_hour = _get_current_hour_in_timezone(profile.dominant_timezone or "UTC")
            if profile_hour in dangerous_hours:
                result = FitnessResult(
                    passed=False,
                    score=0,
                    blocked_by="dangerous_hours",
                    reason=(
                        f"Current hour ({profile_hour}:00) is dangerous in r/{subreddit_name} "
                        f"and avatar karma ({avatar_karma}) < {DANGEROUS_HOURS_KARMA_THRESHOLD}"
                    ),
                )
                _emit_blocked_event(db, avatar, subreddit_name, result)
                _store_fitness_score(db, avatar, subreddit_name, result.score)
                results.append(result)
                continue

        # All checks passed
        score = _compute_fitness_score(
            extracted_rules=extracted_rules,
            avatar_karma=avatar_karma,
            avatar=avatar,
        )
        _store_fitness_score(db, avatar, subreddit_name, score)
        results.append(FitnessResult(passed=True, score=score, blocked_by=None, reason=None))

    return results


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_current_hour_in_timezone(tz_name: str) -> int:
    """Get the current hour (0-23) in the specified timezone.

    Falls back to UTC if the timezone name is invalid.
    """
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tz_name)
        now = datetime.now(tz)
        return now.hour
    except Exception:
        # Fallback to UTC on invalid timezone
        return datetime.now(timezone.utc).hour


def _compute_fitness_score(
    extracted_rules: list[dict],
    avatar_karma: int,
    avatar: Avatar,
) -> int:
    """Compute fitness score (0-100) per Req 3.9.

    Weighted factors:
    - Rule compliance pass/fail count (40%)
    - Karma headroom above min_karma (30%)
    - Account age headroom above min_account_age (30%)
    """
    # --- Rule compliance (40%) ---
    # Count how many rule categories we can check and how many pass
    checkable_rules = 0
    passed_rules = 0

    min_karma_value = _get_rule_threshold(extracted_rules, "min_karma")
    if min_karma_value is not None:
        checkable_rules += 1
        min_karma = _parse_int(min_karma_value)
        if min_karma is not None and avatar_karma >= min_karma:
            passed_rules += 1

    min_age_value = _get_rule_threshold(extracted_rules, "min_account_age")
    if min_age_value is not None and avatar.reddit_account_created is not None:
        checkable_rules += 1
        min_age_days = _parse_days(min_age_value)
        if min_age_days is not None:
            account_age_days = (datetime.now(timezone.utc) - avatar.reddit_account_created).days
            if account_age_days >= min_age_days:
                passed_rules += 1

    # If there are other rule categories, count them as "passed" (not blocking)
    for rule in extracted_rules:
        cat = rule.get("category", "")
        if cat not in ("min_karma", "min_account_age", "posting_frequency_limit"):
            # Non-numeric rules — consider compliance as neutral (passed)
            checkable_rules += 1
            passed_rules += 1

    if checkable_rules > 0:
        compliance_score = (passed_rules / checkable_rules) * 100.0
    else:
        compliance_score = 100.0  # No rules to check = full compliance

    # --- Karma headroom (30%) ---
    min_karma = 0
    if min_karma_value is not None:
        parsed = _parse_int(min_karma_value)
        if parsed is not None:
            min_karma = parsed

    karma_headroom = avatar_karma - min_karma
    karma_headroom_score = min(
        100.0, max(0.0, (karma_headroom / FITNESS_KARMA_HEADROOM_MAX) * 100.0)
    )

    # --- Age headroom (30%) ---
    age_headroom_score = 100.0  # Default if no age check or no account_created
    if min_age_value is not None and avatar.reddit_account_created is not None:
        min_age_days = _parse_days(min_age_value) or 0
        account_age_days = (datetime.now(timezone.utc) - avatar.reddit_account_created).days
        age_headroom = account_age_days - min_age_days
        age_headroom_score = min(
            100.0, max(0.0, (age_headroom / FITNESS_AGE_HEADROOM_MAX_DAYS) * 100.0)
        )

    # --- Weighted total ---
    total = (
        compliance_score * 0.40
        + karma_headroom_score * 0.30
        + age_headroom_score * 0.30
    )

    return int(round(max(0.0, min(100.0, total))))


def _emit_blocked_event(
    db: Session,
    avatar: Avatar,
    subreddit_name: str,
    result: FitnessResult,
) -> None:
    """Emit fitness_gate_blocked activity event (Req 3.6)."""
    record_activity_event(
        db,
        event_type="fitness_gate_blocked",
        message=(
            f"Fitness gate blocked {avatar.reddit_username} in r/{subreddit_name}: "
            f"{result.blocked_by} — {result.reason}"
        ),
        metadata={
            "avatar": avatar.reddit_username,
            "subreddit": subreddit_name,
            "blocked_by": result.blocked_by,
            "reason": result.reason,
        },
    )
    logger.info(
        "FITNESS_GATE | action=blocked | avatar=%s | subreddit=%s | rule=%s",
        avatar.reddit_username,
        subreddit_name,
        result.blocked_by,
    )


def _store_fitness_score(
    db: Session,
    avatar: Avatar,
    subreddit_name: str,
    score: int,
) -> None:
    """Store fitness score on AvatarSubredditCompatibility (Req 3.9)."""
    try:
        record = (
            db.query(AvatarSubredditCompatibility)
            .filter(
                AvatarSubredditCompatibility.avatar_id == avatar.id,
                sa_func.lower(AvatarSubredditCompatibility.subreddit_name)
                == subreddit_name.lower(),
            )
            .first()
        )

        now = datetime.now(timezone.utc)

        if record:
            record.fitness_score = score
            record.fitness_computed_at = now
        else:
            # Create a new compatibility record with fitness score
            record = AvatarSubredditCompatibility(
                avatar_id=avatar.id,
                subreddit_name=subreddit_name,
                score=50,  # Default emotional compatibility (neutral)
                fitness_score=score,
                fitness_computed_at=now,
            )
            db.add(record)

        db.flush()
    except Exception as e:
        # Non-critical: don't block evaluation if storage fails
        logger.warning(
            "FITNESS_GATE | action=store_score_failed | avatar=%s | subreddit=%s | error=%s",
            avatar.reddit_username,
            subreddit_name,
            str(e),
        )
