"""System settings service — read/write settings from DB."""

import logging
import uuid

from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.services import audit as audit_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default settings registry — every key has value, secret flag, description,
# and group assignment.  Groups: database, redis, auth, reddit_api, llm, app,
# budget.
# ---------------------------------------------------------------------------
DEFAULTS: dict[str, dict] = {
    # Redis
    "redis_url": {
        "value": "redis://localhost:6379/0",
        "secret": False,
        "desc": "Redis connection URL (used by Celery and caching)",
        "group": "redis",
    },
    # Auth
    "secret_key": {
        "value": "change-me",
        "secret": True,
        "desc": "JWT signing secret key",
        "group": "auth",
    },
    "access_token_expire_minutes": {
        "value": "1440",
        "secret": False,
        "desc": "Access token TTL in minutes",
        "group": "auth",
    },
    "admin_email": {
        "value": "max@admin.com",
        "secret": False,
        "desc": "Default admin email address",
        "group": "auth",
    },
    "admin_password": {
        "value": "",
        "secret": True,
        "desc": "Default admin password",
        "group": "auth",
    },
    "admin_name": {
        "value": "Admin",
        "secret": False,
        "desc": "Default admin display name",
        "group": "auth",
    },
    # Reddit API
    "reddit_client_id": {
        "value": "",
        "secret": False,
        "desc": "Reddit API Client ID (from reddit.com/prefs/apps)",
        "group": "reddit_api",
    },
    "reddit_client_secret": {
        "value": "",
        "secret": True,
        "desc": "Reddit API Client Secret",
        "group": "reddit_api",
    },
    "reddit_user_agent": {
        "value": "reddit-saas:v0.1.0",
        "secret": False,
        "desc": "Reddit API User Agent string",
        "group": "reddit_api",
    },
    # LLM
    "llm_api_key": {
        "value": "",
        "secret": True,
        "desc": "LLM API key (Anthropic, OpenRouter, or AWS Bedrock)",
        "group": "llm",
    },
    "gemini_api_key": {
        "value": "",
        "secret": True,
        "desc": "Google Gemini API key (for scoring model)",
        "group": "llm",
    },
    "llm_provider": {
        "value": "anthropic",
        "secret": False,
        "desc": "LLM provider: anthropic, openrouter, bedrock",
        "group": "llm",
    },
    "llm_scoring_model": {
        "value": "gemini/gemini-2.0-flash",
        "secret": False,
        "desc": "Model for scoring (cheap, fast)",
        "group": "llm",
    },
    "llm_generation_model": {
        "value": "anthropic/claude-sonnet-4-20250514",
        "secret": False,
        "desc": "Model for comment generation (quality)",
        "group": "llm",
    },
    # App
    "app_env": {
        "value": "development",
        "secret": False,
        "desc": "Environment: development or production",
        "group": "app",
    },
    "app_host": {
        "value": "0.0.0.0",
        "secret": False,
        "desc": "Server bind host",
        "group": "app",
    },
    "app_port": {
        "value": "8000",
        "secret": False,
        "desc": "Server bind port",
        "group": "app",
    },
    "alert_email": {
        "value": "",
        "secret": False,
        "desc": "Email for system alerts (optional)",
        "group": "app",
    },
    "dry_run_enabled": {
        "value": "false",
        "secret": False,
        "desc": "When true, every LLM stage renders the prompt for manual paste-back instead of calling the API",
        "group": "app",
    },
    # Scraping Queue
    "scrape_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Master on/off toggle for scrape queue",
        "group": "scraping",
    },
    "scrape_tick_interval_seconds": {
        "value": "60",
        "secret": False,
        "desc": "Queue tick interval in seconds (30–300)",
        "group": "scraping",
    },
    "scrape_freshness_window_hours": {
        "value": "12",
        "secret": False,
        "desc": "Freshness window in hours (1–168)",
        "group": "scraping",
    },
    "scrape_rate_limit_rpm": {
        "value": "30",
        "secret": False,
        "desc": "Max Reddit API requests per minute (1–60)",
        "group": "scraping",
    },
    # Scheduler
    "pipeline_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Master kill switch — disables all AI pipeline tasks (score, generate)",
        "group": "scheduler",
    },
    "generation_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Kill switch for comment generation only (score still runs)",
        "group": "scheduler",
    },
    "schedule_ai_pipeline_hours": {
        "value": "8,14",
        "secret": False,
        "desc": "Hours (UTC) when AI pipeline runs (scoring + generation). Comma-separated.",
        "group": "scheduler",
    },
    "schedule_hobby_pipeline_hour": {
        "value": "10",
        "secret": False,
        "desc": "Hour (UTC) when hobby pipeline runs daily",
        "group": "scheduler",
    },
    "schedule_avatar_health_hours": {
        "value": "0,12",
        "secret": False,
        "desc": "Hours (UTC) for avatar health checks. Comma-separated.",
        "group": "scheduler",
    },
    "schedule_phase_evaluation_hour": {
        "value": "6",
        "secret": False,
        "desc": "Hour (UTC) for daily avatar phase evaluation",
        "group": "scheduler",
    },
    "schedule_karma_tracking_hours": {
        "value": "0,4,8,12,16,20",
        "secret": False,
        "desc": "Hours (UTC) for karma tracking. Comma-separated (every 4h default).",
        "group": "scheduler",
    },
    # Budget / Billing
    "monthly_budget_usd": {
        "value": "100",
        "secret": False,
        "desc": "Monthly AI budget limit in USD (0 = unlimited)",
        "group": "budget",
    },
    "aws_credits_remaining": {
        "value": "7000",
        "secret": False,
        "desc": "AWS credits remaining (manual entry)",
        "group": "budget",
    },
}

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
_cache: dict[str, str] = {}
_cache_loaded: bool = False


