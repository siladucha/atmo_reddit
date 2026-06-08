"""System Inspector service — diagnostics, funnel, client breakdown, recommendations.

Each check returns detail items (specific records) for drill-down in the UI.
"""

from __future__ import annotations

from app.logging_config import get_logger
from datetime import datetime, timedelta, timezone

from sqlalchemy import asc, func
from sqlalchemy.orm import Session

from app.models.activity_event import ActivityEvent
from app.models.avatar import Avatar
from app.models.client import Client
from app.models.comment_draft import CommentDraft
from app.models.scrape_log import ScrapeLog
from app.models.thread import RedditThread

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pipeline Funnel
# ---------------------------------------------------------------------------


def get_pipeline_funnel(db: Session) -> dict:
    """Compute pipeline funnel: how many items at each stage right now."""
    now = datetime.now(timezone.utc)
    last_7d = now - timedelta(days=7)

    scraped = (
        db.query(func.count(RedditThread.id))
        .filter(RedditThread.created_at >= last_7d)
        .scalar()
    ) or 0

    scored = (
        db.query(func.count(RedditThread.id))
        .filter(RedditThread.created_at >= last_7d, RedditThread.tag.isnot(None))
        .scalar()
    ) or 0

    engage = (
        db.query(func.count(RedditThread.id))
        .filter(RedditThread.created_at >= last_7d, RedditThread.tag == "engage")
        .scalar()
    ) or 0

    generated = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.created_at >= last_7d)
        .scalar()
    ) or 0

    pending = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0

    approved = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.status == "approved", CommentDraft.posted_at.is_(None))
        .scalar()
    ) or 0

    posted = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.status == "posted", CommentDraft.posted_at >= last_7d)
        .scalar()
    ) or 0

    stages = [
        {"label": "Scraped", "value": scraped, "color": "bg-slate-500", "text_color": "text-gray-300"},
        {"label": "Scored", "value": scored, "color": "bg-blue-600", "text_color": "text-blue-300"},
        {"label": "Engage", "value": engage, "color": "bg-indigo-600", "text_color": "text-indigo-300"},
        {"label": "Generated", "value": generated, "color": "bg-purple-600", "text_color": "text-purple-300"},
        {"label": "Pending", "value": pending, "color": "bg-amber-600", "text_color": "text-amber-300"},
        {"label": "Approved", "value": approved, "color": "bg-cyan-600", "text_color": "text-cyan-300"},
        {"label": "Posted", "value": posted, "color": "bg-emerald-600", "text_color": "text-emerald-300"},
    ]

    max_value = max((s["value"] for s in stages), default=1) or 1

    # Conversion rates between adjacent stages
    rates = []
    for i in range(len(stages)):
        if i == 0:
            rates.append({"pct": 100})
        else:
            prev = stages[i - 1]["value"]
            curr = stages[i]["value"]
            pct = int((curr / prev * 100) if prev > 0 else 0)
            rates.append({"pct": pct})

    return {"stages": stages, "max_value": max_value, "rates": rates}


# ---------------------------------------------------------------------------
# Client Breakdown
# ---------------------------------------------------------------------------


def get_client_breakdown(db: Session) -> list[dict]:
    """Per-client queue status for the last 7 days."""
    now = datetime.now(timezone.utc)
    last_7d = now - timedelta(days=7)

    clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )

    result = []
    for client in clients:
        cid = client.id

        threads_7d = (
            db.query(func.count(RedditThread.id))
            .filter(RedditThread.client_id == cid, RedditThread.created_at >= last_7d)
            .scalar()
        ) or 0

        pending = (
            db.query(func.count(CommentDraft.id))
            .filter(CommentDraft.client_id == cid, CommentDraft.status == "pending")
            .scalar()
        ) or 0

        approved = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == cid,
                CommentDraft.status == "approved",
                CommentDraft.posted_at.is_(None),
            )
            .scalar()
        ) or 0

        posted_7d = (
            db.query(func.count(CommentDraft.id))
            .filter(
                CommentDraft.client_id == cid,
                CommentDraft.status == "posted",
                CommentDraft.posted_at >= last_7d,
            )
            .scalar()
        ) or 0

        # Determine issue
        issue = ""
        if pending > 20:
            issue = "queue overflow"
        elif approved > 5:
            issue = "not posting"
        elif threads_7d == 0:
            issue = "no threads"

        result.append({
            "name": client.client_name,
            "threads_7d": threads_7d,
            "pending": pending,
            "approved": approved,
            "posted_7d": posted_7d,
            "issue": issue,
        })

    return result


