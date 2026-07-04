"""Intent Snapshot Collector — Layer 2 of Forecast & Reporting.

Collects all planned/upcoming actions for a client:
- EPGSlot (today/tomorrow) → daily_plan + weekly_plan
- CommentDraft (pending/approved) → weekly_plan
- Beat schedule (static Tue+Fri GEO batches) → weekly_plan
- Avatar phase + promotion criteria → phase_roadmap
- ClientSubredditAssignment (active) → coverage_plan

All queries are client-scoped (P7 isolation). No LLM calls.
Output: IntentSnapshot dataclass (dict-serializable).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.epg_slot import EPGSlot
from app.models.subreddit import ClientSubredditAssignment, Subreddit

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Validity windows (days) per intent category
VALIDITY_DAILY_EPG = 1
VALIDITY_PENDING_DRAFTS = 3
VALIDITY_GEO_BATCH = 7
VALIDITY_PHASE_ROADMAP = 90
VALIDITY_SUBREDDIT_COVERAGE = 30

# GEO batch static schedule: Tuesday and Friday at 09:30
GEO_BATCH_WEEKDAYS = (1, 4)  # Monday=0, Tuesday=1, ..., Friday=4
GEO_BATCH_HOUR = 9
GEO_BATCH_MINUTE = 30

# Phase promotion thresholds (mirrors phase.py defaults)
_P0_PROMOTION = {
    "min_age_days": 7,
    "min_karma": 10,
    "min_posted_comments": 3,
    "max_deleted_comments": 0,
}
_P1_PROMOTION = {
    "min_age_days": 60,
    "min_karma": 100,
    "min_activity": 20,
    "min_survival_rate": 80,
}
_P2_PROMOTION = {
    "min_age_days": 150,
    "min_karma": 500,
    "min_activity": 50,
    "min_survival_rate": 85,
    "min_avg_score": 2.0,
}

# Estimated weeks per phase for roadmap projection
_ESTIMATED_WEEKS = {
    0: 2,   # Phase 0 → 1: ~2 weeks (7d min + graduation buffer)
    1: 8,   # Phase 1 → 2: ~8 weeks (60d min age)
    2: 12,  # Phase 2 → 3: ~12 weeks (150d min age)
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExecutionIntent:
    """A planned action that has not yet produced a measured outcome."""

    intent_id: str  # e.g. "epg_slot:{uuid}"
    intent_type: str  # "comment_slot" | "geo_batch" | "phase_progression" | "strategy_update"
    status: str  # "planned" | "approved" | "scheduled" | "executing" | "expired"
    target_date: str  # ISO format datetime string
    validity_window_days: int
    linked_task_id: str | None  # UUID as string
    version: int
    created_at: str  # ISO format datetime string


@dataclass
class IntentSnapshot:
    """Point-in-time view of all planned actions for a client."""

    snapshot_version: int
    captured_at: str  # ISO format datetime string
    client_id: str  # UUID as string
    daily_plan: list[dict[str, Any]] = field(default_factory=list)
    weekly_plan: list[dict[str, Any]] = field(default_factory=list)
    phase_roadmap: list[dict[str, Any]] = field(default_factory=list)
    coverage_plan: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _make_intent(
    intent_id: str,
    intent_type: str,
    status: str,
    target_date: datetime,
    validity_window_days: int,
    linked_task_id: uuid.UUID | None = None,
    version: int = 1,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an ExecutionIntent dict."""
    now = datetime.now(timezone.utc)
    if target_date and target_date.tzinfo is None:
        target_date = target_date.replace(tzinfo=timezone.utc)
    if created_at and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return {
        "intent_id": intent_id,
        "intent_type": intent_type,
        "status": status,
        "target_date": target_date.isoformat() if target_date else now.isoformat(),
        "validity_window_days": validity_window_days,
        "linked_task_id": str(linked_task_id) if linked_task_id else None,
        "version": version,
        "created_at": (created_at or now).isoformat(),
    }