def invalidate_cache(key: str | None = None) -> None:
    """Drop one key or the entire cache."""
    global _cache_loaded
    if key is not None:
        _cache.pop(key, None)
    else:
        _cache.clear()
        _cache_loaded = False


def reload_cache(db: Session) -> None:
    """Clear the cache and reload all settings from the database."""
    global _cache_loaded
    _cache.clear()
    _cache_loaded = False
    rows = db.query(SystemSetting).all()
    for row in rows:
        _cache[row.key] = row.value
    _cache_loaded = True


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------

def get_setting(db: Session, key: str) -> str:
    """Get a setting value.  Checks cache first, then DB, then defaults."""
    if key in _cache:
        return _cache[key]

    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        _cache[key] = row.value
        return row.value

    # Return default if exists
    if key in DEFAULTS:
        default_val = DEFAULTS[key]["value"]
        _cache[key] = default_val
        return default_val

    return ""


def set_setting(
    db: Session,
    key: str,
    value: str,
    user_id: uuid.UUID | None = None,
) -> None:
    """Set a setting value.  Creates if not exists.

    Writes an audit log entry and invalidates the cache for the key.
    """
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        row.value = value
    else:
        is_secret = DEFAULTS.get(key, {}).get("secret", False)
        desc = DEFAULTS.get(key, {}).get("desc", "")
        group = DEFAULTS.get(key, {}).get("group", "app")
        row = SystemSetting(
            key=key,
            value=value,
            is_secret=is_secret,
            description=desc,
            group=group,
        )
        db.add(row)
    db.commit()

    # Invalidate cache for this key
    invalidate_cache(key)

    # Audit log
    if user_id is not None:
        is_secret = DEFAULTS.get(key, {}).get("secret", False)
        display_value = "[REDACTED]" if is_secret else value
        audit_service.log_action(
            db=db,
            user_id=user_id,
            action="update",
            entity_type="system_setting",
            details={"key": key, "value": display_value},
        )


