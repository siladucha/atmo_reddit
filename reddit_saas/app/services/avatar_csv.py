"""Avatar CSV import/export service.

Provides bulk CSV export and import for avatars — used for quick loading
of avatar inventories by admin, partner, and avatar manager roles.

Export format: flat CSV with one row per avatar, key fields for identity,
voice profile, subreddits, and classification.

Import: creates new avatars from CSV rows. Skips rows where reddit_username
already exists (deduplication). Returns a summary of created/skipped/errors.
"""

import csv
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.avatar import Avatar

logger = logging.getLogger(__name__)

# Fields included in CSV export/import (order matters for CSV columns)
CSV_FIELDS = [
    "reddit_username",
    "email_address",
    "pool",
    "industry",
    "warming_phase",
    "voice_profile_md",
    "tone_principles",
    "speech_patterns",
    "hill_i_die_on",
    "helpful_mode_topics",
    "constraints",
    "vocabulary_lean",
    "hobby_subreddits",
    "business_subreddits",
    "is_farm_avatar",
    "active",
]


def export_avatars_csv(db: Session, client_id: uuid.UUID | None = None) -> str:
    """Export avatars to CSV string.

    Args:
        db: Database session
        client_id: Optional filter — only avatars assigned to this client

    Returns:
        CSV content as string (UTF-8)
    """
    q = db.query(Avatar).order_by(Avatar.reddit_username)
    if client_id:
        q = q.filter(Avatar.client_ids.any(str(client_id)))
    avatars = q.all()

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()

    for avatar in avatars:
        row = _avatar_to_csv_row(avatar)
        writer.writerow(row)

    return output.getvalue()


def import_avatars_csv(
    db: Session,
    csv_content: str,
    user_id: uuid.UUID,
    client_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Import avatars from CSV content.

    Creates new avatars for each row. Skips rows where reddit_username
    already exists in the database.

    Args:
        db: Database session
        csv_content: CSV file content as string
        user_id: ID of the user performing the import (for audit)
        client_id: Optional — auto-assign imported avatars to this client

    Returns:
        Summary dict with created, skipped, errors counts and details
    """
    reader = csv.DictReader(io.StringIO(csv_content))

    created: list[str] = []
    skipped: list[str] = []
    errors: list[dict[str, str]] = []

    # Pre-fetch existing usernames for deduplication
    existing_usernames = {
        row[0].lower()
        for row in db.query(Avatar.reddit_username).all()
    }

    row_num = 0
    for row in reader:
        row_num += 1
        username = (row.get("reddit_username") or "").strip()

        if not username:
            errors.append({"row": row_num, "error": "Missing reddit_username"})
            continue

        if username.lower() in existing_usernames:
            skipped.append(username)
            continue

        try:
            avatar = _csv_row_to_avatar(row, client_id=client_id)
            db.add(avatar)
            db.flush()  # Get ID without committing
            created.append(username)
            existing_usernames.add(username.lower())
        except Exception as e:
            errors.append({"row": row_num, "username": username, "error": str(e)})

    if created:
        db.commit()
        logger.info(
            "Avatar CSV import completed | user_id=%s | created=%d | skipped=%d | errors=%d",
            user_id, len(created), len(skipped), len(errors),
        )
    else:
        db.rollback()

    return {
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "total_rows": row_num,
        "created_count": len(created),
        "skipped_count": len(skipped),
        "error_count": len(errors),
    }


def get_csv_template() -> str:
    """Return an empty CSV template with headers and one example row."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    # Example row
    writer.writerow({
        "reddit_username": "ExampleUser123",
        "email_address": "user@example.com",
        "pool": "b2b",
        "industry": "cybersecurity",
        "warming_phase": "1",
        "voice_profile_md": "Experienced security engineer, pragmatic tone",
        "tone_principles": "Direct, no fluff, evidence-based",
        "speech_patterns": "",
        "hill_i_die_on": "Zero trust is not optional",
        "helpful_mode_topics": "network security, SIEM, incident response",
        "constraints": "Never mention specific CVEs without context",
        "vocabulary_lean": "",
        "hobby_subreddits": "r/homelab, r/networking",
        "business_subreddits": "r/cybersecurity, r/netsec",
        "is_farm_avatar": "false",
        "active": "true",
    })
    return output.getvalue()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _avatar_to_csv_row(avatar: Avatar) -> dict[str, str]:
    """Convert an Avatar model instance to a flat CSV row dict."""
    hobby = avatar.hobby_subreddits
    if isinstance(hobby, list):
        # Items can be strings ("running") or dicts ({"subreddit": "Biohackers", ...})
        parts = []
        for item in hobby:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("subreddit") or item.get("name") or str(item))
            else:
                parts.append(str(item))
        hobby_str = ", ".join(parts)
    elif isinstance(hobby, dict):
        hobby_str = ", ".join(hobby.keys()) if hobby else ""
    else:
        hobby_str = ""

    business = avatar.business_subreddits
    if isinstance(business, list):
        parts = []
        for item in business:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("subreddit") or item.get("name") or str(item))
            else:
                parts.append(str(item))
        business_str = ", ".join(parts)
    elif isinstance(business, dict):
        business_str = ", ".join(business.keys()) if business else ""
    else:
        business_str = ""

    return {
        "reddit_username": avatar.reddit_username or "",
        "email_address": avatar.email_address or "",
        "pool": avatar.pool or "b2b",
        "industry": avatar.industry or "",
        "warming_phase": str(avatar.warming_phase),
        "voice_profile_md": avatar.voice_profile_md or "",
        "tone_principles": avatar.tone_principles or "",
        "speech_patterns": avatar.speech_patterns or "",
        "hill_i_die_on": avatar.hill_i_die_on or "",
        "helpful_mode_topics": avatar.helpful_mode_topics or "",
        "constraints": avatar.constraints or "",
        "vocabulary_lean": avatar.vocabulary_lean or "",
        "hobby_subreddits": hobby_str,
        "business_subreddits": business_str,
        "is_farm_avatar": str(avatar.is_farm_avatar).lower(),
        "active": str(avatar.active).lower(),
    }


