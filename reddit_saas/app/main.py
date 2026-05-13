import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings, get_config
from app.logging_config import setup_logging
from app.middleware.auth import AuthMiddleware
from app.middleware.errors import ErrorMiddleware
from app.middleware.security import SecurityHeadersMiddleware, RateLimitMiddleware
from app.routes import admin, auth, dashboard, review, pipeline, avatars, avatar_analysis, avatar_pipeline, clients, pages, dry_run, export
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
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Middleware (order matters: outermost wraps innermost)
# Request flow: SecurityHeaders → RateLimit → ErrorHandler → Auth → Routes
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    auth_limit=5,
    auth_window_seconds=900,
    enabled=(app_env == "production"),
)
app.add_middleware(ErrorMiddleware, debug=(app_env != "production"))
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
app.include_router(avatar_analysis.router, tags=["avatar-analysis"])
app.include_router(dashboard.router, prefix="/api/admin", tags=["admin"])
app.include_router(review.router, prefix="/review-api", tags=["review-api"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])

# UI Pages
app.include_router(admin.router, tags=["admin-panel"])
app.include_router(avatar_pipeline.router, tags=["avatar-pipeline"])
app.include_router(dry_run.router, tags=["dry-run"])
app.include_router(pages.router, tags=["pages"])
app.include_router(export.router, tags=["export"])


@app.get("/health")
def health_check():
    """Health check endpoint — verifies DB and Redis connectivity.

    Returns 200 if all services are reachable, 503 otherwise.
    Used by load balancers and container orchestrators.
    """
    checks = {"version": "0.1.0"}
    all_ok = True

    # Check database
    try:
        from app.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        all_ok = False

    # Check Redis
    try:
        import redis as redis_lib
        from app.config import get_settings
        r = redis_lib.from_url(get_settings().redis_url, socket_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"
        all_ok = False

    checks["status"] = "ok" if all_ok else "degraded"

    if not all_ok:
        from fastapi.responses import JSONResponse
        return JSONResponse(content=checks, status_code=503)

    return checks


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

    # Refuse to run with the default JWT secret — anyone with the codebase
    # could forge tokens. In dev, set SECRET_KEY in .env or system_settings.
    secret = get_config("secret_key") or ""
    if secret.strip() in {"", "change-me"}:
        raise RuntimeError(
            "SECRET_KEY is unset or still the default 'change-me'. "
            "Set a strong value in .env or system_settings before starting."
        )

    # Validate SECRET_KEY strength in production
    if app_env == "production" and len(secret) < 32:
        raise RuntimeError(
            "SECRET_KEY is too short for production (min 32 chars). "
            "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""
        )

    logger.info("Startup validation passed — all critical settings OK")
