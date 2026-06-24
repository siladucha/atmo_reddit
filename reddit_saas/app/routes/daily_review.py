"""Daily Operations Review routes.

Provides:
- GET  /admin/daily-review              — Main page (start or resume)
- POST /admin/daily-review/start        — Create new session
- GET  /admin/daily-review/section/{name} — Load section partial (HTMX)
- POST /admin/daily-review/section/{name}/complete — Mark section done
- POST /admin/daily-review/section/{name}/save — Auto-save user inputs
- POST /admin/daily-review/complete     — Finalize session → generate report
- POST /admin/daily-review/decisions    — Add decision
- PATCH /admin/daily-review/decisions/{id} — Update decision status
- GET  /admin/daily-review/history      — Past reports (HTMX partial)
- GET  /admin/daily-review/budget       — Budget indicator (HTMX partial)
"""
from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.logging_config import get_logger
from app.models.daily_review_session import DailyReviewSession
from app.models.intelligence_report import IntelligenceReport
from app.models.review_decision import ReviewDecision
from app.models.user import User
from app.services.daily_review.signal_collector import create_review_snapshot
from app.services.daily_review.cost_governor import get_today_budget

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/daily-review")
templates = Jinja2Templates(directory="app/templates")
templates.env.cache = {}

from app.version import __version__ as app_version
from app.config import get_settings as _get_settings

templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled

from app.template_filters import register_filters
register_filters(templates.env)

# Phase 1 sections (Phase 2 adds: trends, hypotheses, forecast)
SECTIONS = ["health", "changes", "decisions"]
SECTION_LABELS = {
    "health": "Health Snapshot",
    "changes": "What Changed",
    "decisions": "Decisions",
}
SECTION_DURATIONS = {"health": 10, "changes": 15, "decisions": 5}


