"""Signal Validator — normalizes raw extension probe results into structured data.

Processes untrusted raw reports from browser extension execution nodes.
Extracts meaningful data (CQS level, visibility, karma) from raw text/JSON
and assigns confidence scores.

This is the normalization layer between extension reports (raw, untrusted)
and backend state transitions (validated, authoritative).

Extension reports raw output only — all interpretation happens here.
"""

import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.activity_event import ActivityEvent

logger = get_logger(__name__)

# CQS level extraction patterns — ordered by specificity/confidence.
# Clear match (0.95 confidence): exact AutoModerator format
# Fuzzy match (0.7 confidence): recognizable CQS format but non-standard
# Ambiguous (0.3 confidence): level keyword found in text but context unclear

# Pattern tier 1 — exact AutoModerator format (confidence: 0.95)
CQS_EXACT_PATTERNS = [
    # "Your current CQS is **LOW**." or "Your current CQS is LOW."
    re.compile(
        r"your\s+current\s+cqs\s+is\s+\*{0,2}(\w+)\*{0,2}",
        re.IGNORECASE,
    ),
]

# Pattern tier 2 — recognizable CQS format (confidence: 0.7)
CQS_FUZZY_PATTERNS = [
    # "CQS: Low" or "CQS:Low"
    re.compile(r"\bCQS\s*:\s*\*{0,2}(\w+)\*{0,2}", re.IGNORECASE),
    # "CQS level: MEDIUM" or "CQS level MEDIUM"
    re.compile(r"\bCQS\s+level\s*:?\s*\*{0,2}(\w+)\*{0,2}", re.IGNORECASE),
    # "CQS is LOW" (without "your current")
    re.compile(r"\bCQS\s+is\s+\*{0,2}(\w+)\*{0,2}", re.IGNORECASE),
]

# Pattern tier 3 — ambiguous (confidence: 0.3)
# Just the level word near "CQS" in the text
CQS_AMBIGUOUS_PATTERN = re.compile(
    r"\bCQS\b.*?\b(lowest|low|medium|high)\b", re.IGNORECASE
)

VALID_CQS_LEVELS = {"lowest", "low", "medium", "high"}


def normalize_probe_result(probe_type: str, raw_output: str) -> dict:
    """Normalize raw extension probe output into structured data.

    Extension reports raw text/JSON from Reddit. This function extracts
    meaningful signals and assigns confidence scores.

    Args:
        probe_type: Type of probe that produced this output.
            One of: "reddit_cqs", "submission_visibility", "profile_check".
        raw_output: Raw text or JSON string from the extension.

    Returns:
        Dict with normalized data. Always includes "confidence".
        Structure depends on probe_type:
        - reddit_cqs: {cqs_level, confidence, raw_text}
        - submission_visibility: {visible, confidence}
        - profile_check: {comment_karma, link_karma, ban_indicators, confidence}
        - unknown: {error, confidence}
    """
    if probe_type == "reddit_cqs":
        return _normalize_cqs(raw_output)
    elif probe_type == "submission_visibility":
        return _normalize_visibility(raw_output)
    elif probe_type == "profile_check":
        return _normalize_profile(raw_output)
    else:
        logger.warning(
            "SIGNAL_VALIDATOR | unknown_probe_type=%s | raw_len=%d",
            probe_type,
            len(raw_output) if raw_output else 0,
        )
        return {"error": "unknown_probe_type", "confidence": 0.0}