# ---------------------------------------------------------------------------
# Recommendations engine
# ---------------------------------------------------------------------------


def get_recommendations(db: Session, report: dict, funnel: dict, pipeline_enabled: bool, generation_enabled: bool, scrape_enabled: bool) -> list[dict]:
    """Generate actionable recommendations based on current state."""
    recs = []

    # Check if pipeline is off
    if not pipeline_enabled:
        recs.append({
            "priority": "high",
            "text": "Pipeline is paused. No scoring or generation is happening.",
            "action_id": "toggle-pipeline",
            "action_params": "?enabled=true",
            "action_label": "Resume",
            "confirm": "Resume the pipeline?",
        })

    if not scrape_enabled:
        recs.append({
            "priority": "high",
            "text": "Scraping is paused. No new threads are being collected.",
            "action_id": "toggle-scraping",
            "action_params": "?enabled=true",
            "action_label": "Resume",
            "confirm": "Resume scraping?",
        })

    # Check for actionable issues from report
    for check in report.get("checks", []):
        if check["status"] == "critical" and check.get("actionable"):
            recs.append({
                "priority": "high",
                "text": f"{check['label']}: {check['details']}",
                "action_id": check["action_id"],
                "action_label": check["action_label"],
                "confirm": f"{check['action_label']}? This will modify data.",
            })
        elif check["status"] == "warning" and check.get("actionable") and check.get("count", 0) > 5:
            recs.append({
                "priority": "medium",
                "text": f"{check['label']}: {check['details']}",
                "action_id": check["action_id"],
                "action_label": check["action_label"],
                "confirm": f"{check['action_label']}? This will modify data.",
            })

    # Funnel bottleneck detection
    stages = funnel.get("stages", [])
    if len(stages) >= 5:
        pending_val = stages[4]["value"]  # Pending
        approved_val = stages[5]["value"]  # Approved
        if pending_val > 20:
            recs.append({
                "priority": "medium",
                "text": f"{pending_val} comments waiting for review. Go to Review Queue.",
                "action_id": None,
                "action_label": "",
                "confirm": "",
            })
        if approved_val > 5:
            recs.append({
                "priority": "medium",
                "text": f"{approved_val} approved comments not yet posted to Reddit. Post them or reset.",
                "action_id": "reset_stuck_approved",
                "action_label": "Back to review",
                "confirm": "Move stuck approved comments back to pending?",
            })

    return recs


# ---------------------------------------------------------------------------
# Diagnostic checks (with detail items for drill-down)
# ---------------------------------------------------------------------------


