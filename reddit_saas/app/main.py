import logging

from fastapi import FastAPI, Request as FastAPIRequest
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings, get_config
from app.logging_config import setup_logging, get_logger
from app.middleware.auth import AuthMiddleware
from app.middleware.trial_signals import TrialSignalMiddleware
from app.version import __version__
from app.middleware.errors import ErrorMiddleware
from app.middleware.security import SecurityHeadersMiddleware, RateLimitMiddleware
from app.routes import admin, auth, dashboard, review, pipeline, avatars, avatar_analysis, avatar_pipeline, avatar_workflow, clients, pages, dry_run, export, decision_center, portal, portal_actions, portal_requests, onboarding, oauth, posting_dashboard, discovery, admin_geo, sse, avatar_onboard, admin_tasks, executor_tasks, trial_intelligence, admin_risk_profile, portal_risk_profile, daily_review, intelligence_report, admin_intelligence_report, demo, admin_ab_test
from app.routes.extension_api import router as extension_api_router
from app.routes.extension_events import router as extension_events_router
from app.routes import notifications as notifications_routes
from app.routes import manual as manual_routes
from app.services.metrics_collector import (
    get_metrics_collector,
    install_metrics_logging_handler,
)

settings = get_settings()
app_env = get_config("app_env")
setup_logging(level="DEBUG" if app_env == "development" else "INFO")
logger = get_logger(__name__)

# In-memory metrics collector + logging hook (captures PRAW rate-limit logs
# emitted in this FastAPI process). Multi-process aggregation happens in
# app.services.health_metrics via DB queries.
metrics_collector = get_metrics_collector(window_minutes=60)
install_metrics_logging_handler(metrics_collector)

