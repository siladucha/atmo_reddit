from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings
from app.routes import pages, api

app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None)


# Cache-Control middleware for static assets
class StaticCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/static/") or request.url.path.startswith("/mkt/static/"):
            response.headers["Cache-Control"] = "public, max-age=604800"
        return response


app.add_middleware(StaticCacheMiddleware)

# Mount static files (under /mkt/static to avoid collision with main app behind nginx)
app.mount("/mkt/static", StaticFiles(directory="app/static"), name="static")
# Also keep /static for backward compat in standalone mode
app.mount("/static", StaticFiles(directory="app/static"), name="static_compat")

# Register route modules
app.include_router(pages.router)
app.include_router(api.router)

# Templates for error pages
templates = Jinja2Templates(directory="app/templates")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "marketing"}


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse(
        request=request,
        name="marketing_404.html",
        status_code=404,
    )