def run_all_checks(db: Session) -> dict:
    """Run all diagnostic checks and return a summary report."""
    checks = [
        check_duplicate_pending_drafts(db),
        check_stuck_approved_comments(db),
        check_orphan_drafts(db),
        check_status_violations(db),
        check_scrape_pipeline_alive(db),
        check_scoring_pipeline_alive(db),
        check_generation_pipeline_alive(db),
        check_review_queue_age(db),
        check_frozen_avatars(db),
        check_shadowbanned_avatars(db),
        check_deleted_comments(db),
    ]

    summary = {"ok": 0, "warning": 0, "critical": 0}
    for c in checks:
        summary[c["status"]] += 1

    if summary["critical"] > 0:
        overall = "critical"
    elif summary["warning"] > 0:
        overall = "warning"
    else:
        overall = "ok"

    return {
        "status": overall,
        "checks": checks,
        "summary": summary,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def _base_check(check_id: str, label: str, status: str, details: str, hint: str = "",
                count: int = 0, actionable: bool = False, action_id: str = "",
                action_label: str = "", items: list | None = None,
                items_columns: list | None = None) -> dict:
    return {
        "check": check_id,
        "label": label,
        "status": status,
        "details": details,
        "hint": hint,
        "count": count,
        "actionable": actionable,
        "action_id": action_id,
        "action_label": action_label,
        "records": items or [],
        "records_columns": items_columns or [],
    }


def check_duplicate_pending_drafts(db: Session) -> dict:
    """One thread should have at most 1 pending draft."""
    dupes = (
        db.query(CommentDraft.thread_id, func.count(CommentDraft.id).label("cnt"))
        .filter(CommentDraft.status == "pending")
        .group_by(CommentDraft.thread_id)
        .having(func.count(CommentDraft.id) > 1)
        .all()
    )
    count = len(dupes)
    items = []
    if count > 0:
        # Get detail rows (max 20)
        for thread_id, cnt in dupes[:20]:
            drafts = (
                db.query(CommentDraft)
                .filter(CommentDraft.thread_id == thread_id, CommentDraft.status == "pending")
                .order_by(asc(CommentDraft.created_at))
                .all()
            )
            thread = db.query(RedditThread).filter(RedditThread.id == thread_id).first()
            title = (thread.post_title[:50] + "...") if thread and len(thread.post_title) > 50 else (thread.post_title if thread else "?")
            for d in drafts[1:]:  # skip the one we'd keep
                items.append([title, str(d.id)[:8], d.created_at.strftime("%m-%d %H:%M")])

        return _base_check(
            "duplicate_pending_drafts", "Duplicate Drafts", "warning",
            f"{count} thread(s) have multiple pending drafts",
            "AI generated multiple comments for the same post. Fix keeps the oldest, rejects the rest.",
            count=count, actionable=True, action_id="fix_duplicate_drafts", action_label="Keep oldest",
            items=items, items_columns=["Thread", "Draft ID", "Created"],
        )
    return _base_check("duplicate_pending_drafts", "Duplicate Drafts", "ok", "No duplicates")


def check_stuck_approved_comments(db: Session) -> dict:
    """Approved comments should be posted to Reddit within 24h."""
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    stuck_q = (
        db.query(CommentDraft)
        .filter(
            CommentDraft.status == "approved",
            CommentDraft.created_at < threshold,
            CommentDraft.posted_at.is_(None),
        )
        .order_by(asc(CommentDraft.created_at))
        .limit(20)
        .all()
    )
    total = (
        db.query(func.count(CommentDraft.id))
        .filter(
            CommentDraft.status == "approved",
            CommentDraft.created_at < threshold,
            CommentDraft.posted_at.is_(None),
        )
        .scalar()
    ) or 0

    if total == 0:
        return _base_check("stuck_approved_comments", "Approved Not Posted", "ok", "All approved comments posted on time")

    status = "critical" if total > 5 else "warning"
    items = []
    for d in stuck_q:
        thread = d.thread
        title = (thread.post_title[:40] + "...") if thread and len(thread.post_title) > 40 else (thread.post_title if thread else "?")
        avatar_name = d.avatar.reddit_username if d.avatar else "?"
        age_h = int((datetime.now(timezone.utc) - d.created_at).total_seconds() / 3600)
        items.append([title, avatar_name, f"{age_h}h ago", str(d.id)[:8]])

    return _base_check(
        "stuck_approved_comments", "Approved Not Posted", status,
        f"{total} comment(s) approved but not posted to Reddit (>24h)",
        "Nobody pasted these into Reddit. Fix moves them back to review.",
        count=total, actionable=True, action_id="reset_stuck_approved", action_label="Back to review",
        items=items, items_columns=["Thread", "Avatar", "Approved", "ID"],
    )


def check_orphan_drafts(db: Session) -> dict:
    """Drafts should reference existing threads and clients."""
    orphans = (
        db.query(CommentDraft)
        .filter(~CommentDraft.thread_id.in_(db.query(RedditThread.id)))
        .limit(20)
        .all()
    )
    total = (
        db.query(func.count(CommentDraft.id))
        .filter(~CommentDraft.thread_id.in_(db.query(RedditThread.id)))
        .scalar()
    ) or 0

    if total == 0:
        return _base_check("orphan_drafts", "Orphan Drafts", "ok", "All drafts have valid references")

    items = [[str(d.id)[:8], d.status, d.created_at.strftime("%m-%d %H:%M")] for d in orphans]
    return _base_check(
        "orphan_drafts", "Orphan Drafts", "warning",
        f"{total} draft(s) reference deleted threads",
        "These drafts point to data that no longer exists. Safe to delete.",
        count=total, actionable=True, action_id="delete_orphan_drafts", action_label="Delete",
        items=items, items_columns=["Draft ID", "Status", "Created"],
    )


def check_status_violations(db: Session) -> dict:
    """Rejected comments should never have a posted_at timestamp."""
    violations = (
        db.query(CommentDraft)
        .filter(CommentDraft.status == "rejected", CommentDraft.posted_at.isnot(None))
        .limit(20)
        .all()
    )
    total = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.status == "rejected", CommentDraft.posted_at.isnot(None))
        .scalar()
    ) or 0

    if total == 0:
        return _base_check("status_violations", "Status Conflict", "ok", "No impossible states found")

    items = [[str(d.id)[:8], d.posted_at.strftime("%m-%d %H:%M") if d.posted_at else "?"] for d in violations]
    return _base_check(
        "status_violations", "Status Conflict", "critical",
        f"{total} rejected comment(s) have a posted timestamp (impossible)",
        "Fix clears the posted timestamp on rejected comments.",
        count=total, actionable=True, action_id="fix_status_violations", action_label="Fix",
        items=items, items_columns=["Draft ID", "Posted At"],
    )