def _map_epg_status(slot_status: str) -> str:
    """Map EPGSlot status to intent status."""
    mapping = {
        "planned": "planned",
        "generated": "scheduled",
        "approved": "approved",
        "posted": "executing",
        "skipped": "expired",
        "expired": "expired",
    }
    return mapping.get(slot_status, "planned")


def _next_geo_batch_dates(from_date: date, count: int = 4) -> list[datetime]:
    """Compute next N GEO batch occurrences from current date.

    GEO batches run on Tue+Fri at 09:30 Israel time (approximated as UTC+3).
    """
    if count <= 0:
        return []

    results: list[datetime] = []
    current = from_date
    # Check up to 30 days ahead to find enough occurrences
    for day_offset in range(30):
        check_date = current + timedelta(days=day_offset)
        if check_date.weekday() in GEO_BATCH_WEEKDAYS:
            batch_dt = datetime(
                check_date.year,
                check_date.month,
                check_date.day,
                GEO_BATCH_HOUR,
                GEO_BATCH_MINUTE,
                tzinfo=timezone.utc,
            )
            # Only include future batches
            if batch_dt > datetime.now(timezone.utc):
                results.append(batch_dt)
            if len(results) >= count:
                break
    return results


# ---------------------------------------------------------------------------
# Main Collector
# ---------------------------------------------------------------------------


def collect_intent(db: Session, client_id: uuid.UUID) -> IntentSnapshot:
    """Collect all execution intents for a client.

    Gathers:
    - EPG slots (today + tomorrow) → daily_plan
    - EPG slots (next 7 days) + pending/approved drafts + GEO schedule → weekly_plan
    - Phase roadmap per avatar → phase_roadmap
    - Active subreddit coverage → coverage_plan

    Args:
        db: SQLAlchemy session.
        client_id: UUID of the client.

    Returns:
        IntentSnapshot with all planned actions.
    """
    now = datetime.now(timezone.utc)
    today = now.date()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=7)

    daily_plan = _collect_daily_epg(db, client_id, today, tomorrow)
    weekly_plan = _collect_weekly_plan(db, client_id, today, week_end)
    phase_roadmap = _collect_phase_roadmap(db, client_id, now)
    coverage_plan = _collect_coverage_plan(db, client_id)

    snapshot = IntentSnapshot(
        snapshot_version=1,
        captured_at=now.isoformat(),
        client_id=str(client_id),
        daily_plan=daily_plan,
        weekly_plan=weekly_plan,
        phase_roadmap=phase_roadmap,
        coverage_plan=coverage_plan,
    )

    logger.info(
        "Collected intent snapshot for client %s: %d daily, %d weekly, %d roadmap, %d coverage",
        client_id,
        len(daily_plan),
        len(weekly_plan),
        len(phase_roadmap),
        len(coverage_plan),
    )

    return snapshot


# ---------------------------------------------------------------------------
# Daily EPG Collection
# ---------------------------------------------------------------------------


def _collect_daily_epg(
    db: Session,
    client_id: uuid.UUID,
    today: date,
    tomorrow: date,
) -> list[dict[str, Any]]:
    """Collect EPG slots for today and tomorrow.

    Returns ExecutionIntent dicts for each slot with status in
    (planned, generated, approved).
    """
    slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.client_id == client_id,
            EPGSlot.plan_date.in_([today, tomorrow]),
            EPGSlot.status.in_(["planned", "generated", "approved"]),
        )
        .order_by(EPGSlot.scheduled_at.asc().nullslast(), EPGSlot.created_at.asc())
        .all()
    )

    intents: list[dict[str, Any]] = []
    for slot in slots:
        target_dt = slot.scheduled_at or datetime.combine(
            slot.plan_date, datetime.min.time(), tzinfo=timezone.utc
        )
        intents.append(
            _make_intent(
                intent_id=f"epg_slot:{slot.id}",
                intent_type="comment_slot",
                status=_map_epg_status(slot.status),
                target_date=target_dt,
                validity_window_days=VALIDITY_DAILY_EPG,
                linked_task_id=slot.id,
                version=1,
                created_at=slot.created_at,
            )
        )

    return intents


