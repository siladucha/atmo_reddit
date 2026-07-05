"""Admin A/B Test routes — experiment creation, management, and reporting.

Provides admin UI for managing posting method A/B test experiments.
All routes require owner access.
"""

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import require_owner
from app.logging_config import get_logger
from app.models.ab_test import (
    AvatarAssignment,
    ControlViolation,
    ExperimentRun,
    MetricSnapshot,
    TreatmentGroup,
    WeeklyReport,
)
from app.models.avatar import Avatar
from app.services.ab_test import experiment_manager
from app.services.ab_test.statistical_reporter import generate_final_report

logger = get_logger(__name__)

router = APIRouter(prefix="/admin/ab-tests", tags=["admin-ab-tests"])
templates = Jinja2Templates(directory="app/templates")
# Disable Jinja2 bytecode cache to avoid "unhashable type: dict" errors
templates.env.cache = {}


# ---------------------------------------------------------------------------
# List page
# ---------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def list_experiments(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """List all A/B experiments with status, group counts, and duration."""
    experiments = (
        db.query(ExperimentRun)
        .order_by(ExperimentRun.created_at.desc())
        .all()
    )

    # Enrich with group and avatar counts
    enriched = []
    for exp in experiments:
        group_count = (
            db.query(func.count(TreatmentGroup.id))
            .filter(TreatmentGroup.experiment_id == exp.id)
            .scalar()
        )
        avatar_count = (
            db.query(func.count(AvatarAssignment.id))
            .filter(
                AvatarAssignment.experiment_id == exp.id,
                AvatarAssignment.is_excluded.is_(False),
            )
            .scalar()
        )
        enriched.append({
            "experiment": exp,
            "group_count": group_count,
            "avatar_count": avatar_count,
        })

    return templates.TemplateResponse(
        "admin_ab_tests.html",
        {"request": request, "experiments": enriched},
    )


# ---------------------------------------------------------------------------
# Create experiment
# ---------------------------------------------------------------------------


@router.get("/new", response_class=HTMLResponse)
async def new_experiment_form(
    request: Request,
    _user=Depends(require_owner),
):
    """Render the create experiment form."""
    return templates.TemplateResponse(
        "admin_ab_test_new.html",
        {"request": request},
    )


@router.post("")
async def create_experiment(
    request: Request,
    name: str = Form(...),
    hypothesis: str = Form(...),
    duration_weeks: int = Form(8),
    daily_volume: int = Form(3),
    risk_max: int = Form(40),
    generation_model: str = Form("gemini/gemini-2.5-flash"),
    db: Session = Depends(get_db),
    user=Depends(require_owner),
):
    """Create a new experiment with 3 default treatment groups."""
    try:
        groups = [
            {"name": "Old Reddit (textarea)", "posting_method": "old_reddit"},
            {"name": "Manual Email", "posting_method": "manual_email"},
            {"name": "New Reddit (debugger)", "posting_method": "new_reddit_debugger"},
        ]
        exp = experiment_manager.create_experiment(
            db=db,
            name=name,
            hypothesis=hypothesis,
            duration_weeks=duration_weeks,
            groups=groups,
            daily_volume=daily_volume,
            risk_max=risk_max,
            content_type="hobby",
            model=generation_model,
            created_by=user.id,
        )
        db.commit()
        return RedirectResponse(
            url=f"/admin/ab-tests/{exp.id}",
            status_code=303,
        )
    except ValueError as e:
        return templates.TemplateResponse(
            "admin_ab_test_new.html",
            {"request": request, "error": str(e)},
            status_code=400,
        )


# ---------------------------------------------------------------------------
# Detail page
# ---------------------------------------------------------------------------