def check_scrape_pipeline_alive(db: Session) -> dict:
    """Scraping should run within its configured freshness window."""
    from app.services.settings import get_setting

    try:
        freshness_hours = int(get_setting(db, "scrape_freshness_window_hours") or "12")
    except (ValueError, TypeError):
        freshness_hours = 12

    threshold = datetime.now(timezone.utc) - timedelta(hours=freshness_hours)
    latest = db.query(func.max(ScrapeLog.scraped_at)).scalar()

    if latest is None:
        return _base_check(
            "scrape_pipeline_alive", "Scraping", "critical",
            "Never ran — no scrape records",
            "Check if scraping is enabled and the worker is running.",
        )

    minutes_ago = int((datetime.now(timezone.utc) - latest).total_seconds() / 60)
    hours_ago = round(minutes_ago / 60, 1)

    if latest < threshold:
        # Get last 5 scrape logs for context
        recent = db.query(ScrapeLog).order_by(ScrapeLog.scraped_at.desc()).limit(5).all()
        items = [
            [s.subreddit_name, s.scraped_at.strftime("%m-%d %H:%M"), str(s.posts_new), s.errors or "—"]
            for s in recent
        ]
        return _base_check(
            "scrape_pipeline_alive", "Scraping", "critical",
            f"Last scrape {hours_ago}h ago (interval: {freshness_hours}h)",
            "Scraper overdue. Check worker logs or Reddit API credentials.",
            count=minutes_ago,
            items=items, items_columns=["Subreddit", "Time", "New", "Error"],
        )

    return _base_check(
        "scrape_pipeline_alive", "Scraping", "ok",
        f"OK (last: {minutes_ago} min ago, interval: {freshness_hours}h)",
    )