# ---------------------------------------------------------------------------
# Weekly Plan Collection
# ---------------------------------------------------------------------------


def _collect_weekly_plan(
    db: Session,
    client_id: uuid.UUID,
    today: date,
    week_end: date,
) -> list[dict[str, Any]]:
    """Collect weekly execution plan: EPG slots + pending drafts + GEO schedule.

    Combines:
    - EPG slots for the next 7 days (beyond today/tomorrow)
    - Pending/approved CommentDrafts (validity: 3 days)
    - Static GEO batch schedule (Tue+Fri 09:30, validity: 7 days)
    """
    intents: list[dict[str, Any]] = []

    # 1. EPG slots for next 7 days
    day_after_tomorrow = today + timedelta(days=2)
    future_slots = (
        db.query(EPGSlot)
        .filter(
            EPGSlot.client_id == client_id,
            EPGSlot.plan_date >= day_after_tomorrow,
            EPGSlot.plan_date <= week_end,
            EPGSlot.status.in_(["planned", "generated", "approved"]),
        )
        .order_by(EPGSlot.plan_date.asc(), EPGSlot.scheduled_at.asc().nullslast())
        .all()
    )

    for slot in future_slots:
        target_dt = slot.scheduled_at or datetime.combine(
            slot.plan_date, datetime.min.time(), tzinfo=timezone.utc
        )
        intents.append(
            _make_intent(
                intent_id=f"epg_slot:{slot.id}",
                intent_type="comment_slot",
                status=_map_epg_status(slot.status),
                target_date=target_dt,
                validity_window_days=VALIDITY_DAILY_EPG,
                linked_task_id=slot.id,
                version=1,
                created_at=slot.created_at,
            )
        )

    # 2. Pending/approved drafts (not yet in EPG slots — standalone intent)
    pending_drafts = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.client_id == client_id,
            CommentDraft.status.in_(["pending", "approved"]),
        )
        .order_by(CommentDraft.created_at.desc())
        .limit(50)  # Cap to prevent huge result sets
        .all()
    )

    for draft in pending_drafts:
        intent_status = "approved" if draft.status == "approved" else "planned"
        intents.append(
            _make_intent(
                intent_id=f"draft:{draft.id}",
                intent_type="comment_slot",
                status=intent_status,
                target_date=draft.created_at,
                validity_window_days=VALIDITY_PENDING_DRAFTS,
                linked_task_id=draft.id,
                version=1,
                created_at=draft.created_at,
            )
        )

    # 3. Static GEO batch schedule (next occurrences)
    geo_dates = _next_geo_batch_dates(today, count=4)
    for i, geo_dt in enumerate(geo_dates):
        intents.append(
            _make_intent(
                intent_id=f"geo_batch:next_{i + 1}",
                intent_type="geo_batch",
                status="scheduled",
                target_date=geo_dt,
                validity_window_days=VALIDITY_GEO_BATCH,
                linked_task_id=None,
                version=1,
                created_at=datetime.now(timezone.utc),
            )
        )

    return intents


# ---------------------------------------------------------------------------
# Phase Roadmap Collection
# ---------------------------------------------------------------------------


