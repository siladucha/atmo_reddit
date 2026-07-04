"""Experiment Manager — full lifecycle management for A/B test experiments.

Provides module-level functions for creating, configuring, and managing
experiment runs including avatar assignment with eligibility validation,
state transitions, and exclusion tracking.

Usage:
    from app.services.ab_test.experiment_manager import (
        create_experiment, add_treatment_group, assign_avatar,
        start_experiment, pause_experiment, resume_experiment,
        conclude_experiment, abort_experiment, exclude_avatar,
        get_active_experiment_for_avatar, is_avatar_in_experiment,
    )
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.ab_test import (
    AvatarAssignment,
    ExperimentRun,
    TreatmentGroup,
)
from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _emit_event(
    db: Session,
    event_type: str,
    message: str,
    metadata: dict | None = None,
) -> None:
    """Create an ActivityEvent record for experiment lifecycle actions."""
    event = ActivityEvent(
        event_type=event_type,
        message=message,
        event_metadata=metadata,
    )
    db.add(event)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Experiment Creation
# ---------------------------------------------------------------------------


def create_experiment(
    db: Session,
    name: str,
    hypothesis: str,
    duration_weeks: int,
    groups: list[dict],
    daily_volume: int = 3,
    risk_max: int = 40,
    content_type: str = "hobby",
    model: str | None = None,
    created_by: uuid.UUID | None = None,
) -> ExperimentRun:
    """Create a new experiment in draft state with treatment groups.

    Args:
        db: SQLAlchemy session.
        name: Experiment name.
        hypothesis: What the experiment aims to prove/disprove.
        duration_weeks: Planned duration (default 8).
        groups: List of dicts with keys: name, posting_method, description (optional).
        daily_volume: Posts per avatar per day (default 3).
        risk_max: Maximum subreddit risk score allowed (default 40).
        content_type: Content type restriction (default "hobby").
        model: LLM generation model to use (required).
        created_by: UUID of the creating user.

    Returns:
        The created ExperimentRun.

    Raises:
        ValueError: If validation fails.
    """
    # Validate minimum 2 groups
    if not groups or len(groups) < 2:
        raise ValueError("At least 2 treatment groups are required.")

    # Validate each group has a posting_method
    posting_methods = set()
    for g in groups:
        pm = g.get("posting_method")
        if not pm:
            raise ValueError("Each group must have a posting_method.")
        if pm in posting_methods:
            raise ValueError(
                f"Duplicate posting_method '{pm}'. Each group must have a distinct method."
            )
        posting_methods.add(pm)

    # Validate duration
    if duration_weeks < 1:
        raise ValueError("Planned duration must be at least 1 week.")

    # Validate model
    if not model:
        raise ValueError("A generation model must be specified for the experiment.")

    # Create experiment
    experiment = ExperimentRun(
        name=name,
        hypothesis=hypothesis,
        status="draft",
        planned_duration_weeks=duration_weeks,
        daily_volume_per_avatar=daily_volume,
        subreddit_risk_max=risk_max,
        content_type=content_type,
        generation_model=model,
        created_by=created_by,
    )
    db.add(experiment)
    db.flush()  # Get the ID

    # Create treatment groups
    for g in groups:
        group = TreatmentGroup(
            experiment_id=experiment.id,
            name=g["name"],
            posting_method=g["posting_method"],
            description=g.get("description"),
        )
        db.add(group)

    db.flush()

    _emit_event(
        db,
        event_type="ab_experiment_created",
        message=f"A/B experiment '{name}' created with {len(groups)} groups.",
        metadata={
            "experiment_id": str(experiment.id),
            "groups": [g["posting_method"] for g in groups],
            "duration_weeks": duration_weeks,
        },
    )

    logger.info(
        "Experiment created: %s (id=%s, groups=%d)",
        name,
        experiment.id,
        len(groups),
    )
    return experiment


# ---------------------------------------------------------------------------
# Treatment Group Management
# ---------------------------------------------------------------------------


def add_treatment_group(
    db: Session,
    experiment_id: uuid.UUID,
    name: str,
    posting_method: str,
    description: str | None = None,
) -> TreatmentGroup:
    """Add a treatment group to an existing experiment.

    Args:
        db: SQLAlchemy session.
        experiment_id: UUID of the experiment.
        name: Display name for the group.
        posting_method: The posting method identifier.
        description: Optional description.

    Returns:
        The created TreatmentGroup.

    Raises:
        ValueError: If experiment not found, not in draft, or posting_method duplicate.
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise ValueError(f"Experiment {experiment_id} not found.")
    if experiment.status != "draft":
        raise ValueError("Can only add groups to experiments in 'draft' state.")

    # Check unique posting_method per experiment
    existing = db.query(TreatmentGroup).filter(
        TreatmentGroup.experiment_id == experiment_id,
        TreatmentGroup.posting_method == posting_method,
    ).first()
    if existing:
        raise ValueError(
            f"Posting method '{posting_method}' already exists in this experiment."
        )

    group = TreatmentGroup(
        experiment_id=experiment_id,
        name=name,
        posting_method=posting_method,
        description=description,
    )
    db.add(group)
    db.flush()

    logger.info(
        "Treatment group added: %s (method=%s, experiment=%s)",
        name,
        posting_method,
        experiment_id,
    )
    return group