@router.get("", response_class=HTMLResponse)
def daily_review_page(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Main Daily Review page — start new or resume existing session."""
    # Check for in-progress session
    active_session = (
        db.query(DailyReviewSession)
        .filter(
            DailyReviewSession.user_id == current_user.id,
            DailyReviewSession.status == "in_progress",
        )
        .order_by(DailyReviewSession.started_at.desc())
        .first()
    )

    # Last completed report
    last_report = (
        db.query(IntelligenceReport)
        .order_by(IntelligenceReport.report_date.desc())
        .first()
    )

    hours_since_last = None
    if last_report:
        delta = datetime.now(timezone.utc) - last_report.created_at
        hours_since_last = int(delta.total_seconds() / 3600)

    budget = get_today_budget(db)

    return templates.TemplateResponse(
        name="admin_daily_review.html",
        context={
            "request": request,
            "current_user": current_user,
            "active_session": active_session,
            "last_report": last_report,
            "hours_since_last": hours_since_last,
            "sections": SECTIONS,
            "section_labels": SECTION_LABELS,
            "budget": budget.to_dict(),
            "today": date.today().isoformat(),
        },
    )


@router.post("/start", response_class=HTMLResponse)
def start_session(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Start a new Daily Review session — collects snapshot and creates session."""
    # Abandon any existing in-progress sessions
    old_sessions = (
        db.query(DailyReviewSession)
        .filter(
            DailyReviewSession.user_id == current_user.id,
            DailyReviewSession.status == "in_progress",
        )
        .all()
    )
    for old in old_sessions:
        old.status = "abandoned"

    # Collect snapshot (frozen data)
    snapshot = create_review_snapshot(db)

    # Create session
    session = DailyReviewSession(
        user_id=current_user.id,
        snapshot_id=snapshot.id,
        review_date=date.today(),
        status="in_progress",
        current_section="health",
        section_states={s: "pending" for s in SECTIONS},
        section_timestamps={},
        user_inputs={},
    )
    db.add(session)
    db.commit()

    logger.info(f"Daily Review session started: {session.id} by user {current_user.email}")

    # Redirect to the review page (which will now show the active session)
    return RedirectResponse(url="/admin/daily-review", status_code=303)


@router.get("/section/{name}", response_class=HTMLResponse)
def get_section(
    request: Request,
    name: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Load a section partial via HTMX."""
    if name not in SECTIONS:
        return HTMLResponse("<p>Unknown section</p>", status_code=404)

    session = _get_active_session(db, current_user)
    if not session:
        return HTMLResponse("<p>No active session</p>", status_code=404)

    # Mark section as in-progress
    states = session.section_states or {}
    if states.get(name) == "pending":
        states[name] = "in_progress"
        session.section_states = states
        ts = session.section_timestamps or {}
        ts[f"{name}_started_at"] = datetime.now(timezone.utc).isoformat()
        session.section_timestamps = ts
        session.current_section = name
        db.commit()

    # Load snapshot data
    from app.models.review_snapshot import ReviewSnapshot
    snapshot = db.query(ReviewSnapshot).filter(ReviewSnapshot.id == session.snapshot_id).first()

    template_name = f"partials/daily_review/section_{name}.html"

    context: dict = {
        "request": request,
        "session": session,
        "snapshot": snapshot,
        "section_name": name,
        "user_inputs": (session.user_inputs or {}).get(name, {}),
    }

    # Section-specific data
    if name == "health":
        context["health_data"] = snapshot.health_snapshot_json if snapshot else {}
    elif name == "changes":
        health = snapshot.health_snapshot_json if snapshot else {}
        context["changes"] = health.get("changes", [])
    elif name == "decisions":
        # Load open decisions from last 7 days
        week_ago = date.today() - timedelta(days=7)
        open_decisions = (
            db.query(ReviewDecision)
            .filter(
                ReviewDecision.status == "open",
                ReviewDecision.report_date >= week_ago,
            )
            .order_by(ReviewDecision.created_at.desc())
            .all()
        )
        context["open_decisions"] = open_decisions
        # Count decisions in current session
        session_decisions = (
            db.query(ReviewDecision)
            .filter(ReviewDecision.session_id == session.id)
            .count()
        )
        context["session_decision_count"] = session_decisions

    return templates.TemplateResponse(name=template_name, context=context)


@router.post("/section/{name}/save", response_class=HTMLResponse)
def save_section_inputs(
    request: Request,
    name: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Auto-save user inputs for a section (called on keystroke debounce)."""
    import json
    session = _get_active_session(db, current_user)
    if not session:
        return HTMLResponse("", status_code=204)

    # Parse form data (will be sent as form fields)
    # For simplicity, accept a JSON body or form field called 'data'
    # HTMX sends form data
    inputs = session.user_inputs or {}
    # We'll update on next request with actual form parsing
    # For now, just acknowledge
    db.commit()
    return HTMLResponse("", status_code=204)


@router.post("/section/{name}/complete", response_class=HTMLResponse)
def complete_section(
    request: Request,
    name: str,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Mark a section as completed and advance to next."""
    if name not in SECTIONS:
        return HTMLResponse("<p>Unknown section</p>", status_code=400)

    session = _get_active_session(db, current_user)
    if not session:
        return HTMLResponse("<p>No active session</p>", status_code=404)

    states = session.section_states or {}
    states[name] = "completed"
    session.section_states = states

    ts = session.section_timestamps or {}
    ts[f"{name}_completed_at"] = datetime.now(timezone.utc).isoformat()
    session.section_timestamps = ts

    # Advance to next section
    current_idx = SECTIONS.index(name)
    if current_idx < len(SECTIONS) - 1:
        session.current_section = SECTIONS[current_idx + 1]
    else:
        session.current_section = None  # All done

    db.commit()

    # Return updated sidebar partial
    return templates.TemplateResponse(
        name="partials/daily_review/sidebar.html",
        context={
            "request": request,
            "session": session,
            "sections": SECTIONS,
            "section_labels": SECTION_LABELS,
            "section_durations": SECTION_DURATIONS,
        },
    )


@router.post("/complete", response_class=HTMLResponse)
def complete_review(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Finalize the review session and generate the Intelligence Report."""
    session = _get_active_session(db, current_user)
    if not session:
        return RedirectResponse(url="/admin/daily-review", status_code=303)

    # Verify all sections completed
    states = session.section_states or {}
    incomplete = [s for s in SECTIONS if states.get(s) != "completed"]
    if incomplete:
        return HTMLResponse(
            f"<p class='text-red-400'>Sections not completed: {', '.join(incomplete)}</p>",
            status_code=400,
        )

    # Compute duration
    now = datetime.now(timezone.utc)
    duration_sec = int((now - session.started_at).total_seconds())

    # Generate report
    from app.models.review_snapshot import ReviewSnapshot
    snapshot = db.query(ReviewSnapshot).filter(ReviewSnapshot.id == session.snapshot_id).first()
    health_data = snapshot.health_snapshot_json if snapshot else {}

    # Get decisions for this session
    decisions = (
        db.query(ReviewDecision)
        .filter(ReviewDecision.session_id == session.id)
        .all()
    )

    report_raw = {
        "health_snapshot": health_data,
        "top_events": health_data.get("changes", [])[:3],
        "top_anomalies": [s for s in health_data.get("signals", []) if s.get("attention")][:3],
        "top_risks": [],  # Phase 2: from forecast
        "forecast_table": [],  # Phase 2
        "decisions": [
            {"type": d.decision_type, "description": d.description, "owner": d.owner}
            for d in decisions
        ],
        "overall_confidence": 50,  # Phase 2: aggregated from forecasts
    }

    report = IntelligenceReport(
        session_id=session.id,
        report_date=session.review_date,
        system_state=health_data.get("overall_verdict", "healthy"),
        report_raw=report_raw,
        report_summary=_generate_template_summary(health_data, decisions),
        narrative_mode="template",
        overall_confidence=50,
        total_llm_cost_usd=session.cost_used_usd,
    )

    # Finalize session
    session.status = "completed"
    session.completed_at = now
    session.total_duration_sec = duration_sec

    db.add(report)
    db.commit()

    logger.info(f"Daily Review completed: session={session.id}, report={report.id}, duration={duration_sec}s")

    return RedirectResponse(url="/admin/daily-review", status_code=303)


@router.post("/decisions", response_class=HTMLResponse)
def add_decision(
    request: Request,
    decision_type: str = Form(...),
    description: str = Form(...),
    owner: str = Form(...),
    deadline: str = Form(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Add a decision to the current session (max 3)."""
    session = _get_active_session(db, current_user)
    if not session:
        return HTMLResponse("<p>No active session</p>", status_code=404)

    # Enforce max 3
    existing_count = (
        db.query(ReviewDecision)
        .filter(ReviewDecision.session_id == session.id)
        .count()
    )
    if existing_count >= 3:
        return HTMLResponse(
            "<p class='text-red-400'>Maximum 3 decisions per session</p>",
            status_code=422,
        )

    deadline_date = None
    if deadline:
        try:
            deadline_date = date.fromisoformat(deadline)
        except ValueError:
            pass

    decision = ReviewDecision(
        session_id=session.id,
        report_date=session.review_date,
        decision_type=decision_type,
        description=description,
        owner=owner,
        deadline=deadline_date,
    )
    db.add(decision)
    db.commit()

    # Return updated decisions list partial
    decisions = (
        db.query(ReviewDecision)
        .filter(ReviewDecision.session_id == session.id)
        .order_by(ReviewDecision.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        name="partials/daily_review/decisions_list.html",
        context={"request": request, "decisions": decisions, "count": len(decisions)},
    )


@router.patch("/decisions/{decision_id}", response_class=HTMLResponse)
def update_decision(
    request: Request,
    decision_id: uuid.UUID,
    status: str = Form(...),
    resolution_note: str = Form(None),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Update decision status (done, deferred, cancelled)."""
    decision = db.query(ReviewDecision).filter(ReviewDecision.id == decision_id).first()
    if not decision:
        return HTMLResponse("<p>Decision not found</p>", status_code=404)

    if status in ("done", "deferred", "cancelled"):
        decision.status = status
        decision.resolution_note = resolution_note
        if status == "done":
            decision.resolved_at = datetime.now(timezone.utc)
        elif status == "deferred":
            decision.defer_count += 1
        db.commit()

    return HTMLResponse(f'<span class="text-green-400">Updated: {status}</span>')


@router.get("/history", response_class=HTMLResponse)
def review_history(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """List past Intelligence Reports."""
    reports = (
        db.query(IntelligenceReport)
        .order_by(IntelligenceReport.report_date.desc())
        .limit(30)
        .all()
    )
    return templates.TemplateResponse(
        name="partials/daily_review/history.html",
        context={"request": request, "reports": reports},
    )


@router.get("/budget", response_class=HTMLResponse)
def budget_indicator(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Budget indicator partial (polled every 30s)."""
    budget = get_today_budget(db)
    return templates.TemplateResponse(
        name="partials/daily_review/budget_indicator.html",
        context={"request": request, "budget": budget.to_dict()},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_active_session(db: Session, user: User) -> DailyReviewSession | None:
    """Get the current user's in-progress session."""
    return (
        db.query(DailyReviewSession)
        .filter(
            DailyReviewSession.user_id == user.id,
            DailyReviewSession.status == "in_progress",
        )
        .order_by(DailyReviewSession.started_at.desc())
        .first()
    )


def _generate_template_summary(health_data: dict, decisions: list) -> str:
    """Generate a simple template-based narrative (no LLM)."""
    verdict = health_data.get("overall_verdict", "unknown")
    changes = health_data.get("changes", [])
    n_changes = len(changes)
    n_decisions = len(decisions)

    lines = [
        f"System state: {verdict}.",
        f"Changes detected: {n_changes}.",
        f"Decisions made: {n_decisions}.",
    ]

    if changes:
        lines.append(f"Top change: {changes[0].get('signal', 'N/A')}.")

    if decisions:
        for d in decisions:
            lines.append(f"- [{d.decision_type}] {d.description} (owner: {d.owner})")

    return " ".join(lines)
