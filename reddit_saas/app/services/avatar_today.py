"""Avatar 'what to do today' computation.

Surfaces a single imperative action line, a daily-quota pill, a nearest
promotion gate, and a phase badge status for the Avatar Detail Overview tab.
Combines warming phase, daily quotas, recent activity, and health blockers
so an ops marketer can act without piecing rules from separate panels.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.avatar import Avatar
from app.models.comment_draft import CommentDraft
from app.models.hobby import HobbySubreddit
from app.services.smart_scoring import get_avatar_daily_limit


# Expected phase duration before stalled-coloring kicks in
PHASE_EXPECTED_DURATION_DAYS = {
    1: 14,
    2: 30,
    3: None,
}


@dataclass
class PhaseBadge:
    """Phase number + status suffix with semantic color."""

    phase_label: str  # "Mentor" | "Phase 1" | "Phase 2" | "Phase 3"
    status_suffix: str  # "On track" | "Day 8/14" | "Stalled 22d" | "Blocked" | "Eligible for promotion" | ""
    color: str  # "purple" | "green" | "blue" | "amber" | "red"


@dataclass
class TodayRecommendation:
    """Aggregate of all signals needed for the Today's Action card and header badge."""

    imperative: str
    blocker: str | None  # None | "shadowban" | "freeze" | "cqs_lowest" | "mentor"
    quota_used: int
    quota_limit: int
    quota_kind: str  # "hobby" | "professional" | "none"
    next_gate_label: str | None
    next_gate_current: float | int | None
    next_gate_required: float | int | None
    next_gate_pct: int  # 0-100
    days_in_phase: int
    phase_badge: PhaseBadge


def _count_hobby_today(db: Session, avatar: Avatar, now: datetime) -> int:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(HobbySubreddit.id))
        .filter(
            HobbySubreddit.avatar_username == avatar.reddit_username,
            HobbySubreddit.created_at >= today_start,
        )
        .scalar()
    ) or 0


def _count_pro_today(db: Session, avatar: Avatar, now: datetime) -> int:
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.avatar_id == avatar.id,
            CommentDraft.created_at >= today_start,
        )
        .scalar()
    ) or 0


def _days_in_phase(avatar: Avatar, now: datetime) -> int:
    if not avatar.phase_changed_at:
        return 0
    return max(0, (now - avatar.phase_changed_at).days)


def _detect_blocker(avatar: Avatar) -> str | None:
    if avatar.is_shadowbanned or avatar.health_status == "shadowbanned":
        return "shadowban"
    if avatar.is_frozen:
        return "freeze"
    if avatar.cqs_level == "lowest" and avatar.warming_phase >= 2:
        return "cqs_lowest"
    return None


def _nearest_gate(health: dict[str, Any]) -> tuple[str | None, float | None, float | None, int]:
    """Return (label, current, required, pct) for the closest unmet phase-progress gate.

    Picks the gate with the highest completion percentage that is still < 100%, so the
    marketer sees the gate they are about to clear, not the one furthest away.
    """
    progress = health.get("phase_progress") or {}
    if not progress:
        return (None, None, None, 0)

    candidates: list[tuple[str, float, float, int]] = []
    label_map = {
        "karma": "Karma",
        "age_days": "Account age (days)",
        "activity": "Activity (comments)",
        "survival_rate": "Survival rate (%)",
        "avg_score": "Avg score",
        "subreddit_diversity": "Subreddit diversity",
    }
    for key, label in label_map.items():
        entry = progress.get(key)
        if not isinstance(entry, dict):
            continue
        required = entry.get("required")
        current = entry.get("current")
        if required is None or current is None:
            continue
        if required == 0:
            continue  # waived
        try:
            req_f = float(required)
            cur_f = float(current)
        except (TypeError, ValueError):
            continue
        if cur_f >= req_f:
            continue
        pct = min(100, max(0, int((cur_f / req_f) * 100)))
        candidates.append((label, cur_f, req_f, pct))

    if not candidates:
        return (None, None, None, 100)
    candidates.sort(key=lambda c: c[3], reverse=True)
    return candidates[0]