def _collect_phase_roadmap(
    db: Session,
    client_id: uuid.UUID,
    now: datetime,
) -> list[dict[str, Any]]:
    """Build phase roadmap for each avatar belonging to this client.

    For each avatar, includes:
    - current_phase
    - projected_next_phase
    - estimated_weeks_to_promotion
    - promotion_criteria (what's needed)
    - days_in_current_phase
    - blockers (frozen, shadowbanned, etc.)
    """
    # Find avatars assigned to this client
    # Avatar.client_ids is an ARRAY(String) containing client UUID strings
    client_id_str = str(client_id)

    avatars = (
        db.query(Avatar)
        .filter(
            Avatar.active == True,  # noqa: E712
            Avatar.client_ids.any(client_id_str),
        )
        .all()
    )

    if not avatars:
        return []

    roadmap: list[dict[str, Any]] = []

    for avatar in avatars:
        current_phase = avatar.warming_phase or 1
        days_in_phase = 0
        if avatar.phase_changed_at:
            phase_start = avatar.phase_changed_at
            if phase_start.tzinfo is None:
                phase_start = phase_start.replace(tzinfo=timezone.utc)
            days_in_phase = max(0, (now - phase_start).days)

        # Determine next phase and criteria
        next_phase = min(current_phase + 1, 3)
        promotion_criteria = _get_promotion_criteria(current_phase)
        estimated_weeks = _estimate_weeks_to_promotion(
            current_phase, days_in_phase
        )

        # Identify blockers
        blockers: list[str] = []
        if avatar.is_frozen:
            blockers.append("frozen")
        if avatar.is_shadowbanned:
            blockers.append("shadowbanned")
        if hasattr(avatar, "cqs_level") and avatar.cqs_level == "lowest":
            blockers.append("cqs_lowest")

        entry = {
            "avatar_id": str(avatar.id),
            "avatar_username": avatar.reddit_username,
            "current_phase": current_phase,
            "projected_next_phase": next_phase if current_phase < 3 else None,
            "estimated_weeks_to_promotion": estimated_weeks if current_phase < 3 else None,
            "days_in_current_phase": days_in_phase,
            "promotion_criteria": promotion_criteria,
            "blockers": blockers,
            "is_frozen": avatar.is_frozen,
            "warming_phase_label": _phase_label(current_phase),
        }

        roadmap.append(entry)

    return roadmap


def _get_promotion_criteria(current_phase: int) -> dict[str, Any]:
    """Get the promotion criteria for graduating from current_phase to next."""
    if current_phase == 0:
        return _P0_PROMOTION.copy()
    elif current_phase == 1:
        return _P1_PROMOTION.copy()
    elif current_phase == 2:
        return _P2_PROMOTION.copy()
    else:
        # Phase 3 is max
        return {}


def _estimate_weeks_to_promotion(current_phase: int, days_in_phase: int) -> int | None:
    """Estimate weeks remaining until promotion.

    Uses default timeline estimates minus time already spent.
    Returns None for Phase 3 (max phase).
    """
    if current_phase >= 3:
        return None

    estimated_total_weeks = _ESTIMATED_WEEKS.get(current_phase, 8)
    weeks_spent = days_in_phase / 7.0
    remaining_weeks = max(0, estimated_total_weeks - weeks_spent)
    return max(1, round(remaining_weeks))


def _phase_label(phase: int) -> str:
    """Human-readable phase label."""
    labels = {
        0: "Phase 0 (Incubation)",
        1: "Phase 1 (Hobby/Warming)",
        2: "Phase 2 (Professional)",
        3: "Phase 3 (Brand Integration)",
    }
    return labels.get(phase, f"Phase {phase}")


# ---------------------------------------------------------------------------
# Subreddit Coverage Collection
# ---------------------------------------------------------------------------


def _collect_coverage_plan(
    db: Session,
    client_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Collect active subreddit assignments with priority and engagement approach.

    Returns coverage entries with subreddit name, priority, engagement strategy,
    and assignment type.
    """
    assignments = (
        db.query(ClientSubredditAssignment, Subreddit)
        .join(Subreddit, ClientSubredditAssignment.subreddit_id == Subreddit.id)
        .filter(
            ClientSubredditAssignment.client_id == client_id,
            ClientSubredditAssignment.is_active == True,  # noqa: E712
        )
        .order_by(
            ClientSubredditAssignment.priority.asc().nullslast(),
            Subreddit.subreddit_name.asc(),
        )
        .all()
    )

    coverage: list[dict[str, Any]] = []

    for assignment, subreddit in assignments:
        coverage.append(
            {
                "subreddit_id": str(subreddit.id),
                "subreddit_name": subreddit.subreddit_name,
                "priority": assignment.priority,
                "engagement_approach": assignment.engagement_approach,
                "type": assignment.type,
                "is_active": assignment.is_active,
                "validity_window_days": VALIDITY_SUBREDDIT_COVERAGE,
            }
        )

    return coverage