def _normalize_cqs(raw_output: str) -> dict:
    """Extract CQS level from AutoModerator reply text.

    Handles multiple bot reply formats with tiered confidence:
      - 0.95: exact AutoModerator format ("Your current CQS is **LOW**.")
      - 0.70: recognizable CQS format ("CQS: Low", "CQS level: MEDIUM")
      - 0.30: ambiguous (CQS keyword + level word found nearby)

    Returns:
        Dict with cqs_level, confidence, and raw_text.
    """
    if not raw_output:
        return {"error": "parse_failed", "confidence": 0.0, "raw_text": ""}

    # Tier 1: exact AutoModerator format (highest confidence)
    for pattern in CQS_EXACT_PATTERNS:
        match = pattern.search(raw_output)
        if match:
            level = match.group(1).lower()
            if level in VALID_CQS_LEVELS:
                return {
                    "cqs_level": level,
                    "confidence": 0.95,
                    "raw_text": raw_output,
                }

    # Tier 2: recognizable CQS format (fuzzy confidence)
    for pattern in CQS_FUZZY_PATTERNS:
        match = pattern.search(raw_output)
        if match:
            level = match.group(1).lower()
            if level in VALID_CQS_LEVELS:
                return {
                    "cqs_level": level,
                    "confidence": 0.7,
                    "raw_text": raw_output,
                }

    # Tier 3: ambiguous — CQS mentioned + level word found
    match = CQS_AMBIGUOUS_PATTERN.search(raw_output)
    if match:
        level = match.group(1).lower()
        if level in VALID_CQS_LEVELS:
            logger.info(
                "SIGNAL_VALIDATOR | cqs_ambiguous_match | level=%s | raw=%s",
                level,
                raw_output[:200],
            )
            return {
                "cqs_level": level,
                "confidence": 0.3,
                "raw_text": raw_output,
            }

    # No match at all
    logger.info(
        "SIGNAL_VALIDATOR | cqs_parse_failed | raw_output=%s",
        raw_output[:200],
    )
    return {"error": "parse_failed", "confidence": 0.0, "raw_text": raw_output}


def _normalize_visibility(raw_output: str) -> dict:
    """Normalize submission visibility probe result.

    Extension reports "present" or "absent" after checking if a post
    appears in the subreddit /new feed.

    Returns:
        Dict with visible (bool) and confidence.
    """
    if not raw_output:
        return {"error": "parse_failed", "confidence": 0.0, "raw_text": ""}

    normalized = raw_output.strip().lower()

    if normalized == "present":
        return {"visible": True, "confidence": 0.9}
    elif normalized == "absent":
        return {"visible": False, "confidence": 0.9}
    else:
        logger.info(
            "SIGNAL_VALIDATOR | visibility_parse_failed | raw_output=%s",
            raw_output[:200],
        )
        return {"error": "parse_failed", "confidence": 0.0, "raw_text": raw_output}


def _normalize_profile(raw_output: str) -> dict:
    """Normalize profile check probe result.

    Extension reports JSON with karma values from the user's profile page.
    Expected format: {"comment_karma": int, "link_karma": int, ...}
    May optionally include ban_indicators.

    Returns:
        Dict with comment_karma, link_karma, ban_indicators, and confidence.
    """
    if not raw_output:
        return {"error": "parse_failed", "confidence": 0.0, "raw_text": ""}

    try:
        data = json.loads(raw_output)
    except (json.JSONDecodeError, TypeError):
        logger.info(
            "SIGNAL_VALIDATOR | profile_json_parse_failed | raw_output=%s",
            raw_output[:200],
        )
        return {"error": "parse_failed", "confidence": 0.0, "raw_text": raw_output}

    comment_karma = data.get("comment_karma")
    link_karma = data.get("link_karma")

    if comment_karma is None or link_karma is None:
        logger.info(
            "SIGNAL_VALIDATOR | profile_missing_fields | keys=%s",
            list(data.keys()),
        )
        return {"error": "parse_failed", "confidence": 0.0, "raw_text": raw_output}

    try:
        ban_indicators = data.get("ban_indicators", [])
        if not isinstance(ban_indicators, list):
            ban_indicators = []

        return {
            "comment_karma": int(comment_karma),
            "link_karma": int(link_karma),
            "ban_indicators": ban_indicators,
            "confidence": 0.85,
        }
    except (ValueError, TypeError):
        return {"error": "parse_failed", "confidence": 0.0, "raw_text": raw_output}