def get_all_settings(db: Session) -> list[dict]:
    """Get all settings with their current values."""
    existing = {s.key: s for s in db.query(SystemSetting).all()}

    result = []
    for key, meta in DEFAULTS.items():
        row = existing.get(key)
        result.append({
            "key": key,
            "value": row.value if row else meta["value"],
            "is_secret": meta["secret"],
            "description": meta["desc"],
            "group": meta.get("group", "app"),
            "is_set": bool(row and row.value),
            "updated_at": row.updated_at if row else None,
        })

    return result


def init_defaults(db: Session) -> None:
    """Initialize default settings in DB if they don't exist.

    For new keys: creates the row with defaults from the registry.
    For existing keys: updates ``group``, ``is_secret``, and ``description``
    to match the registry (fixes rows created before the group column existed).
    Values are never overwritten — only metadata is synced.
    """
    for key, meta in DEFAULTS.items():
        existing = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if not existing:
            db.add(SystemSetting(
                key=key,
                value=meta["value"],
                is_secret=meta["secret"],
                description=meta["desc"],
                group=meta.get("group", "app"),
            ))
        else:
            # Sync metadata (group, is_secret, description) without touching value
            expected_group = meta.get("group", "app")
            if existing.group != expected_group:
                existing.group = expected_group
            if existing.is_secret != meta["secret"]:
                existing.is_secret = meta["secret"]
            if existing.description != meta["desc"]:
                existing.description = meta["desc"]
    db.commit()


def seed_from_env(db: Session) -> None:
    """One-time migration: seed empty DB settings from environment variables.

    Only writes a value if the DB row is empty (value == "" or value == default)
    and the corresponding env var is set.  This bridges the gap between the old
    .env-only config and the new DB-first approach.
    """
    import os

    # Map DB setting keys to their .env variable names
    _ENV_MAP: dict[str, str] = {
        "redis_url": "REDIS_URL",
        "secret_key": "SECRET_KEY",
        "access_token_expire_minutes": "ACCESS_TOKEN_EXPIRE_MINUTES",
        "admin_email": "ADMIN_EMAIL",
        "admin_password": "ADMIN_PASSWORD",
        "admin_name": "ADMIN_NAME",
        "reddit_client_id": "REDDIT_CLIENT_ID",
        "reddit_client_secret": "REDDIT_CLIENT_SECRET",
        "reddit_user_agent": "REDDIT_USER_AGENT",
        "llm_api_key": "LITELLM_API_KEY",
        "gemini_api_key": "GEMINI_API_KEY",
        "llm_provider": "LITELLM_PROVIDER",
        "llm_scoring_model": "LITELLM_SCORING_MODEL",
        "llm_generation_model": "LITELLM_GENERATION_MODEL",
        "app_env": "APP_ENV",
        "app_host": "APP_HOST",
        "app_port": "APP_PORT",
    }

    # Load .env file manually if vars aren't already in os.environ
    try:
        from dotenv import dotenv_values
        env_values = dotenv_values(".env")
    except ImportError:
        env_values = {}

    changed = False
    for db_key, env_var in _ENV_MAP.items():
        env_val = os.environ.get(env_var) or env_values.get(env_var)
        if not env_val:
            continue

        row = db.query(SystemSetting).filter(SystemSetting.key == db_key).first()
        if row and (not row.value or row.value == DEFAULTS.get(db_key, {}).get("value", "")):
            row.value = env_val
            changed = True

    if changed:
        db.commit()
        invalidate_cache()


# ---------------------------------------------------------------------------
# Bulk save
# ---------------------------------------------------------------------------

def bulk_save_settings(
    db: Session,
    updates: dict[str, str],
    user_id: uuid.UUID | None = None,
) -> None:
    """Persist multiple settings at once, audit-log each, and invalidate cache."""
    for key, value in updates.items():
        row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if row:
            row.value = value
        else:
            is_secret = DEFAULTS.get(key, {}).get("secret", False)
            desc = DEFAULTS.get(key, {}).get("desc", "")
            group = DEFAULTS.get(key, {}).get("group", "app")
            row = SystemSetting(
                key=key,
                value=value,
                is_secret=is_secret,
                description=desc,
                group=group,
            )
            db.add(row)
    db.commit()

    # Invalidate cache and audit-log each change
    for key, value in updates.items():
        invalidate_cache(key)
        if user_id is not None:
            is_secret = DEFAULTS.get(key, {}).get("secret", False)
            display_value = "[REDACTED]" if is_secret else value
            audit_service.log_action(
                db=db,
                user_id=user_id,
                action="update",
                entity_type="system_setting",
                details={"key": key, "value": display_value},
            )


