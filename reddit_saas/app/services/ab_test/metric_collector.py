"""Metric Collector — weekly health metric collection for A/B test experiments.

Collects per-avatar health metrics from existing database tables and stores
them as immutable MetricSnapshot records. Metrics include removal rate,
karma velocity, shadowban events, CQS changes, subreddit bans, phase speed,
and account warnings.

Usage:
    from app.services.ab_test.metric_collector import collect_week_metrics

    snapshots = collect_week_metrics(db, experiment_id, week_number)
"""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models.ab_test import (
    AvatarAssignment,
    ExperimentRun,
    MetricSnapshot,
    ControlViolation,
)
from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.avatar_subreddit_ban import AvatarSubredditBan
from app.models.comment_draft import CommentDraft
from app.models.karma_snapshot import KarmaSnapshot

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def collect_week_metrics(
    db: Session,
    experiment_id: "str | __import__('uuid').UUID",
    week_number: int,
) -> list[MetricSnapshot]:
    """Collect all health metrics for all active (non-excluded) avatars in experiment.

    Computes week_start and week_end from experiment.started_at + week_number,
    then iterates each non-excluded avatar assignment to gather metrics and
    create immutable MetricSnapshot records.

    Args:
        db: SQLAlchemy session.
        experiment_id: UUID of the experiment.
        week_number: 1-based week within the experiment.

    Returns:
        List of MetricSnapshot records created (already added to session).
    """
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).one()

    if not experiment.started_at:
        logger.warning(
            "Experiment %s has no started_at, cannot collect metrics", experiment_id
        )
        return []

    # Compute week window
    week_start_dt = experiment.started_at + timedelta(weeks=week_number - 1)
    week_end_dt = week_start_dt + timedelta(weeks=1)

    week_start_date = week_start_dt.date() if isinstance(week_start_dt, datetime) else week_start_dt
    week_end_date = week_end_dt.date() if isinstance(week_end_dt, datetime) else week_end_dt

    # Get all non-excluded assignments
    assignments = (
        db.query(AvatarAssignment)
        .filter(
            AvatarAssignment.experiment_id == experiment_id,
            AvatarAssignment.is_excluded.is_(False),
        )
        .all()
    )

    snapshots: list[MetricSnapshot] = []

    for assignment in assignments:
        avatar_id = assignment.avatar_id
        group_id = assignment.group_id

        # Check if avatar was excluded mid-week
        excluded_mid_week = False
        if assignment.excluded_at and assignment.excluded_at < week_end_dt:
            if assignment.excluded_at > week_start_dt:
                excluded_mid_week = True
            else:
                # Excluded before this week started, skip entirely
                continue

        # Collect individual metrics
        removal_rate, total_posted, total_deleted = _collect_removal_rate(
            db, avatar_id, week_start_dt, week_end_dt
        )
        karma_4h, karma_24h, karma_7d = _collect_karma_velocity(
            db, avatar_id, week_start_dt, week_end_dt
        )
        shadowban_events = _collect_shadowban_events(
            db, avatar_id, week_start_dt, week_end_dt
        )
        cqs_start, cqs_end, cqs_changed = _collect_cqs_changes(
            db, avatar_id, assignment.assignment_snapshot, week_number
        )
        subreddit_bans = _collect_subreddit_bans(
            db, avatar_id, week_start_dt, week_end_dt
        )
        phase_start, phase_end, phase_promoted = _collect_phase_speed(
            db, avatar_id, assignment.assignment_snapshot
        )
        account_warnings = _collect_account_warnings(
            db, avatar_id, week_start_dt, week_end_dt
        )

        # Collect control variable violations for this week
        volume_violations, subreddit_violations = _collect_violations(
            db, experiment_id, avatar_id, week_start_date, week_end_date
        )

        snapshot = MetricSnapshot(
            experiment_id=experiment_id,
            avatar_id=avatar_id,
            group_id=group_id,
            week_number=week_number,
            week_start=week_start_date,
            week_end=week_end_date,
            removal_rate=removal_rate,
            total_posted=total_posted,
            total_deleted=total_deleted,
            karma_velocity_4h=karma_4h,
            karma_velocity_24h=karma_24h,
            karma_velocity_7d=karma_7d,
            shadowban_events=shadowban_events,
            cqs_level_start=cqs_start,
            cqs_level_end=cqs_end,
            cqs_changed=cqs_changed,
            subreddit_bans_new=subreddit_bans,
            phase_at_start=phase_start,
            phase_at_end=phase_end,
            phase_promoted=phase_promoted,
            account_warnings=account_warnings,
            volume_violations=volume_violations,
            subreddit_violations=subreddit_violations,
        )
        db.add(snapshot)
        snapshots.append(snapshot)

        if excluded_mid_week:
            logger.info(
                "Avatar %s excluded mid-week %d, partial data recorded",
                avatar_id, week_number,
            )

    logger.info(
        "Collected metrics for experiment %s week %d: %d snapshots",
        experiment_id, week_number, len(snapshots),
    )
    return snapshots


