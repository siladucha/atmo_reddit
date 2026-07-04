"""Control Variable Enforcer — Hooks into EPG pipeline for A/B test experiments.

Provides module-level functions that the pipeline calls to check if an avatar
is participating in an active experiment, and if so, returns the enforced
control variable values (budget, risk range, content type, generation model).

Non-participating avatars get None (early return), signaling the pipeline
to use its default behavior.

Usage:
    from app.services.ab_test.control_enforcer import (
        get_experiment_budget,
        get_allowed_risk_range,
        get_forced_content_type,
        get_forced_generation_model,
        validate_and_log_violation,
    )
"""

import uuid
from datetime import date, timezone

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.ab_test import ControlViolation, ExperimentRun
from app.models.activity_event import ActivityEvent
from app.services.ab_test.experiment_manager import get_active_experiment_for_avatar

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Control Variable Queries
# ---------------------------------------------------------------------------


def get_experiment_budget(
    db: Session,
    avatar_id: uuid.UUID,
) -> int | None:
    """Return the experiment-enforced daily volume for a participating avatar.

    If the avatar is in an active experiment, returns the experiment's
    `daily_volume_per_avatar` config value (default 3). Otherwise returns
    None, indicating the pipeline should use its normal budget logic.

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar.

    Returns:
        Daily volume integer if in experiment, None otherwise.
    """
    experiment = get_active_experiment_for_avatar(db, avatar_id)
    if experiment is None:
        return None

    return experiment.daily_volume_per_avatar


def get_allowed_risk_range(
    db: Session,
    avatar_id: uuid.UUID,
) -> tuple[int, int] | None:
    """Return the allowed subreddit risk score range for a participating avatar.

    If the avatar is in an active experiment, returns (0, subreddit_risk_max)
    from experiment config. Otherwise returns None, indicating the pipeline
    should use its normal subreddit filtering.

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar.

    Returns:
        Tuple (0, risk_max) if in experiment, None otherwise.
    """
    experiment = get_active_experiment_for_avatar(db, avatar_id)
    if experiment is None:
        return None

    return (0, experiment.subreddit_risk_max)


def get_forced_content_type(
    db: Session,
    avatar_id: uuid.UUID,
) -> str | None:
    """Return the experiment-enforced content type for a participating avatar.

    If the avatar is in an active experiment, returns the experiment's
    `content_type` (typically "hobby"). Otherwise returns None, indicating
    the pipeline should use its normal content type logic.

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar.

    Returns:
        Content type string if in experiment, None otherwise.
    """
    experiment = get_active_experiment_for_avatar(db, avatar_id)
    if experiment is None:
        return None

    return experiment.content_type


def get_forced_generation_model(
    db: Session,
    avatar_id: uuid.UUID,
) -> str | None:
    """Return the experiment-enforced LLM generation model for a participating avatar.

    If the avatar is in an active experiment, returns the experiment's
    `generation_model` (locked at experiment start). Otherwise returns None,
    indicating the pipeline should use the system's configured model.

    Args:
        db: SQLAlchemy session.
        avatar_id: UUID of the avatar.

    Returns:
        Model string if in experiment, None otherwise.
    """
    experiment = get_active_experiment_for_avatar(db, avatar_id)
    if experiment is None:
        return None

    return experiment.generation_model


# ---------------------------------------------------------------------------
# Violation Logging
# ---------------------------------------------------------------------------


def validate_and_log_violation(
    db: Session,
    experiment_id: uuid.UUID,
    avatar_id: uuid.UUID,
    violation_type: str,
    details: dict,
) -> ControlViolation:
    """Record a control variable violation and emit an activity event.

    Called when the pipeline detects a breach of experiment constraints
    (e.g., budget exceeded, subreddit risk too high, wrong content type).

    Args:
        db: SQLAlchemy session.
        experiment_id: UUID of the experiment.
        avatar_id: UUID of the avatar that violated.
        violation_type: Short identifier (e.g., "budget_exceeded",
            "risk_range_violation", "content_type_mismatch").
        details: JSONB dict with contextual information about the violation.

    Returns:
        The created ControlViolation record.
    """
    from datetime import datetime

    today = datetime.now(timezone.utc).date()

    violation = ControlViolation(
        experiment_id=experiment_id,
        avatar_id=avatar_id,
        violation_type=violation_type,
        violation_date=today,
        details=details,
    )
    db.add(violation)

    # Emit activity event for transparency
    event = ActivityEvent(
        event_type="ab_control_violation",
        message=(
            f"Control variable violation [{violation_type}] "
            f"for avatar in experiment."
        ),
        event_metadata={
            "experiment_id": str(experiment_id),
            "avatar_id": str(avatar_id),
            "violation_type": violation_type,
            "violation_date": today.isoformat(),
            "details": details,
        },
    )
    db.add(event)

    db.flush()

    logger.warning(
        "Control violation logged: type=%s, avatar=%s, experiment=%s",
        violation_type,
        avatar_id,
        experiment_id,
    )

    return violation