# ---------------------------------------------------------------------------
# Connection tests
# ---------------------------------------------------------------------------

def test_reddit_connection(db: Session) -> dict:
    """Test Reddit API connection using saved credentials.

    Returns ``{"success": bool, "message": str}``.
    """
    client_id = get_setting(db, "reddit_client_id")
    client_secret = get_setting(db, "reddit_client_secret")
    user_agent = get_setting(db, "reddit_user_agent") or "reddit-saas:v0.1.0"

    if not client_id or not client_secret:
        return {"success": False, "message": "Reddit API credentials not configured"}

    try:
        import praw
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
        # Minimal call to verify credentials
        list(reddit.subreddit("test").hot(limit=1))
        return {"success": True, "message": "Connected"}
    except Exception as e:
        msg = str(e)[:100]
        return {"success": False, "message": msg}


def test_llm_connection(db: Session) -> dict:
    """Test LLM API connection using saved key and model.

    Returns ``{"success": bool, "message": str}``.
    """
    model = get_setting(db, "llm_scoring_model")

    if not model:
        return {"success": False, "message": "LLM model not configured"}

    # Resolve the correct API key based on model provider
    if model.startswith("gemini/"):
        api_key = get_setting(db, "gemini_api_key")
        if not api_key:
            api_key = get_setting(db, "llm_api_key")
        key_name = "gemini_api_key"
    else:
        api_key = get_setting(db, "llm_api_key")
        key_name = "llm_api_key"

    if not api_key:
        return {"success": False, "message": f"{key_name} not configured"}

    try:
        import litellm
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            api_key=api_key,
            max_tokens=5,
        )
        return {"success": True, "message": "Connected"}
    except Exception as e:
        msg = str(e)[:100]
        return {"success": False, "message": msg}


# ---------------------------------------------------------------------------
# Legacy helper (kept for backward compatibility)
# ---------------------------------------------------------------------------

def check_connections(db: Session) -> dict:
    """Check which external services are configured."""
    reddit_id = get_setting(db, "reddit_client_id")
    reddit_secret = get_setting(db, "reddit_client_secret")
    llm_key = get_setting(db, "llm_api_key")

    reddit_ok = bool(reddit_id and reddit_secret)
    llm_ok = bool(llm_key)

    reddit_status = "not_configured"
    if reddit_ok:
        try:
            import praw
            reddit = praw.Reddit(
                client_id=reddit_id,
                client_secret=reddit_secret,
                user_agent=get_setting(db, "reddit_user_agent") or "reddit-saas:v0.1.0",
            )
            reddit.subreddit("test").hot(limit=1)
            reddit_status = "connected"
        except Exception as e:
            reddit_status = f"error: {str(e)[:100]}"

    return {
        "reddit": {"configured": reddit_ok, "status": reddit_status},
        "llm": {"configured": llm_ok, "provider": get_setting(db, "llm_provider")},
        "database": {"configured": True, "status": "connected"},
        "redis": {"configured": True, "status": "connected"},
    }


# ---------------------------------------------------------------------------
# Kill switch helpers
# ---------------------------------------------------------------------------


def is_pipeline_enabled(db: Session) -> bool:
    """Check if the pipeline master switch is on."""
    return get_setting(db, "pipeline_enabled").lower() == "true"


def is_generation_enabled(db: Session) -> bool:
    """Check if generation is enabled."""
    return get_setting(db, "generation_enabled").lower() == "true"


def is_scrape_enabled(db: Session) -> bool:
    """Check if scraping is enabled."""
    return get_setting(db, "scrape_enabled").lower() == "true"
