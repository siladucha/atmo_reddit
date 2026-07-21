"""Client Portal — My Requests page.

Shows all ActionRequests for the current client with status, timestamps,
and rejection reasons. Uses existing RBAC + permission context.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from app.templating import Jinja2Templates
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.permissions import (
    get_current_user,
    verify_client_access_from_path,
)
from app.models.action_request import ActionRequest
from app.models.user import User
from app.routes.portal import _portal_render

router = APIRouter(
    dependencies=[Depends(verify_client_access_from_path)],
    tags=["client-portal"],
)


# Human-readable labels for action types
ACTION_TYPE_LABELS: dict[str, str] = {
    "add_subreddit": "Add Subreddit",
    "remove_subreddit": "Remove Subreddit",
    "request_avatar_freeze": "Freeze Avatar",
    "request_avatar_unfreeze": "Unfreeze Avatar",
    "change_brand_guardrails": "Change Brand Guardrails",
    "add_keyword": "Add Keyword",
    "remove_keyword": "Remove Keyword",
    "trigger_pipeline": "Run Pipeline",
    "trigger_epg_rebuild": "Rebuild EPG",
    "trigger_strategy": "Generate Strategy",
    "regenerate_draft": "Regenerate Draft",
}


@router.get("/clients/{client_id}/requests")
def portal_requests(
    request: Request,
    client_id: UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """My Requests page — shows all ActionRequests for this client."""
    requests_list = (
        db.query(ActionRequest)
        .filter(ActionRequest.client_id == client_id)
        .order_by(desc(ActionRequest.created_at))
        .limit(100)
        .all()
    )

    # Enrich with human-readable labels
    enriched_requests = []
    for ar in requests_list:
        enriched_requests.append({
            "id": ar.id,
            "action_type": ar.action_type,
            "action_label": ACTION_TYPE_LABELS.get(ar.action_type, ar.action_type.replace("_", " ").title()),
            "status": ar.status,
            "created_at": ar.created_at,
            "resolved_at": ar.resolved_at,
            "rejection_reason": ar.rejection_reason,
            "payload": ar.payload,
        })

    return _portal_render(
        request=request,
        template="client/requests.html",
        client_id=client_id,
        db=db,
        active_page="requests",
        extra_context={
            "requests_list": enriched_requests,
        },
    )