def _phase_badge(
    avatar: Avatar,
    days_in_phase: int,
    blocker: str | None,
    eligible: bool,
) -> PhaseBadge:
    phase = avatar.warming_phase
    if phase == 0:
        return PhaseBadge(phase_label="Mentor", status_suffix="", color="purple")

    phase_label = f"Phase {phase}"

    if blocker:
        return PhaseBadge(phase_label=phase_label, status_suffix="Blocked", color="red")

    if eligible:
        return PhaseBadge(
            phase_label=phase_label,
            status_suffix="Eligible for promotion",
            color="green",
        )

    expected = PHASE_EXPECTED_DURATION_DAYS.get(phase)
    if expected is None:
        # Phase 3 — no expected cap, healthy by default
        return PhaseBadge(phase_label=phase_label, status_suffix="On track", color="green")

    if days_in_phase <= expected // 2:
        return PhaseBadge(
            phase_label=phase_label,
            status_suffix=f"Day {days_in_phase}/{expected}",
            color="blue",
        )
    if days_in_phase <= expected:
        return PhaseBadge(phase_label=phase_label, status_suffix="On track", color="green")
    if days_in_phase > int(expected * 1.5):
        return PhaseBadge(
            phase_label=phase_label,
            status_suffix=f"Stalled {days_in_phase}d",
            color="amber",
        )
    return PhaseBadge(
        phase_label=phase_label,
        status_suffix=f"Day {days_in_phase}/{expected}",
        color="blue",
    )


def _imperative_for_blocker(blocker: str) -> str:
    if blocker == "shadowban":
        return "Blocked: shadowbanned — run health check, do not post"
    if blocker == "freeze":
        return "Blocked: frozen by ops — see Profile & Safety"
    if blocker == "cqs_lowest":
        return "Blocked: CQS=lowest — pipeline auto-restricted to 1 hobby/day"
    return "Blocked"


def _imperative_for_phase(
    phase: int,
    eligible: bool,
    quota_used: int,
    quota_limit: int,
    quota_kind: str,
    pro_pending: int,
) -> str:
    if phase == 0:
        return "Mentor — no pipeline action expected today"
    if eligible:
        return f"Eligible for promotion to Phase {phase + 1} — review evidence"
    if quota_limit > 0 and quota_used >= quota_limit:
        kind_label = "hobby" if quota_kind == "hobby" else "comments"
        return f"Quota met ({quota_used}/{quota_limit} {kind_label} today) — wait until 00:00 UTC"
    if phase == 1:
        remaining = quota_limit - quota_used
        return f"Post {remaining} hobby comment{'s' if remaining != 1 else ''} (e.g. via Pipeline tab)"
    if phase in (2, 3):
        if pro_pending > 0:
            return f"Review {pro_pending} pending draft{'s' if pro_pending != 1 else ''} in Content tab"
        remaining = quota_limit - quota_used
        return f"Generate up to {remaining} more draft{'s' if remaining != 1 else ''} today"
    return "No action recommended"


def compute_today_recommendation(
    db: Session,
    avatar: Avatar,
    health: dict[str, Any],
    pro_pending: int,
) -> TodayRecommendation:
    """Compute the full Today's Action signal set for the Overview card and header badge.

    Pure-ish: reads two extra counters from db (hobby + pro today) but does no mutations.
    """
    now = datetime.now(timezone.utc)
    days_in_phase = _days_in_phase(avatar, now)
    blocker = _detect_blocker(avatar)
    eligible = bool(health.get("phase_eligible_for_next"))

    daily_limit = get_avatar_daily_limit(avatar)
    if avatar.warming_phase == 1:
        quota_used = _count_hobby_today(db, avatar, now)
        quota_kind = "hobby"
    elif avatar.warming_phase in (2, 3):
        quota_used = _count_pro_today(db, avatar, now)
        quota_kind = "professional"
    else:
        quota_used = 0
        quota_kind = "none"

    if blocker:
        imperative = _imperative_for_blocker(blocker)
    else:
        imperative = _imperative_for_phase(
            phase=avatar.warming_phase,
            eligible=eligible,
            quota_used=quota_used,
            quota_limit=daily_limit,
            quota_kind=quota_kind,
            pro_pending=pro_pending,
        )

    gate_label, gate_current, gate_required, gate_pct = _nearest_gate(health)

    badge = _phase_badge(avatar, days_in_phase, blocker, eligible)

    return TodayRecommendation(
        imperative=imperative,
        blocker=blocker,
        quota_used=quota_used,
        quota_limit=daily_limit,
        quota_kind=quota_kind,
        next_gate_label=gate_label,
        next_gate_current=gate_current,
        next_gate_required=gate_required,
        next_gate_pct=gate_pct,
        days_in_phase=days_in_phase,
        phase_badge=badge,
    )