app = FastAPI(
    title="RAMP",
    version=__version__,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Middleware (order matters: outermost wraps innermost)
# Request flow: SecurityHeaders → RateLimit → ErrorHandler → Auth → Routes
app.add_middleware(SecurityHeadersMiddleware)


# --- Custom HTTP exception handlers (friendly HTML pages) ---

ACCESS_DENIED_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Access Denied — RAMP</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body class="bg-[#0F172A] min-h-screen flex items-center justify-center font-['Inter']">
    <div class="bg-[#1E293B] border border-slate-700 p-10 rounded-xl shadow-2xl max-w-md text-center">
        <div class="text-5xl mb-4">🚫</div>
        <h1 class="text-2xl font-semibold text-white mb-3">Access Denied</h1>
        <p class="text-gray-400 mb-6">You don't have permission to view this page.</p>
        <div class="flex gap-3 justify-center">
            <a href="javascript:history.back()" class="px-4 py-2 bg-slate-700 text-gray-300 rounded-lg hover:bg-slate-600 transition-colors text-sm">← Go Back</a>
            <a href="/admin/" class="px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 transition-colors text-sm">Dashboard</a>
        </div>
    </div>
</body>
</html>
"""


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: FastAPIRequest, exc: HTTPException):
    """Render friendly HTML pages for 403 and 303 instead of raw JSON."""
    # 303 redirect (unauthenticated / inactive user)
    if exc.status_code == 303:
        location = (exc.headers or {}).get("Location", "/login")
        return RedirectResponse(url=location, status_code=303)

    # 403 Access Denied — show styled page for browser requests
    if exc.status_code == 403:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return HTMLResponse(content=ACCESS_DENIED_HTML, status_code=403)
        # API requests still get JSON
        from fastapi.responses import JSONResponse
        return JSONResponse(content={"detail": exc.detail}, status_code=403)

    # All other HTTP exceptions — default FastAPI behavior
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={"detail": exc.detail},
        status_code=exc.status_code,
        headers=exc.headers,
    )


# --- End exception handlers ---
app.add_middleware(
    RateLimitMiddleware,
    auth_limit=5,
    auth_window_seconds=900,
    enabled=(app_env == "production"),
)
app.add_middleware(ErrorMiddleware, debug=(app_env != "production"))
app.add_middleware(AuthMiddleware)
app.add_middleware(TrialSignalMiddleware)

# Expose the metrics collector to route handlers via app.state
app.state.metrics_collector = metrics_collector

# Static files & templates
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# API Routes
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(oauth.router, tags=["oauth"])  # prefix="/api/oauth" defined in router
app.include_router(clients.router, prefix="/clients-api", tags=["clients-api"])
app.include_router(avatars.router, prefix="/avatars-api", tags=["avatars-api"])
app.include_router(avatar_analysis.router, tags=["avatar-analysis"])
app.include_router(dashboard.router, prefix="/api/admin", tags=["admin"])
app.include_router(review.router, prefix="/review-api", tags=["review-api"])
app.include_router(pipeline.router, prefix="/pipeline", tags=["pipeline"])

# UI Pages
app.include_router(admin.router, tags=["admin-panel"])
app.include_router(decision_center.router, tags=["decision-center"])
app.include_router(avatar_pipeline.router, tags=["avatar-pipeline"])
app.include_router(avatar_workflow.router, tags=["avatar-workflow"])
app.include_router(dry_run.router, tags=["dry-run"])
app.include_router(portal.router, tags=["client-portal"])
app.include_router(manual_routes.router)
app.include_router(portal_actions.router, tags=["client-portal-actions"])
app.include_router(portal_requests.router, tags=["client-portal-requests"])
app.include_router(sse.router, tags=["sse"])
app.include_router(notifications_routes.router, tags=["notifications"])
app.include_router(onboarding.router, tags=["onboarding"])
app.include_router(avatar_onboard.router, tags=["avatar-onboard"])
app.include_router(pages.router, tags=["pages"])
app.include_router(posting_dashboard.router, tags=["posting-dashboard"])
app.include_router(discovery.router, tags=["discovery"])
app.include_router(export.router, tags=["export"])
app.include_router(admin_geo.router, tags=["admin-geo"])
app.include_router(admin_tasks.router, tags=["admin-tasks"])
app.include_router(executor_tasks.router, tags=["executor-tasks"])
app.include_router(extension_api_router, tags=["extension-api"])
app.include_router(extension_events_router, tags=["extension-events"])
app.include_router(trial_intelligence.router, tags=["trial-intelligence"])
app.include_router(admin_risk_profile.router, tags=["admin-risk-profile"])
app.include_router(portal_risk_profile.router, tags=["portal-risk-profile"])
app.include_router(daily_review.router, tags=["daily-review"])
app.include_router(intelligence_report.router, tags=["intelligence-report"])
app.include_router(admin_intelligence_report.router, tags=["admin-intelligence-report"])
app.include_router(demo.router, tags=["demo"])
app.include_router(admin_ab_test.router, tags=["admin-ab-tests"])


@app.get("/health")
def health_check():
    """Health check endpoint — verifies DB, Redis, and pipeline liveness.

    Returns 200 if all services reachable AND pipeline alive.
    Returns 503 if DB/Redis down (infrastructure dead).
    Returns 200 with pipeline_alive=false if workers dead but infra OK
    (allows external monitors to alert on pipeline death separately).

    Key fields for external monitoring:
    - status: "ok" | "degraded" | "pipeline_dead"
    - pipeline_alive: true/false (are Celery workers producing output?)
    - worker_alive: true/false (last heartbeat < 5 min?)
    - scrape_stale_hours: hours since last successful scrape
    """
    checks = {"version": __version__, "env": app_env, "posting_disabled": settings.posting_disabled}
    all_ok = True

    # Check database
    try:
        from app.database import SessionLocal
        from sqlalchemy import text
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {type(e).__name__}"
        all_ok = False
        db = None

    # Check Redis
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url, socket_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {type(e).__name__}"
        all_ok = False
        r = None

    # Check worker heartbeat (Redis key written by system_heartbeat task)
    worker_alive = False
    try:
        if r is not None:
            last_heartbeat_str = r.get("ramp:heartbeat:last_at")
            if last_heartbeat_str:
                from datetime import datetime, timezone
                last_hb = datetime.fromisoformat(last_heartbeat_str.decode() if isinstance(last_heartbeat_str, bytes) else last_heartbeat_str)
                hb_age_sec = (datetime.now(timezone.utc) - last_hb).total_seconds()
                worker_alive = hb_age_sec < 300  # 5 min threshold
                checks["worker_heartbeat_age_sec"] = int(hb_age_sec)
            else:
                checks["worker_heartbeat_age_sec"] = -1  # no heartbeat ever
    except Exception:
        checks["worker_heartbeat_age_sec"] = -1
    checks["worker_alive"] = worker_alive

    # Check pipeline liveness: when was the last successful scrape?
    pipeline_alive = False
    scrape_stale_hours = -1
    try:
        if db is not None:
            from datetime import datetime, timezone
            from sqlalchemy import func as sa_func
            from app.models.subreddit import Subreddit
            last_scrape = db.query(sa_func.max(Subreddit.last_scraped_at)).scalar()
            if last_scrape:
                scrape_age = (datetime.now(timezone.utc) - last_scrape).total_seconds() / 3600
                scrape_stale_hours = round(scrape_age, 1)
                pipeline_alive = scrape_age < 24  # pipeline alive if scraped in last 24h
            else:
                scrape_stale_hours = 9999
    except Exception:
        pass
    finally:
        if db is not None:
            db.close()

    checks["pipeline_alive"] = pipeline_alive
    checks["scrape_stale_hours"] = scrape_stale_hours

    # Determine overall status
    if not all_ok:
        checks["status"] = "degraded"
        from fastapi.responses import JSONResponse
        return JSONResponse(content=checks, status_code=503)
    elif not pipeline_alive or not worker_alive:
        checks["status"] = "pipeline_dead"
    else:
        checks["status"] = "ok"

    return checks


@app.on_event("startup")
def on_startup():
    from app.version import __version__
    logger.info("RAMP v%s started — env=%s", __version__, app_env)

    # Log posting override status
    if settings.posting_disabled:
        logger.warning("⚠️  POSTING_DISABLED=true — automated posting blocked at env level")

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