def check_scoring_pipeline_alive(db: Session) -> dict:
    """Scoring should run at least every 4 hours."""
    threshold = datetime.now(timezone.utc) - timedelta(hours=4)
    latest = (
        db.query(func.max(ActivityEvent.created_at))
        .filter(ActivityEvent.event_type == "score")
        .scalar()
    )

    if latest is None:
        return _base_check(
            "scoring_pipeline_alive", "Scoring", "warning",
            "No scoring events yet",
            "Normal if system just started. Scoring runs at 08:00 and 14:00 UTC automatically.",
        )

    if latest < threshold:
        hours_ago = round((datetime.now(timezone.utc) - latest).total_seconds() / 3600, 1)
        return _base_check(
            "scoring_pipeline_alive", "Scoring", "warning",
            f"Last scoring {hours_ago}h ago (threshold: 4h)",
            "Check if pipeline is enabled and LLM API key is valid.",
        )

    return _base_check("scoring_pipeline_alive", "Scoring", "ok", "Running on schedule")


def check_generation_pipeline_alive(db: Session) -> dict:
    """Generation should run at least every 4 hours."""
    threshold = datetime.now(timezone.utc) - timedelta(hours=4)
    latest = (
        db.query(func.max(ActivityEvent.created_at))
        .filter(ActivityEvent.event_type == "generate")
        .scalar()
    )

    if latest is None:
        return _base_check(
            "generation_pipeline_alive", "Generation", "warning",
            "No generation events yet",
            "Normal if system just started. Generation runs automatically after scoring marks threads as relevant.",
        )

    if latest < threshold:
        hours_ago = round((datetime.now(timezone.utc) - latest).total_seconds() / 3600, 1)
        return _base_check(
            "generation_pipeline_alive", "Generation", "warning",
            f"Last generation {hours_ago}h ago (threshold: 4h)",
            "Check if generation is enabled and there are 'engage' threads.",
        )

    return _base_check("generation_pipeline_alive", "Generation", "ok", "Running on schedule")


def check_review_queue_age(db: Session) -> dict:
    """Pending comments older than 48h are stale."""
    threshold = datetime.now(timezone.utc) - timedelta(hours=48)
    stale_q = (
        db.query(CommentDraft)
        .filter(CommentDraft.status == "pending", CommentDraft.created_at < threshold)
        .order_by(asc(CommentDraft.created_at))
        .limit(20)
        .all()
    )
    total = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending", CommentDraft.created_at < threshold)
        .scalar()
    ) or 0

    pending_total = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.status == "pending")
        .scalar()
    ) or 0

    if total == 0:
        return _base_check("review_queue_age", "Stale Queue", "ok", f"No stale items (pending: {pending_total})")

    status = "critical" if total > 10 else "warning"
    items = []
    for d in stale_q:
        thread = d.thread
        title = (thread.post_title[:40] + "...") if thread and len(thread.post_title) > 40 else (thread.post_title if thread else "?")
        age_h = int((datetime.now(timezone.utc) - d.created_at).total_seconds() / 3600)
        items.append([title, f"{age_h}h", str(d.id)[:8]])

    return _base_check(
        "review_queue_age", "Stale Queue", status,
        f"{total} pending > 48h (total pending: {pending_total})",
        "These threads are probably dead. Fix rejects them to clear the queue.",
        count=total, actionable=True, action_id="reject_stale_pending", action_label="Reject stale",
        items=items, items_columns=["Thread", "Age", "ID"],
    )


def check_frozen_avatars(db: Session) -> dict:
    """Report frozen avatars with details."""
    frozen = db.query(Avatar).filter(Avatar.is_frozen.is_(True)).all()
    if not frozen:
        return _base_check("frozen_avatars", "Frozen Avatars", "ok", "None")

    items = [
        [a.reddit_username, a.freeze_reason or "—", a.frozen_at.strftime("%m-%d %H:%M") if a.frozen_at else "?"]
        for a in frozen[:20]
    ]
    return _base_check(
        "frozen_avatars", "Frozen Avatars", "warning",
        f"{len(frozen)} avatar(s) frozen",
        "Frozen avatars won't generate comments. Unfreeze in Avatars page.",
        count=len(frozen),
        items=items, items_columns=["Username", "Reason", "Frozen At"],
    )