# ---------------------------------------------------------------------------
# Individual Metric Collectors
# ---------------------------------------------------------------------------


def _collect_removal_rate(
    db: Session,
    avatar_id: "str | __import__('uuid').UUID",
    week_start: datetime,
    week_end: datetime,
) -> tuple[float | None, int, int]:
    """Query CommentDraft for posted comments in the week window.

    Returns:
        (removal_rate, total_posted, total_deleted)
        removal_rate is None if total_posted == 0.
    """
    total_posted = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= week_start,
            CommentDraft.posted_at < week_end,
        )
        .scalar()
    ) or 0

    total_deleted = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= week_start,
            CommentDraft.posted_at < week_end,
            CommentDraft.is_deleted.is_(True),
        )
        .scalar()
    ) or 0

    if total_posted == 0:
        return None, 0, 0

    rate = total_deleted / total_posted
    return rate, total_posted, total_deleted


def _collect_karma_velocity(
    db: Session,
    avatar_id: "str | __import__('uuid').UUID",
    week_start: datetime,
    week_end: datetime,
) -> tuple[float | None, float | None, float | None]:
    """Average KarmaSnapshot values for 4h, 24h, and 7d windows.

    Looks for karma snapshots of comments posted during this week.

    Returns:
        (avg_4h, avg_24h, avg_7d) — any can be None if no data.
    """
    # Get draft IDs posted during the week for this avatar
    draft_ids_subq = (
        db.query(CommentDraft.id)
        .filter(
            CommentDraft.avatar_id == avatar_id,
            CommentDraft.status == "posted",
            CommentDraft.posted_at >= week_start,
            CommentDraft.posted_at < week_end,
        )
        .subquery()
    )

    avg_4h = (
        db.query(func.avg(KarmaSnapshot.karma_value))
        .filter(
            KarmaSnapshot.comment_draft_id.in_(draft_ids_subq),
            KarmaSnapshot.check_window == "4h",
        )
        .scalar()
    )

    avg_24h = (
        db.query(func.avg(KarmaSnapshot.karma_value))
        .filter(
            KarmaSnapshot.comment_draft_id.in_(draft_ids_subq),
            KarmaSnapshot.check_window == "24h",
        )
        .scalar()
    )

    avg_7d = (
        db.query(func.avg(KarmaSnapshot.karma_value))
        .filter(
            KarmaSnapshot.comment_draft_id.in_(draft_ids_subq),
            KarmaSnapshot.check_window == "7d",
        )
        .scalar()
    )

    return (
        float(avg_4h) if avg_4h is not None else None,
        float(avg_24h) if avg_24h is not None else None,
        float(avg_7d) if avg_7d is not None else None,
    )


def _collect_shadowban_events(
    db: Session,
    avatar_id: "str | __import__('uuid').UUID",
    week_start: datetime,
    week_end: datetime,
) -> int:
    """Count ActivityEvent records with event_type containing 'shadowban' in the window.

    Looks for events like 'global_shadowban_detected' that indicate a
    shadowban transition.
    """
    count = (
        db.query(func.count(ActivityEvent.id))
        .filter(
            ActivityEvent.event_type.ilike("%shadowban%"),
            ActivityEvent.created_at >= week_start,
            ActivityEvent.created_at < week_end,
            ActivityEvent.event_metadata["avatar_id"].astext == str(avatar_id),
        )
        .scalar()
    ) or 0

    return count