# ─── Health Signal Processing ───────────────────────────────────────────────

# Trust weights per signal type — higher weight = more reliable indicator of health issue.
SIGNAL_TRUST_WEIGHTS: dict[str, float] = {
    "comment_removed": 0.6,
    "ban_notice": 0.9,
    "profile_restricted": 0.8,
    "cqs_degraded": 0.7,
}
DEFAULT_TRUST_WEIGHT = 0.5

# Decay hours per signal type — how long the signal remains relevant.
SIGNAL_DECAY_HOURS: dict[str, int] = {
    "comment_removed": 72,       # 3 days
    "ban_notice": 168,           # 7 days
    "profile_restricted": 120,   # 5 days
}
DEFAULT_DECAY_HOURS = 48  # 2 days


def process_health_signal(
    db: Session,
    avatar_username: str,
    signal_type: str,
    raw_value: dict,
    timestamp: datetime,
) -> dict:
    """Record a health signal from extension with trust weight and decay.

    This is the first step of the signal processing pipeline — recording
    signals with weights for later aggregation. Threshold-based decisions
    happen elsewhere.

    Args:
        db: Database session.
        avatar_username: Reddit username of the avatar.
        signal_type: Type of health signal (e.g. "comment_removed", "ban_notice").
        raw_value: Raw observation data from the extension.
        timestamp: When the signal was observed.

    Returns:
        Dict with trust_weight, decay_hours, signal_type, and recorded flag.
    """
    trust_weight = SIGNAL_TRUST_WEIGHTS.get(signal_type, DEFAULT_TRUST_WEIGHT)
    decay_hours = SIGNAL_DECAY_HOURS.get(signal_type, DEFAULT_DECAY_HOURS)

    # Look up avatar to get client_id for the activity event
    client_id = _resolve_client_id(db, avatar_username)

    event = ActivityEvent(
        id=uuid.uuid4(),
        client_id=client_id,
        event_type="health_signal_received",
        message=(
            f"Health signal '{signal_type}' for {avatar_username} "
            f"(weight={trust_weight}, decay={decay_hours}h)"
        ),
        event_metadata={
            "avatar_username": avatar_username,
            "signal_type": signal_type,
            "raw_value": raw_value,
            "trust_weight": trust_weight,
            "decay_hours": decay_hours,
            "timestamp": timestamp.isoformat(),
        },
    )
    db.add(event)
    db.flush()

    logger.info(
        "SIGNAL_VALIDATOR | health_signal_recorded | avatar=%s | type=%s | weight=%.2f | decay=%dh",
        avatar_username,
        signal_type,
        trust_weight,
        decay_hours,
    )

    return {
        "trust_weight": trust_weight,
        "decay_hours": decay_hours,
        "signal_type": signal_type,
        "recorded": True,
    }


def _resolve_client_id(db: Session, avatar_username: str) -> uuid.UUID | None:
    """Resolve client_id from avatar username. Returns None if not found."""
    from app.models.avatar import Avatar

    avatar = (
        db.query(Avatar)
        .filter(Avatar.reddit_username == avatar_username)
        .first()
    )
    if avatar and avatar.client_ids:
        try:
            return uuid.UUID(str(avatar.client_ids[0]))
        except (ValueError, TypeError, IndexError):
            pass
    return None


# --- CQS level ordering for improvement detection ---
CQS_LEVEL_ORDER = {"lowest": 0, "low": 1, "medium": 2, "high": 3}