def check_shadowbanned_avatars(db: Session) -> dict:
    """Report shadowbanned avatars with details."""
    banned = db.query(Avatar).filter(Avatar.is_shadowbanned.is_(True)).all()
    if not banned:
        return _base_check("shadowbanned_avatars", "Shadowbanned", "ok", "None detected")

    items = [
        [a.reddit_username, f"karma: {a.reddit_karma_comment}", a.reddit_status_checked_at.strftime("%m-%d %H:%M") if a.reddit_status_checked_at else "?"]
        for a in banned[:20]
    ]
    return _base_check(
        "shadowbanned_avatars", "Shadowbanned", "critical",
        f"{len(banned)} avatar(s) — their comments are invisible",
        "Reddit silently hides all posts. Freeze immediately, use different avatars.",
        count=len(banned),
        items=items, items_columns=["Username", "Karma", "Last Check"],
    )


def check_deleted_comments(db: Session) -> dict:
    """Comments removed by Reddit mods."""
    deleted_q = (
        db.query(CommentDraft)
        .filter(CommentDraft.is_deleted.is_(True))
        .order_by(CommentDraft.deleted_detected_at.desc())
        .limit(20)
        .all()
    )
    total = (
        db.query(func.count(CommentDraft.id))
        .filter(CommentDraft.is_deleted.is_(True))
        .scalar()
    ) or 0

    if total == 0:
        return _base_check("deleted_comments", "Removed by Mods", "ok", "None")

    status = "warning" if total > 5 else "ok"
    items = []
    for d in deleted_q:
        thread = d.thread
        title = (thread.post_title[:35] + "...") if thread and len(thread.post_title) > 35 else (thread.post_title if thread else "?")
        avatar_name = d.avatar.reddit_username if d.avatar else "?"
        detected = d.deleted_detected_at.strftime("%m-%d %H:%M") if d.deleted_detected_at else "?"
        items.append([title, avatar_name, detected])

    return _base_check(
        "deleted_comments", "Removed by Mods", status,
        f"{total} comment(s) removed",
        "If growing, review content style or target subreddits.",
        count=total,
        items=items, items_columns=["Thread", "Avatar", "Detected"],
    )


# ---------------------------------------------------------------------------
# Corrective actions
# ---------------------------------------------------------------------------


def action_fix_duplicate_drafts(db: Session) -> dict:
    """Keep the oldest pending draft per thread, reject the rest."""
    dupes = (
        db.query(CommentDraft.thread_id)
        .filter(CommentDraft.status == "pending")
        .group_by(CommentDraft.thread_id)
        .having(func.count(CommentDraft.id) > 1)
        .all()
    )

    affected = 0
    for (thread_id,) in dupes:
        drafts = (
            db.query(CommentDraft)
            .filter(CommentDraft.thread_id == thread_id, CommentDraft.status == "pending")
            .order_by(asc(CommentDraft.created_at))
            .all()
        )
        for draft in drafts[1:]:
            draft.status = "rejected"
            affected += 1

    if affected > 0:
        db.commit()

    return {"action": "fix_duplicate_drafts", "success": True,
            "message": f"Kept oldest, rejected {affected} duplicate(s)", "affected": affected}


def action_reset_stuck_approved(db: Session) -> dict:
    """Move stuck approved comments back to pending."""
    threshold = datetime.now(timezone.utc) - timedelta(hours=24)
    stuck = (
        db.query(CommentDraft)
        .filter(CommentDraft.status == "approved", CommentDraft.created_at < threshold, CommentDraft.posted_at.is_(None))
        .all()
    )
    affected = len(stuck)
    for draft in stuck:
        draft.status = "pending"
    if affected > 0:
        db.commit()
    return {"action": "reset_stuck_approved", "success": True,
            "message": f"Moved {affected} comment(s) back to review", "affected": affected}