def _collect_cqs_changes(
    db: Session,
    avatar_id: "str | __import__('uuid').UUID",
    assignment_snapshot: dict,
    week_number: int,
) -> tuple[str | None, str | None, bool]:
    """Compare current avatar CQS level vs snapshot/previous week.

    For week 1, cqs_start comes from assignment_snapshot.
    For subsequent weeks, cqs_start comes from the previous week's cqs_end.

    Returns:
        (cqs_level_start, cqs_level_end, cqs_changed)
    """
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        return None, None, False

    cqs_end = avatar.cqs_level

    if week_number == 1:
        cqs_start = assignment_snapshot.get("cqs_level")
    else:
        # Look for previous week's metric snapshot for this avatar
        prev_snapshot = (
            db.query(MetricSnapshot)
            .filter(
                MetricSnapshot.avatar_id == avatar_id,
                MetricSnapshot.week_number == week_number - 1,
            )
            .first()
        )
        cqs_start = prev_snapshot.cqs_level_end if prev_snapshot else assignment_snapshot.get("cqs_level")

    cqs_changed = cqs_start != cqs_end if (cqs_start is not None and cqs_end is not None) else False

    return cqs_start, cqs_end, cqs_changed


def _collect_subreddit_bans(
    db: Session,
    avatar_id: "str | __import__('uuid').UUID",
    week_start: datetime,
    week_end: datetime,
) -> int:
    """Count new AvatarSubredditBan records created during the week window."""
    count = (
        db.query(func.count(AvatarSubredditBan.id))
        .filter(
            AvatarSubredditBan.avatar_id == avatar_id,
            AvatarSubredditBan.banned_at >= week_start,
            AvatarSubredditBan.banned_at < week_end,
        )
        .scalar()
    ) or 0

    return count


def _collect_phase_speed(
    db: Session,
    avatar_id: "str | __import__('uuid').UUID",
    assignment_snapshot: dict,
) -> tuple[int, int, bool]:
    """Record current phase vs phase at assignment time.

    Returns:
        (phase_at_start, phase_at_end, phase_promoted)
        phase_at_start is from the assignment snapshot.
        phase_at_end is the avatar's current warming_phase.
    """
    avatar = db.query(Avatar).filter(Avatar.id == avatar_id).first()
    if not avatar:
        phase_start = assignment_snapshot.get("warming_phase", 1)
        return phase_start, phase_start, False

    phase_start = assignment_snapshot.get("warming_phase", 1)
    phase_end = avatar.warming_phase

    return phase_start, phase_end, phase_end > phase_start


def _collect_account_warnings(
    db: Session,
    avatar_id: "str | __import__('uuid').UUID",
    week_start: datetime,
    week_end: datetime,
) -> int:
    """Count health_status-related activity events indicating account warnings.

    Looks for events that indicate new restrictions or warnings
    (e.g., health_status changes to limited/suspended, or similar events).
    """
    count = (
        db.query(func.count(ActivityEvent.id))
        .filter(
            ActivityEvent.event_type.in_([
                "health_status_changed",
                "avatar_health_degraded",
                "account_warning_detected",
                "avatar_suspended",
                "avatar_limited",
            ]),
            ActivityEvent.created_at >= week_start,
            ActivityEvent.created_at < week_end,
            ActivityEvent.event_metadata["avatar_id"].astext == str(avatar_id),
        )
        .scalar()
    ) or 0

    return count


# ---------------------------------------------------------------------------
# Control Violation Collector
# ---------------------------------------------------------------------------


def _collect_violations(
    db: Session,
    experiment_id: "str | __import__('uuid').UUID",
    avatar_id: "str | __import__('uuid').UUID",
    week_start: date,
    week_end: date,
) -> tuple[int, int]:
    """Count control variable violations for an avatar during the week.

    Returns:
        (volume_violations, subreddit_violations)
    """
    volume_violations = (
        db.query(func.count(ControlViolation.id))
        .filter(
            ControlViolation.experiment_id == experiment_id,
            ControlViolation.avatar_id == avatar_id,
            ControlViolation.violation_type == "volume_exceeded",
            ControlViolation.violation_date >= week_start,
            ControlViolation.violation_date < week_end,
        )
        .scalar()
    ) or 0

    subreddit_violations = (
        db.query(func.count(ControlViolation.id))
        .filter(
            ControlViolation.experiment_id == experiment_id,
            ControlViolation.avatar_id == avatar_id,
            ControlViolation.violation_type == "subreddit_risk_exceeded",
            ControlViolation.violation_date >= week_start,
            ControlViolation.violation_date < week_end,
        )
        .scalar()
    ) or 0

    return volume_violations, subreddit_violations