@router.get("/{experiment_id}", response_class=HTMLResponse)
async def experiment_detail(
    request: Request,
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Full detail page: groups, assignments, metrics summary."""
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    groups = (
        db.query(TreatmentGroup)
        .filter(TreatmentGroup.experiment_id == experiment_id)
        .all()
    )

    # Assignments per group with avatar info
    assignments_by_group = {}
    for group in groups:
        assignments = (
            db.query(AvatarAssignment, Avatar)
            .join(Avatar, AvatarAssignment.avatar_id == Avatar.id)
            .filter(AvatarAssignment.group_id == group.id)
            .all()
        )
        assignments_by_group[group.id] = assignments

    # Latest report
    latest_report = (
        db.query(WeeklyReport)
        .filter(WeeklyReport.experiment_id == experiment_id)
        .order_by(WeeklyReport.week_number.desc())
        .first()
    )

    # Violations count
    violation_count = (
        db.query(func.count(ControlViolation.id))
        .filter(ControlViolation.experiment_id == experiment_id)
        .scalar()
    )

    # Available avatars for assignment (eligible, not already in this experiment)
    assigned_avatar_ids = (
        db.query(AvatarAssignment.avatar_id)
        .filter(AvatarAssignment.experiment_id == experiment_id)
        .subquery()
    )
    available_avatars = (
        db.query(Avatar)
        .filter(
            Avatar.is_active.is_(True),
            Avatar.is_frozen.is_(False),
            Avatar.id.notin_(assigned_avatar_ids),
        )
        .order_by(Avatar.reddit_username)
        .all()
    )

    return templates.TemplateResponse(
        "admin_ab_test_detail.html",
        {
            "request": request,
            "experiment": experiment,
            "groups": groups,
            "assignments_by_group": assignments_by_group,
            "latest_report": latest_report,
            "violation_count": violation_count,
            "available_avatars": available_avatars,
        },
    )


# ---------------------------------------------------------------------------
# Treatment Group Management
# ---------------------------------------------------------------------------


@router.post("/{experiment_id}/groups")
async def add_treatment_group(
    experiment_id: uuid.UUID,
    request: Request,
    name: str = Form(...),
    posting_method: str = Form(...),
    description: str = Form(""),
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Add a treatment group to an experiment (HTMX)."""
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise HTTPException(status_code=404, detail="Experiment not found")

    if experiment.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Can only add groups to experiments in draft status",
        )

    try:
        experiment_manager.add_treatment_group(
            db=db,
            experiment_id=experiment_id,
            name=name.strip(),
            posting_method=posting_method.strip(),
            description=description.strip() or None,
        )
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(
        url=f"/admin/ab-tests/{experiment_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# Avatar Assignment
# ---------------------------------------------------------------------------


@router.post("/{experiment_id}/assign")
async def assign_avatars(
    experiment_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Assign selected avatars to a treatment group (HTMX)."""
    form = await request.form()
    group_id = form.get("group_id")
    avatar_ids = form.getlist("avatar_ids")

    if not group_id or not avatar_ids:
        raise HTTPException(status_code=400, detail="group_id and avatar_ids required")

    results = []
    for avatar_id_str in avatar_ids:
        try:
            experiment_manager.assign_avatar(
                db=db,
                experiment_id=experiment_id,
                group_id=uuid.UUID(group_id),
                avatar_id=uuid.UUID(avatar_id_str),
            )
            results.append({"avatar_id": avatar_id_str, "status": "assigned"})
        except ValueError as e:
            results.append({"avatar_id": avatar_id_str, "status": "error", "error": str(e)})

    db.commit()
    return RedirectResponse(
        url=f"/admin/ab-tests/{experiment_id}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# State Transitions
# ---------------------------------------------------------------------------


@router.post("/{experiment_id}/start")
async def start_experiment(
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Transition experiment from draft → active."""
    try:
        experiment_manager.start_experiment(db, experiment_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/admin/ab-tests/{experiment_id}", status_code=303)


@router.post("/{experiment_id}/pause")
async def pause_experiment(
    experiment_id: uuid.UUID,
    reason: str = Form("Operator paused"),
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Pause an active experiment."""
    try:
        experiment_manager.pause_experiment(db, experiment_id, reason)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/admin/ab-tests/{experiment_id}", status_code=303)


@router.post("/{experiment_id}/resume")
async def resume_experiment(
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Resume a paused experiment."""
    try:
        experiment_manager.resume_experiment(db, experiment_id)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/admin/ab-tests/{experiment_id}", status_code=303)


@router.post("/{experiment_id}/conclude")
async def conclude_experiment(
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Conclude an active experiment and generate final report."""
    try:
        exp = experiment_manager.conclude_experiment(db, experiment_id)
        # Generate final summary
        final_summary = generate_final_report(db, experiment_id)
        exp.conclusion_summary = final_summary
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/admin/ab-tests/{experiment_id}", status_code=303)


@router.post("/{experiment_id}/abort")
async def abort_experiment(
    experiment_id: uuid.UUID,
    reason: str = Form("Operator aborted"),
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Abort an experiment."""
    try:
        experiment_manager.abort_experiment(db, experiment_id, reason)
        db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return RedirectResponse(url=f"/admin/ab-tests/{experiment_id}", status_code=303)


# ---------------------------------------------------------------------------
# Reports (HTMX partials)
# ---------------------------------------------------------------------------


@router.get("/{experiment_id}/report/{week_number}", response_class=HTMLResponse)
async def get_weekly_report(
    request: Request,
    experiment_id: uuid.UUID,
    week_number: int,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Get weekly report partial (HTMX lazy-load)."""
    report = (
        db.query(WeeklyReport)
        .filter(
            WeeklyReport.experiment_id == experiment_id,
            WeeklyReport.week_number == week_number,
        )
        .first()
    )

    return templates.TemplateResponse(
        "partials/ab_test_report.html",
        {"request": request, "report": report, "week_number": week_number},
    )


@router.get("/{experiment_id}/metrics", response_class=HTMLResponse)
async def get_metrics_dashboard(
    request: Request,
    experiment_id: uuid.UUID,
    db: Session = Depends(get_db),
    _user=Depends(require_owner),
):
    """Metrics dashboard partial with chart data (HTMX lazy-load)."""
    experiment = db.query(ExperimentRun).filter(
        ExperimentRun.id == experiment_id
    ).first()
    if not experiment:
        raise HTTPException(status_code=404)

    groups = (
        db.query(TreatmentGroup)
        .filter(TreatmentGroup.experiment_id == experiment_id)
        .all()
    )

    # Get all metric snapshots grouped by week and group
    snapshots = (
        db.query(MetricSnapshot)
        .filter(MetricSnapshot.experiment_id == experiment_id)
        .order_by(MetricSnapshot.week_number)
        .all()
    )

    # Build chart data: per group, per week averages for key metrics
    chart_data = _build_chart_data(snapshots, groups)

    # Get all reports
    reports = (
        db.query(WeeklyReport)
        .filter(WeeklyReport.experiment_id == experiment_id)
        .order_by(WeeklyReport.week_number)
        .all()
    )

    return templates.TemplateResponse(
        "partials/ab_test_metrics.html",
        {
            "request": request,
            "experiment": experiment,
            "groups": groups,
            "chart_data": chart_data,
            "reports": reports,
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_chart_data(
    snapshots: list[MetricSnapshot],
    groups: list[TreatmentGroup],
) -> dict:
    """Build chart-ready data structure for metrics dashboard."""
    group_map = {g.id: g.posting_method for g in groups}

    # Organize by group and week
    data: dict[str, dict[int, list]] = {}
    for g in groups:
        data[g.posting_method] = {}

    for snap in snapshots:
        method = group_map.get(snap.group_id)
        if not method:
            continue
        week = snap.week_number
        if week not in data[method]:
            data[method][week] = []
        data[method][week].append(snap)

    # Compute per-week averages
    chart = {
        "weeks": sorted(set(s.week_number for s in snapshots)) if snapshots else [],
        "removal_rate": {},
        "karma_velocity_4h": {},
        "shadowban_events": {},
    }

    for method in data:
        chart["removal_rate"][method] = []
        chart["karma_velocity_4h"][method] = []
        chart["shadowban_events"][method] = []

        for week in chart["weeks"]:
            week_snaps = data[method].get(week, [])
            if week_snaps:
                rr_values = [float(s.removal_rate) for s in week_snaps if s.removal_rate is not None]
                kv_values = [float(s.karma_velocity_4h) for s in week_snaps if s.karma_velocity_4h is not None]
                sb_values = [s.shadowban_events for s in week_snaps]

                chart["removal_rate"][method].append(
                    round(sum(rr_values) / len(rr_values), 4) if rr_values else None
                )
                chart["karma_velocity_4h"][method].append(
                    round(sum(kv_values) / len(kv_values), 2) if kv_values else None
                )
                chart["shadowban_events"][method].append(
                    sum(sb_values)
                )
            else:
                chart["removal_rate"][method].append(None)
                chart["karma_velocity_4h"][method].append(None)
                chart["shadowban_events"][method].append(None)

    return chart
