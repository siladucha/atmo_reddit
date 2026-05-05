import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings, get_config
from app.logging_config import setup_logging
from app.middleware.auth import AuthMiddleware
from app.middleware.errors import ErrorMiddleware
from app.routes import admin, auth, dashboard, review, pipeline, avatars, clients, pages, dry_run
from app.services.metrics_collector import (
    get_metrics_collector,
    install_metrics_logging_handler,
)

settings = get_settings()
app_env = get_config("app_env")
setup_logging(level="DEBUG" if app_env == "development" else "INFO")
logger = logging.getLogger(__name__)

# In-memory metrics collector + logging hook (captures PRAW rate-limit logs
# emitted in this FastAPI process). Multi-process aggregation happens in
# app.services.health_metrics via DB queries.
metrics_collector = get_metrics_collector(window_minutes=60)
install_metrics_logging_handler(metrics_collector)

app = FastAPI(
    title="Reddit Marketing SaaS",
    version="0.1.0",
    docs_url="/docs" if app_env == "development" else None,
)

# Middleware (order matters: error handler wraps auth which wraps routes)
app.add_middleware(ErrorMiddleware, debug=(app_env == "development"))
app.add_middleware(AuthMiddleware)

# Expose the metrics collector to route handlers via app.state
app.state.metrics_collector = metrics_collector

# Static files & templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# API Routes
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(clients.router, prefix="/clients-api", tags=["clients-api"])
app.include_router(avatars.router, prefix="/avatars-api", tags=["avatars-api"])
app.include_router(dashboard.router, prefix="/api/admin", tags=["admin"])
app.include_router(review.router, prefix="/review-api", tags=["review-api"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])

# UI Pages
app.include_router(admin.router, tags=["admin-panel"])
app.include_router(dry_run.router, tags=["dry-run"])
app.include_router(pages.router, tags=["pages"])


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}


@app.on_event("startup")
def on_startup():
    logger.info("Reddit SaaS started — env=%s", app_env)

    # Ensure all settings exist in DB and seed values from .env
    from app.database import SessionLocal
    from app.services.settings import init_defaults, seed_from_env
    db = SessionLocal()
    try:
        init_defaults(db)
        seed_from_env(db)
    except Exception as e:
        logger.warning("Failed to init settings: %s", e)
    finally:
        db.close()