# ---------------------------------------------------------------------------
# Avatar Assignment
# ---------------------------------------------------------------------------


def assign_avatar(
    db: Session,
    experiment_id: uuid.UUID,
    group_id: uuid.UUID,
    avatar_id: uuid.UUID,
) -> AvatarAssignment:
    """Assign an avatar to a treatment group with eligibility validation.

    Validates:
    - CQS level is not 'lowest'
    - Account age is within ±2 weeks of group median

    Stores an eligibility snapshot at assignment time.

    Args:
        db: SQLAlchemy session.
        experiment_id: UUID of the experiment.
        group_id: UUID of the treatment group.
        avatar_id: UUID of the avatar to assign.

    Returns:
        The created AvatarAssignment.

    Raises:
        ValueError: If validation fails.
    """
    # Validate experiment exists and is in draft
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise ValueError(f"Experiment {experiment_id} not found.")
    if experiment.status != "draft":
        raise ValueError("Can only assign avatars to experiments in 'draft' state.")

    # Validate group belongs to this experiment
    group = db.query(TreatmentGroup).filter(
        TreatmentGroup.id == group_id,
        TreatmentGroup.experiment_id == experiment_id,
    ).first()
    if not group:
        raise ValueError(
            f"Treatment group {group_id} not found in experiment {experiment_id}."
        )

    # Validate avatar exists
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        raise ValueError(f"Avatar {avatar_id} not found.")

    # Check not already assigned in this experiment (UniqueConstraint will catch too)
    existing = db.query(AvatarAssignment).filter(
        AvatarAssignment.experiment_id == experiment_id,
        AvatarAssignment.avatar_id == avatar_id,
    ).first()
    if existing:
        raise ValueError(
            f"Avatar {avatar_id} is already assigned in experiment {experiment_id}."
        )

    # Eligibility: CQS ≠ lowest
    if avatar.cqs_level and avatar.cqs_level.lower() == "lowest":
        raise ValueError(
            f"Avatar {avatar.reddit_username} has CQS 'lowest' and is not eligible."
        )

    # Eligibility: Account age within ±2 weeks of group median
    _validate_account_age(db, group_id, avatar)

    # Build eligibility snapshot
    now = _now()
    account_age_days = 0
    if avatar.reddit_account_created:
        account_age_days = (now - avatar.reddit_account_created).days

    snapshot = {
        "account_age_days": account_age_days,
        "cqs_level": avatar.cqs_level or "unknown",
        "warming_phase": avatar.warming_phase,
        "health_status": avatar.health_status,
        "is_frozen": avatar.is_frozen,
        "is_shadowbanned": avatar.is_shadowbanned,
    }

    assignment = AvatarAssignment(
        experiment_id=experiment_id,
        group_id=group_id,
        avatar_id=avatar_id,
        assignment_snapshot=snapshot,
    )
    db.add(assignment)
    db.flush()

    logger.info(
        "Avatar %s assigned to group %s in experiment %s",
        avatar.reddit_username,
        group.name,
        experiment_id,
    )
    return assignment