def handle_cqs_improvement(
    db: Session,
    avatar_id: uuid.UUID,
    old_level: str,
    new_level: str,
    raw_text: str,
) -> dict:
    """Handle a CQS improvement signal reported by the browser extension.

    Called when extension reports a CQS level change. Determines if it's
    actually an improvement, updates the avatar's cqs_level, and flags
    recovery candidates for downstream PRAW verification.

    Args:
        db: SQLAlchemy database session.
        avatar_id: UUID of the avatar whose CQS changed.
        old_level: Previous CQS level (e.g., "lowest").
        new_level: New CQS level reported by extension (e.g., "low").
        raw_text: Raw AutoModerator reply text from extension probe.

    Returns:
        Dict with improvement status and recovery_candidate flag.
    """
    from app.models.avatar import Avatar
    from app.models.activity_event import ActivityEvent

    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        logger.warning(
            "SIGNAL_VALIDATOR | handle_cqs_improvement | avatar_not_found | id=%s",
            avatar_id,
        )
        return {"error": "avatar_not_found", "improved": False, "recovery_candidate": False}

    # Normalize levels to lowercase
    old_normalized = old_level.strip().lower() if old_level else ""
    new_normalized = new_level.strip().lower() if new_level else ""

    # Validate both levels are recognized
    if old_normalized not in CQS_LEVEL_ORDER or new_normalized not in CQS_LEVEL_ORDER:
        logger.warning(
            "SIGNAL_VALIDATOR | handle_cqs_improvement | invalid_level | "
            "old=%s | new=%s | avatar=%s",
            old_level, new_level, avatar.reddit_username,
        )
        return {"error": "invalid_level", "improved": False, "recovery_candidate": False}

    # Determine if this is an actual improvement
    old_rank = CQS_LEVEL_ORDER[old_normalized]
    new_rank = CQS_LEVEL_ORDER[new_normalized]
    is_improvement = new_rank > old_rank

    # Always update cqs_level to the latest measurement (regardless of direction)
    avatar.cqs_level = new_normalized
    avatar.cqs_checked_at = datetime.now(timezone.utc)
    db.flush()

    if is_improvement:
        # Flag as recovery candidate
        logger.info(
            "SIGNAL_VALIDATOR | cqs_improvement_detected | username=u/%s | "
            "old=%s | new=%s | recovery_candidate=True",
            avatar.reddit_username, old_normalized, new_normalized,
        )

        # Determine client_id for event scoping
        client_id = None
        if avatar.client_ids:
            try:
                client_id = uuid.UUID(avatar.client_ids[0]) if avatar.client_ids[0] else None
            except (IndexError, TypeError, ValueError):
                pass

        # Create ActivityEvent for recovery detection
        event = ActivityEvent(
            event_type="cqs_recovery_detected",
            message=(
                f"CQS improvement for u/{avatar.reddit_username}: "
                f"{old_normalized} → {new_normalized}. "
                f"Recovery candidate flagged for PRAW verification."
            ),
            client_id=client_id,
            event_metadata={
                "avatar_id": str(avatar_id),
                "username": avatar.reddit_username,
                "old_level": old_normalized,
                "new_level": new_normalized,
                "raw_text": raw_text[:500] if raw_text else "",
                "recovery_candidate": True,
                "detected_at": datetime.now(timezone.utc).isoformat(),
                "source": "browser_extension",
                "is_frozen": avatar.is_frozen,
                "is_shadowbanned": avatar.is_shadowbanned,
            },
        )
        db.add(event)
        db.flush()

        logger.info(
            "SIGNAL_VALIDATOR | recovery_candidate_created | username=u/%s | "
            "event_id=%s | awaiting_praw_probe",
            avatar.reddit_username, event.id,
        )

        return {
            "improved": True,
            "old_level": old_normalized,
            "new_level": new_normalized,
            "recovery_candidate": True,
        }
    else:
        # Not an improvement (same or worse) — still record the new level
        logger.info(
            "SIGNAL_VALIDATOR | cqs_no_improvement | username=u/%s | "
            "old=%s | new=%s",
            avatar.reddit_username, old_normalized, new_normalized,
        )

        return {
            "improved": False,
            "old_level": old_normalized,
            "new_level": new_normalized,
            "recovery_candidate": False,
        }
