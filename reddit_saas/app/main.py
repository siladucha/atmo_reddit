import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.logging_config import setup_logging
from app.middleware.auth import AuthMiddleware
from app.middleware.errors import ErrorMiddleware
from app.routes import auth, dashboard, review, pipeline, avatars, clients, pages

settings = get_settings()
setup_logging(level="DEBUG" if settings.app_env == "development" else "INFO")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Reddit Marketing SaaS",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "development" else None,
)

# Middleware (order matters: error handler wraps auth which wraps routes)
app.add_middleware(ErrorMiddleware, debug=(settings.app_env == "development"))
app.add_middleware(AuthMiddleware)

# Static files & templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# API Routes
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(clients.router, prefix="/clients-api", tags=["clients-api"])
app.include_router(avatars.router, prefix="/avatars-api", tags=["avatars-api"])
app.include_router(dashboard.router, prefix="/admin", tags=["admin"])
app.include_router(review.router, prefix="/review-api", tags=["review-api"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])

# UI Pages
app.include_router(pages.router, tags=["pages"])


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.on_event("startup")
def on_startup():
    logger.info("Reddit SaaS started — env=%s", settings.app_env)