def _validate_account_age(
    db: Session,
    group_id: uuid.UUID,
    avatar: Avatar,
) -> None:
    """Validate avatar's account age is within ±2 weeks of group median.

    If the group has no existing members, skip this check (first assignment).
    """
    # Get existing assignments for this group (non-excluded)
    existing_assignments = (
        db.query(AvatarAssignment)
        .filter(
            AvatarAssignment.group_id == group_id,
            AvatarAssignment.is_excluded == False,  # noqa: E712
        )
        .all()
    )

    if not existing_assignments:
        # First avatar in group — no median to compare against
        return

    # Calculate account ages from snapshots
    ages = []
    for a in existing_assignments:
        snap = a.assignment_snapshot or {}
        age = snap.get("account_age_days", 0)
        ages.append(age)

    if not ages:
        return

    # Calculate median
    sorted_ages = sorted(ages)
    n = len(sorted_ages)
    if n % 2 == 1:
        median_age = sorted_ages[n // 2]
    else:
        median_age = (sorted_ages[n // 2 - 1] + sorted_ages[n // 2]) / 2

    # Check avatar's account age
    now = _now()
    avatar_age = 0
    if avatar.reddit_account_created:
        avatar_age = (now - avatar.reddit_account_created).days

    two_weeks_days = 14
    if abs(avatar_age - median_age) > two_weeks_days:
        raise ValueError(
            f"Avatar account age ({avatar_age} days) is more than ±2 weeks "
            f"from group median ({median_age:.0f} days). "
            f"Difference: {abs(avatar_age - median_age):.0f} days."
        )


# ---------------------------------------------------------------------------
# Experiment State Transitions
# ---------------------------------------------------------------------------


def start_experiment(
    db: Session,
    experiment_id: uuid.UUID,
) -> ExperimentRun:
    """Start an experiment: validate prerequisites and transition draft → active.

    Validates:
    - At least 5 avatars per group (non-excluded).
    - Experiment is in 'draft' state.

    Sets start_date and freezes configuration.

    Returns:
        The updated ExperimentRun.

    Raises:
        ValueError: If validation fails.
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise ValueError(f"Experiment {experiment_id} not found.")
    if experiment.status != "draft":
        raise ValueError("Can only start experiments in 'draft' state.")

    # Validate minimum group sizes
    groups = (
        db.query(TreatmentGroup)
        .filter(TreatmentGroup.experiment_id == experiment_id)
        .all()
    )
    if len(groups) < 2:
        raise ValueError("Experiment must have at least 2 treatment groups.")

    for group in groups:
        count = (
            db.query(func.count(AvatarAssignment.id))
            .filter(
                AvatarAssignment.group_id == group.id,
                AvatarAssignment.is_excluded == False,  # noqa: E712
            )
            .scalar()
        )
        if count < 5:
            raise ValueError(
                f"Group '{group.name}' has {count} avatars, minimum 5 required."
            )

    # Freeze config: store current config in config_history
    now = _now()
    config_snapshot = {
        "frozen_at": now.isoformat(),
        "daily_volume_per_avatar": experiment.daily_volume_per_avatar,
        "subreddit_risk_max": experiment.subreddit_risk_max,
        "content_type": experiment.content_type,
        "generation_model": experiment.generation_model,
        "planned_duration_weeks": experiment.planned_duration_weeks,
    }
    history = experiment.config_history or []
    history.append(config_snapshot)
    experiment.config_history = history

    # Transition to active
    experiment.status = "active"
    experiment.started_at = now
    db.flush()

    _emit_event(
        db,
        event_type="ab_experiment_started",
        message=f"A/B experiment '{experiment.name}' started.",
        metadata={
            "experiment_id": str(experiment.id),
            "group_count": len(groups),
        },
    )

    logger.info("Experiment started: %s (id=%s)", experiment.name, experiment.id)
    return experiment


def pause_experiment(
    db: Session,
    experiment_id: uuid.UUID,
    reason: str,
) -> ExperimentRun:
    """Pause an active experiment.

    Records the pause timestamp and reason. Transitions active → paused.

    Returns:
        The updated ExperimentRun.

    Raises:
        ValueError: If experiment not found or not active.
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise ValueError(f"Experiment {experiment_id} not found.")
    if experiment.status != "active":
        raise ValueError("Can only pause experiments in 'active' state.")

    now = _now()
    experiment.status = "paused"
    experiment.paused_at = now
    experiment.pause_reason = reason
    db.flush()

    _emit_event(
        db,
        event_type="ab_experiment_paused",
        message=f"A/B experiment '{experiment.name}' paused: {reason}",
        metadata={
            "experiment_id": str(experiment.id),
            "reason": reason,
            "paused_at": now.isoformat(),
        },
    )

    logger.info(
        "Experiment paused: %s (reason=%s)", experiment.name, reason
    )
    return experiment


def resume_experiment(
    db: Session,
    experiment_id: uuid.UUID,
) -> ExperimentRun:
    """Resume a paused experiment.

    Re-activates enforcement and transitions paused → active.

    Returns:
        The updated ExperimentRun.

    Raises:
        ValueError: If experiment not found or not paused.
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise ValueError(f"Experiment {experiment_id} not found.")
    if experiment.status != "paused":
        raise ValueError("Can only resume experiments in 'paused' state.")

    now = _now()
    experiment.status = "active"
    experiment.resumed_at = now
    experiment.pause_reason = None
    db.flush()

    _emit_event(
        db,
        event_type="ab_experiment_resumed",
        message=f"A/B experiment '{experiment.name}' resumed.",
        metadata={
            "experiment_id": str(experiment.id),
            "resumed_at": now.isoformat(),
        },
    )

    logger.info("Experiment resumed: %s", experiment.name)
    return experiment


def conclude_experiment(
    db: Session,
    experiment_id: uuid.UUID,
) -> ExperimentRun:
    """Conclude an active experiment.

    Transitions active → concluded and triggers final report generation.

    Returns:
        The updated ExperimentRun.

    Raises:
        ValueError: If experiment not found or not active.
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise ValueError(f"Experiment {experiment_id} not found.")
    if experiment.status != "active":
        raise ValueError("Can only conclude experiments in 'active' state.")

    now = _now()
    experiment.status = "concluded"
    experiment.concluded_at = now
    db.flush()

    _emit_event(
        db,
        event_type="ab_experiment_concluded",
        message=f"A/B experiment '{experiment.name}' concluded.",
        metadata={
            "experiment_id": str(experiment.id),
            "concluded_at": now.isoformat(),
        },
    )

    logger.info("Experiment concluded: %s", experiment.name)
    return experiment


def abort_experiment(
    db: Session,
    experiment_id: uuid.UUID,
    reason: str,
) -> ExperimentRun:
    """Abort an experiment from any state.

    Marks the experiment as aborted with a reason.
    Can be called from any non-terminal state.

    Returns:
        The updated ExperimentRun.

    Raises:
        ValueError: If experiment not found or already in terminal state.
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise ValueError(f"Experiment {experiment_id} not found.")
    if experiment.status in ("concluded", "aborted"):
        raise ValueError(
            f"Cannot abort experiment in '{experiment.status}' state."
        )

    now = _now()
    experiment.status = "aborted"
    experiment.pause_reason = reason  # Re-use pause_reason for abort reason
    experiment.concluded_at = now
    db.flush()

    _emit_event(
        db,
        event_type="ab_experiment_aborted",
        message=f"A/B experiment '{experiment.name}' aborted: {reason}",
        metadata={
            "experiment_id": str(experiment.id),
            "reason": reason,
            "aborted_at": now.isoformat(),
        },
    )

    logger.info(
        "Experiment aborted: %s (reason=%s)", experiment.name, reason
    )
    return experiment


# ---------------------------------------------------------------------------
# Avatar Exclusion
# ---------------------------------------------------------------------------


def exclude_avatar(
    db: Session,
    experiment_id: uuid.UUID,
    avatar_id: uuid.UUID,
    reason: str,
) -> AvatarAssignment:
    """Mark an avatar as excluded from the experiment.

    Records the exclusion reason and date.

    Returns:
        The updated AvatarAssignment.

    Raises:
        ValueError: If assignment not found or already excluded.
    """
    assignment = db.query(AvatarAssignment).filter(
        AvatarAssignment.experiment_id == experiment_id,
        AvatarAssignment.avatar_id == avatar_id,
    ).first()
    if not assignment:
        raise ValueError(
            f"Avatar {avatar_id} not found in experiment {experiment_id}."
        )
    if assignment.is_excluded:
        raise ValueError(
            f"Avatar {avatar_id} is already excluded from experiment {experiment_id}."
        )

    now = _now()
    assignment.is_excluded = True
    assignment.excluded_at = now
    assignment.exclusion_reason = reason
    db.flush()

    _emit_event(
        db,
        event_type="ab_avatar_excluded",
        message=f"Avatar excluded from A/B experiment: {reason}",
        metadata={
            "experiment_id": str(experiment_id),
            "avatar_id": str(avatar_id),
            "reason": reason,
            "excluded_at": now.isoformat(),
        },
    )

    logger.info(
        "Avatar %s excluded from experiment %s: %s",
        avatar_id,
        experiment_id,
        reason,
    )
    return assignment


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def get_active_experiment_for_avatar(
    db: Session,
    avatar_id: uuid.UUID,
) -> ExperimentRun | None:
    """Return the active experiment (if any) for a given avatar.

    Looks up the avatar's assignment in any currently active experiment
    where the avatar is not excluded.

    Returns:
        The active ExperimentRun or None.
    """
    assignment = (
        db.query(AvatarAssignment)
        .join(ExperimentRun, AvatarAssignment.experiment_id == ExperimentRun.id)
        .filter(
            AvatarAssignment.avatar_id == avatar_id,
            AvatarAssignment.is_excluded == False,  # noqa: E712
            ExperimentRun.status == "active",
        )
        .first()
    )
    if not assignment:
        return None

    return db.query(ExperimentRun).filter(
        ExperimentRun.id == assignment.experiment_id
    ).first()


def is_avatar_in_experiment(
    db: Session,
    avatar_id: uuid.UUID,
) -> bool:
    """Fast boolean check: is this avatar in any active experiment?

    Used by pipeline hooks to determine if experiment overrides apply.

    Returns:
        True if avatar is assigned (non-excluded) to an active experiment.
    """
    exists = (
        db.query(AvatarAssignment.id)
        .join(ExperimentRun, AvatarAssignment.experiment_id == ExperimentRun.id)
        .filter(
            AvatarAssignment.avatar_id == avatar_id,
            AvatarAssignment.is_excluded == False,  # noqa: E712
            ExperimentRun.status == "active",
        )
        .first()
    )
    return exists is not None