def action_delete_orphan_drafts(db: Session) -> dict:
    """Delete drafts referencing non-existent threads."""
    orphan_ids = [
        r[0] for r in
        db.query(CommentDraft.id).filter(~CommentDraft.thread_id.in_(db.query(RedditThread.id))).all()
    ]
    affected = len(orphan_ids)
    if affected > 0:
        db.query(CommentDraft).filter(CommentDraft.id.in_(orphan_ids)).delete(synchronize_session=False)
        db.commit()
    return {"action": "delete_orphan_drafts", "success": True,
            "message": f"Deleted {affected} orphan draft(s)", "affected": affected}


def action_fix_status_violations(db: Session) -> dict:
    """Clear posted_at on rejected comments."""
    violations = (
        db.query(CommentDraft)
        .filter(CommentDraft.status == "rejected", CommentDraft.posted_at.isnot(None))
        .all()
    )
    affected = len(violations)
    for draft in violations:
        draft.posted_at = None
    if affected > 0:
        db.commit()
    return {"action": "fix_status_violations", "success": True,
            "message": f"Fixed {affected} status conflict(s)", "affected": affected}


def action_reject_stale_pending(db: Session) -> dict:
    """Reject pending comments older than 48h."""
    threshold = datetime.now(timezone.utc) - timedelta(hours=48)
    stale = (
        db.query(CommentDraft)
        .filter(CommentDraft.status == "pending", CommentDraft.created_at < threshold)
        .all()
    )
    affected = len(stale)
    for draft in stale:
        draft.status = "rejected"
    if affected > 0:
        db.commit()
    return {"action": "reject_stale_pending", "success": True,
            "message": f"Rejected {affected} stale comment(s)", "affected": affected}


# ---------------------------------------------------------------------------
# Pipeline control actions
# ---------------------------------------------------------------------------


def action_toggle_pipeline(db: Session, enabled: bool) -> dict:
    from app.services.settings import set_setting
    set_setting(db, "pipeline_enabled", "true" if enabled else "false")
    return {"action": "toggle_pipeline", "success": True,
            "message": f"Pipeline {'enabled' if enabled else 'disabled'}", "affected": 0}


def action_toggle_generation(db: Session, enabled: bool) -> dict:
    from app.services.settings import set_setting
    set_setting(db, "generation_enabled", "true" if enabled else "false")
    return {"action": "toggle_generation", "success": True,
            "message": f"Generation {'enabled' if enabled else 'disabled'}", "affected": 0}


def action_toggle_scraping(db: Session, enabled: bool) -> dict:
    from app.services.settings import set_setting
    set_setting(db, "scrape_enabled", "true" if enabled else "false")
    return {"action": "toggle_scraping", "success": True,
            "message": f"Scraping {'enabled' if enabled else 'disabled'}", "affected": 0}


# ---------------------------------------------------------------------------
# Action dispatcher
# ---------------------------------------------------------------------------

ACTIONS = {
    "fix_duplicate_drafts": action_fix_duplicate_drafts,
    "reset_stuck_approved": action_reset_stuck_approved,
    "delete_orphan_drafts": action_delete_orphan_drafts,
    "fix_status_violations": action_fix_status_violations,
    "reject_stale_pending": action_reject_stale_pending,
}


def execute_action(db: Session, action_id: str) -> dict:
    """Execute a corrective action by ID."""
    handler = ACTIONS.get(action_id)
    if not handler:
        return {"action": action_id, "success": False, "message": f"Unknown action: {action_id}", "affected": 0}
    try:
        return handler(db)
    except Exception as e:
        logger.exception(f"inspector.action_failed action={action_id}")
        return {"action": action_id, "success": False, "message": f"Error: {str(e)[:200]}", "affected": 0}
