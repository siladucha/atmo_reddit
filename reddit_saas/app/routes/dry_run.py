"""Dry-run admin routes.

Routes mounted under /admin/dry-run/* let the operator walk a thread through
the LLM pipeline manually: the system renders each prompt, the operator runs
it externally, the operator pastes the response back.

Toggle is gated by the system_setting `dry_run_enabled`. When false, all
routes here return 404 and the nav item is hidden in admin_base.html.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_superuser
from app.models.client import Client
from app.models.thread import RedditThread
from app.models.user import User
from app.services import dry_run as dry_run_service
from app.services.scoring import apply_scoring_result, build_scoring_messages
from app.services.settings import get_setting, set_setting
from app.services.transparency import record_activity_event

router = APIRouter(prefix="/admin/dry-run")
templates = Jinja2Templates(directory="app/templates")
templates.env.globals["dry_run_enabled"] = dry_run_service.is_dry_run_enabled_global
from app.version import __version__ as app_version
from app.config import get_settings as _get_settings
templates.env.globals["app_version"] = app_version
templates.env.globals["posting_disabled"] = lambda: _get_settings().posting_disabled


def _require_dry_run_on(db: Session) -> None:
    """Raise 404 if dry-run mode is currently off (UI is hidden)."""
    if not dry_run_service.is_dry_run_enabled(db):
        raise HTTPException(status_code=404, detail="Dry-run mode is disabled")


# ---------------------------------------------------------------------------
# Toggle settings page
# ---------------------------------------------------------------------------


@router.get("/settings", response_class=HTMLResponse)
def dry_run_settings_get(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    enabled = dry_run_service.is_dry_run_enabled(db)
    return templates.TemplateResponse(
        name="admin_dry_run_settings.html",
        context={
            "request": request,
            "active_nav": "dry-run",
            "enabled": enabled,
            "saved": False,
        },
        request=request,
    )


@router.post("/settings", response_class=HTMLResponse)
def dry_run_settings_post(
    request: Request,
    enabled: str = Form(""),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    new_value = "true" if enabled == "on" else "false"
    set_setting(db, "dry_run_enabled", new_value)
    record_activity_event(
        db,
        event_type="system",
        message=f"Dry-run mode set to {new_value}",
        client_id=None,
        metadata={"setting": "dry_run_enabled", "value": new_value, "operator_user_id": str(current_user.id)},
    )
    return templates.TemplateResponse(
        name="admin_dry_run_settings.html",
        context={
            "request": request,
            "active_nav": "dry-run",
            "enabled": new_value == "true",
            "saved": True,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Hub: per-client backlog
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def dry_run_index(
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    """Pick a client to walk through dry-run."""
    _require_dry_run_on(db)
    clients = (
        db.query(Client)
        .filter(Client.is_active.is_(True))
        .order_by(Client.client_name)
        .all()
    )
    return templates.TemplateResponse(
        name="admin_dry_run_index.html",
        context={
            "request": request,
            "active_nav": "dry-run",
            "clients": clients,
        },
        request=request,
    )


@router.get("/{client_id}", response_class=HTMLResponse)
def dry_run_hub(
    client_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    _require_dry_run_on(db)
    client = db.query(Client).filter(Client.id == client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    counts = dry_run_service.get_backlog_counts(db, client.id)
    unscored = dry_run_service.get_unscored_threads(db, client.id, limit=20)

    return templates.TemplateResponse(
        name="admin_dry_run_hub.html",
        context={
            "request": request,
            "active_nav": "dry-run",
            "client": client,
            "counts": counts,
            "unscored_threads": unscored,
        },
        request=request,
    )


# ---------------------------------------------------------------------------
# Scoring stage preview + paste-back
# ---------------------------------------------------------------------------


@router.get("/score/{thread_id}", response_class=HTMLResponse)
def dry_run_score_get(
    thread_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    _require_dry_run_on(db)
    thread = db.query(RedditThread).filter(RedditThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    client = db.query(Client).filter(Client.id == thread.client_id).first()
    if not client:
        raise HTTPException(status_code=404, detail="Client not found")

    messages = build_scoring_messages(thread, client)
    system_prompt = messages[0]["content"]
    user_prompt = messages[1]["content"]
    combined = (
        f"# SYSTEM\n\n{system_prompt}\n\n---\n\n# USER\n\n{user_prompt}"
    )

    model_name = get_setting(db, "llm_scoring_model") or "anthropic/claude-3-5-haiku-20241022"

    return templates.TemplateResponse(
        name="admin_dry_run_score.html",
        context={
            "request": request,
            "active_nav": "dry-run",
            "client": client,
            "thread": thread,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "combined_prompt": combined,
            "model_name": model_name,
            "error": None,
            "raw_response": "",
        },
        request=request,
    )


@router.post("/score/{thread_id}", response_class=HTMLResponse)
def dry_run_score_post(
    thread_id: uuid.UUID,
    request: Request,
    raw_response: str = Form(...),
    current_user: User = Depends(require_superuser),
    db: Session = Depends(get_db),
):
    _require_dry_run_on(db)
    thread = db.query(RedditThread).filter(RedditThread.id == thread_id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    client = db.query(Client).filter(Client.id == thread.client_id).first()

    error = None
    data: dict | None = None
    try:
        data = _parse_json_response(raw_response)
    except ValueError as e:
        error = str(e)

    if error or data is None:
        # Re-render the page with the error and the operator's text preserved.
        messages = build_scoring_messages(thread, client)
        return templates.TemplateResponse(
            name="admin_dry_run_score.html",
            context={
                "request": request,
                "active_nav": "dry-run",
                "client": client,
                "thread": thread,
                "system_prompt": messages[0]["content"],
                "user_prompt": messages[1]["content"],
                "combined_prompt": (
                    f"# SYSTEM\n\n{messages[0]['content']}\n\n---\n\n# USER\n\n{messages[1]['content']}"
                ),
                "model_name": get_setting(db, "llm_scoring_model"),
                "error": error,
                "raw_response": raw_response,
            },
            request=request,
        )

    apply_scoring_result(db, thread, data)
    record_activity_event(
        db,
        event_type="score",
        message=f"Scored thread '{thread.post_title[:60]}' (dry-run) → {thread.tag}",
        client_id=thread.client_id,
        metadata={
            "mode": "dry_run",
            "thread_id": str(thread.id),
            "tag": thread.tag,
            "composite": thread.composite,
            "operator_user_id": str(current_user.id),
            "cost_usd": 0,
        },
    )

    # Try to advance to the next unscored thread for the same client.
    unscored = dry_run_service.get_unscored_threads(db, thread.client_id, limit=1)
    if unscored:
        return RedirectResponse(url=f"/admin/dry-run/score/{unscored[0].id}", status_code=303)
    return RedirectResponse(url=f"/admin/dry-run/{thread.client_id}", status_code=303)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict:
    """Parse a pasted LLM JSON response, tolerating ``` fences and stray text.

    Raises ValueError with a helpful message on failure.
    """
    if not text or not text.strip():
        raise ValueError("Response is empty")

    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
    elif cleaned.startswith("```"):
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Try to find the first { ... } block in the text.
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Could not parse JSON: {e.msg} (line {e.lineno}, col {e.colno})") from e