def _csv_row_to_avatar(row: dict[str, str], client_id: uuid.UUID | None = None) -> Avatar:
    """Convert a CSV row dict to an Avatar model instance."""
    username = row.get("reddit_username", "").strip()
    if not username:
        raise ValueError("reddit_username is required")

    # Parse hobby_subreddits — comma-separated list
    hobby_raw = row.get("hobby_subreddits", "").strip()
    hobby_list = [s.strip().lstrip("r/") for s in hobby_raw.split(",") if s.strip()] if hobby_raw else []
    # Store as list (JSONB)
    hobby_subreddits = hobby_list if hobby_list else None

    # Parse business_subreddits — comma-separated list
    business_raw = row.get("business_subreddits", "").strip()
    business_list = [s.strip().lstrip("r/") for s in business_raw.split(",") if s.strip()] if business_raw else []
    business_subreddits = business_list if business_list else None

    # Parse boolean fields
    is_farm = _parse_bool(row.get("is_farm_avatar", "false"))
    active = _parse_bool(row.get("active", "true"))

    # Parse warming_phase
    try:
        warming_phase = int(row.get("warming_phase", "1"))
        if warming_phase < 0 or warming_phase > 3:
            warming_phase = 1
    except (ValueError, TypeError):
        warming_phase = 1

    # Parse pool
    pool = row.get("pool", "b2b").strip().lower()
    if pool not in ("b2b", "b2c", "mentor", "warm"):
        pool = "b2b"

    # Client assignment
    client_ids = [str(client_id)] if client_id else None

    return Avatar(
        reddit_username=username,
        email_address=row.get("email_address", "").strip() or None,
        pool=pool,
        industry=row.get("industry", "").strip() or None,
        warming_phase=warming_phase,
        voice_profile_md=row.get("voice_profile_md", "").strip() or None,
        tone_principles=row.get("tone_principles", "").strip() or None,
        speech_patterns=row.get("speech_patterns", "").strip() or None,
        hill_i_die_on=row.get("hill_i_die_on", "").strip() or None,
        helpful_mode_topics=row.get("helpful_mode_topics", "").strip() or None,
        constraints=row.get("constraints", "").strip() or None,
        vocabulary_lean=row.get("vocabulary_lean", "").strip() or None,
        hobby_subreddits=hobby_subreddits,
        business_subreddits=business_subreddits,
        is_farm_avatar=is_farm,
        active=active,
        client_ids=client_ids,
    )


def _parse_bool(value: str) -> bool:
    """Parse a boolean from CSV string."""
    return value.strip().lower() in ("true", "1", "yes", "t", "y")
