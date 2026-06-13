"""Learning Loop service — store human edits and retrieve for few-shot injection.

Part of the RAMP Closed Feedback Architecture.
This loop learns from TWO signals:
1. Human corrections to LLM-generated behavioral profiles (store_edit)
2. Real Reddit outcomes that validate/invalidate profile accuracy (get_outcome_context)
"""

from app.logging_config import get_logger
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.analysis_edit import AnalysisEditRecord

logger = get_logger(__name__)


def _truncate(value: object, max_len: int = 50) -> str:
    """Truncate a value representation for readable diff summaries."""
    s = repr(value)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _diff_nested(parent_key: str, original: dict, edited: dict) -> list[str]:
    """Compute diff for a nested dict, prefixing with parent key."""
    changes: list[str] = []
    nested_keys = set(original.keys()) | set(edited.keys())

    for key in sorted(nested_keys):
        orig_val = original.get(key)
        edit_val = edited.get(key)

        if orig_val == edit_val:
            continue

        full_key = f"{parent_key}.{key}"
        if key not in original:
            changes.append(f"Added '{full_key}'")
        elif key not in edited:
            changes.append(f"Removed '{full_key}'")
        else:
            changes.append(
                f"Changed '{full_key}' from {_truncate(orig_val)} to {_truncate(edit_val)}"
            )

    return changes


def _compute_diff_summary(llm_output: dict, human_edited: dict) -> str:
    """Compute a human-readable summary of differences between two dicts.

    Walks top-level and nested keys, collecting changes into a description.
    """
    changes: list[str] = []

    all_keys = set(llm_output.keys()) | set(human_edited.keys())
    for key in sorted(all_keys):
        original = llm_output.get(key)
        edited = human_edited.get(key)

        if original == edited:
            continue

        if key not in llm_output:
            changes.append(f"Added '{key}'")
        elif key not in human_edited:
            changes.append(f"Removed '{key}'")
        elif isinstance(original, dict) and isinstance(edited, dict):
            nested_changes = _diff_nested(key, original, edited)
            changes.extend(nested_changes)
        else:
            changes.append(f"Changed '{key}' from {_truncate(original)} to {_truncate(edited)}")

    return "; ".join(changes)


def store_edit(
    db: Session,
    avatar_id: uuid.UUID,
    llm_output: dict,
    human_edited: dict,
) -> AnalysisEditRecord:
    """Compute diff, store edit record. Raises ValueError if no changes.

    Args:
        db: Database session.
        avatar_id: The avatar this edit belongs to.
        llm_output: Original LLM-generated BehavioralProfile dict.
        human_edited: Human-corrected BehavioralProfile dict.

    Returns:
        The persisted AnalysisEditRecord.

    Raises:
        ValueError: If llm_output and human_edited are identical.
    """
    if llm_output == human_edited:
        raise ValueError("No changes detected")

    diff_summary = _compute_diff_summary(llm_output, human_edited)

    record = AnalysisEditRecord(
        avatar_id=avatar_id,
        llm_output=llm_output,
        human_edited=human_edited,
        diff_summary=diff_summary,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(
        "LEARNING_LOOP | action=store_edit | avatar_id=%s | record_id=%s | diff=%s",
        avatar_id,
        record.id,
        diff_summary[:100],
    )

    return record


def get_recent_edits(
    db: Session,
    avatar_id: uuid.UUID,
    limit: int = 3,
) -> list[AnalysisEditRecord]:
    """Retrieve most recent N edit records for few-shot injection.

    Args:
        db: Database session.
        avatar_id: The avatar to retrieve edits for.
        limit: Maximum number of records to return.

    Returns:
        List of AnalysisEditRecord ordered by created_at DESC.
    """
    stmt = (
        select(AnalysisEditRecord)
        .where(AnalysisEditRecord.avatar_id == avatar_id)
        .order_by(AnalysisEditRecord.created_at.desc())
        .limit(limit)
    )
    result = db.execute(stmt).scalars().all()
    return list(result)

def get_outcome_context(db: Session, avatar_id: uuid.UUID) -> str:
    """Build outcome-based context for avatar analysis injection.

    Fetches real Reddit performance data (karma, removals, approach effectiveness)
    and formats it as context for the LLM to validate/correct behavioral profiles.

    This connects Loop 2 (Avatar Analysis) to Loop 3 (EPG Feedback),
    ensuring the profile assessment reflects actual Reddit outcomes,
    not just human preferences.

    Args:
        db: Database session.
        avatar_id: The avatar to get outcome data for.

    Returns:
        Formatted string for prompt injection, or empty string if no data.
    """
    try:
        from app.services.outcome_analysis import compute_avatar_outcome_profile

        profile = compute_avatar_outcome_profile(db, avatar_id, lookback_days=30)

        if profile.total_posted < 3:
            return ""

        parts = [
            "\n\n--- Real Reddit Outcome Data (last 30 days) ---",
            f"Total posted: {profile.total_posted}",
            f"Average karma: {profile.avg_karma:.1f}",
            f"Removal rate: {profile.removal_rate:.0%}",
            f"Karma velocity: {profile.karma_velocity:.1f}/day",
        ]

        if profile.top_performing_subreddits:
            parts.append(f"Best subreddits: {', '.join(profile.top_performing_subreddits)}")

        if profile.underperforming_subreddits:
            parts.append(f"Underperforming: {', '.join(profile.underperforming_subreddits)}")

        if profile.approach_signals:
            best = profile.approach_signals[0]
            parts.append(f"Best approach: {best.approach} (avg karma: {best.avg_karma:.1f})")
            if len(profile.approach_signals) > 1:
                worst = profile.approach_signals[-1]
                parts.append(f"Worst approach: {worst.approach} (avg karma: {worst.avg_karma:.1f})")

        parts.append(
            "\nUse this outcome data to VALIDATE your behavioral assessment. "
            "If the avatar\'s actual Reddit performance contradicts the voice profile "
            "or intended persona, note it in \'mismatches\'."
        )

        return "\n".join(parts)

    except Exception:
        logger.warning(
            "get_outcome_context failed for avatar %s — skipping outcome injection",
            avatar_id,
            exc_info=True,
        )
        return ""
