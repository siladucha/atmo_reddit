"""UX Manual Overlay — content serving route."""

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.manual.registry import get_manual_content

router = APIRouter(prefix="/api/manual", tags=["manual"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
async def manual_content(
    request: Request,
    path: str = Query("", description="Current page route path"),
) -> HTMLResponse:
    """Serve manual overlay content for the given page path."""
    user_role = getattr(request.state, "user_role", "b2c_user") or "b2c_user"
    content = get_manual_content(path, user_role)
    return templates.TemplateResponse(
        name="partials/manual_content.html",
        context={"request": request, **content},
        request=request,
    )
