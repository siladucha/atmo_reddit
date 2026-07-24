"""System settings service — read/write settings from DB."""

from app.logging_config import get_logger
import uuid

from sqlalchemy.orm import Session

from app.models.settings import SystemSetting
from app.services import audit as audit_service

logger = get_logger(__name__)

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
        "value": "max.breger@gmail.com",
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
    "reddit_status_manual_freshness_hours": {
        "value": "6",
        "secret": False,
        "desc": "Minimum age before manual Reddit account metadata checks hit the API again",
        "group": "reddit_api",
    },
    "reddit_status_manual_batch_limit": {
        "value": "25",
        "secret": False,
        "desc": "Maximum avatars a manual Check visible action may refresh at once",
        "group": "reddit_api",
    },
    "reddit_profile_analytics_freshness_hours": {
        "value": "24",
        "secret": False,
        "desc": "Minimum age before profile analytics refreshes fetch from Reddit again",
        "group": "reddit_api",
    },
    "reddit_profile_analytics_batch_limit": {
        "value": "20",
        "secret": False,
        "desc": "Maximum avatars refreshed by the scheduled profile analytics snapshot job",
        "group": "reddit_api",
    },
    "external_shadowban_checker_enabled": {
        "value": "false",
        "secret": False,
        "desc": "Use an external shadowban checker before falling back to Reddit visibility checks",
        "group": "reddit_api",
    },
    "external_shadowban_checker_url_template": {
        "value": "",
        "secret": False,
        "desc": "External checker URL template. Use {username}, for example https://checker.example/u/{username}",
        "group": "reddit_api",
    },
    "external_shadowban_checker_timeout_seconds": {
        "value": "8",
        "secret": False,
        "desc": "Timeout for the external shadowban checker HTTP request",
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
    "llm_editing_model": {
        "value": "gemini/gemini-2.5-flash",
        "secret": False,
        "desc": "Model for comment editing/cleanup (cheap, fast)",
        "group": "llm",
    },
    "llm_persona_model": {
        "value": "gemini/gemini-2.5-flash",
        "secret": False,
        "desc": "Model for persona selection routing (cheap, fast)",
        "group": "llm",
    },
    "llm_strategy_model": {
        "value": "anthropic/claude-sonnet-4-20250514",
        "secret": False,
        "desc": "Model for strategy generation (try claude-3-5-haiku-20241022 for cheaper)",
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
    "sales_calendar_url": {
        "value": "",
        "secret": False,
        "desc": "Sales calendar/booking URL shown to expired trial users (e.g. Calendly link). Falls back to mailto if empty.",
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
        "value": "6",
        "secret": False,
        "desc": "Freshness window in hours (1–168). Each subreddit is re-scraped after this many hours.",
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
    # --- Provider-Level Budget Monitoring ---
    "provider_budget_anthropic_usd": {
        "value": "50",
        "secret": False,
        "desc": "Anthropic monthly credit limit in USD. Alert at 70%, block at 95%.",
        "group": "budget",
    },
    "provider_budget_gemini_usd": {
        "value": "300",
        "secret": False,
        "desc": "Google Gemini monthly budget in USD (0 = unlimited/free tier).",
        "group": "budget",
    },
    "provider_budget_perplexity_usd": {
        "value": "50",
        "secret": False,
        "desc": "Perplexity monthly budget in USD (0 = unlimited).",
        "group": "budget",
    },
    "provider_budget_openai_usd": {
        "value": "50",
        "secret": False,
        "desc": "OpenAI monthly budget in USD (0 = unlimited).",
        "group": "budget",
    },
    "provider_budget_alert_threshold_pct": {
        "value": "70",
        "secret": False,
        "desc": "Percentage of provider budget at which warning alert fires.",
        "group": "budget",
    },
    "provider_budget_block_threshold_pct": {
        "value": "95",
        "secret": False,
        "desc": "Percentage of provider budget at which calls auto-fallback to another provider.",
        "group": "budget",
    },
    # Pipeline v2 — Operational Guardrails
    "dedup_lookback_days": {
        "value": "30",
        "secret": False,
        "desc": "Lookback window (days) for cross-avatar dedup on approved/posted drafts",
        "group": "pipeline_v2",
    },
    "thread_max_age_hours": {
        "value": "48",
        "secret": False,
        "desc": "Maximum thread age (hours) for scoring and generation eligibility",
        "group": "pipeline_v2",
    },
    "max_comments_per_sub_per_day": {
        "value": "2",
        "secret": False,
        "desc": "Maximum comments per subreddit per day per avatar",
        "group": "pipeline_v2",
    },
    "min_scrape_interval_minutes": {
        "value": "30",
        "secret": False,
        "desc": "Minimum minutes between scrapes of the same subreddit",
        "group": "pipeline_v2",
    },
    "min_comment_interval_minutes": {
        "value": "15",
        "secret": False,
        "desc": "Minimum minutes between consecutive comments by same avatar",
        "group": "pipeline_v2",
    },
    "max_brand_ratio_percent": {
        "value": "30",
        "secret": False,
        "desc": "Maximum brand mention ratio (%) over 30-day window",
        "group": "pipeline_v2",
    },
    "hill_hook_target_min_percent": {
        "value": "25",
        "secret": False,
        "desc": "Below this hook usage %, prompt encourages hook usage",
        "group": "pipeline_v2",
    },
    "hill_hook_target_max_percent": {
        "value": "35",
        "secret": False,
        "desc": "Above this hook usage %, prompt discourages hook usage",
        "group": "pipeline_v2",
    },
    "scoring_batch_size": {
        "value": "5",
        "secret": False,
        "desc": "Number of threads per batch scoring LLM call (Phase 2: 5 for cost optimization)",
        "group": "pipeline_v2",
    },
    "strategy_max_age_days": {
        "value": "30",
        "secret": False,
        "desc": "Strategy document validity window (days)",
        "group": "pipeline_v2",
    },
    "generation_max_body_chars": {
        "value": "500",
        "secret": False,
        "desc": "Maximum characters for post body in generation prompt (Phase 2 context trimming)",
        "group": "pipeline_v2",
    },
    "generation_max_voice_chars": {
        "value": "500",
        "secret": False,
        "desc": "Maximum characters for voice profile in generation prompt",
        "group": "pipeline_v2",
    },
    # Health Check
    "health_check_interval_hours": {
        "value": "12",
        "secret": False,
        "desc": "How often the periodic health check task runs (hours)",
        "group": "health_check",
    },
    "health_check_min_comments": {
        "value": "3",
        "secret": False,
        "desc": "Minimum recent comments required for visibility classification",
        "group": "health_check",
    },
    "health_check_visibility_threshold": {
        "value": "0.5",
        "secret": False,
        "desc": "Visibility ratio above which avatar is classified ACTIVE (0.0-1.0)",
        "group": "health_check",
    },
    "health_check_rate_limit_delay_seconds": {
        "value": "2",
        "secret": False,
        "desc": "Delay between individual avatar checks in a batch (seconds)",
        "group": "health_check",
    },
    "health_check_max_failures_before_unknown": {
        "value": "5",
        "secret": False,
        "desc": "Consecutive failures before status becomes UNKNOWN",
        "group": "health_check",
    },
    "health_check_max_failures_before_limited": {
        "value": "3",
        "secret": False,
        "desc": "Consecutive failures before emitting LIMITED warning",
        "group": "health_check",
    },
    "health_check_comment_lookback_days": {
        "value": "7",
        "secret": False,
        "desc": "How far back to look for avatar comments (days)",
        "group": "health_check",
    },
    "health_check_max_comments_to_sample": {
        "value": "10",
        "secret": False,
        "desc": "Maximum comments to fetch per avatar for visibility check",
        "group": "health_check",
    },
    # CQS (Contributor Quality Score)
    "cqs_check_interval_days": {
        "value": "7",
        "secret": False,
        "desc": "How often to re-check CQS for each avatar (days). Avatars checked more recently are skipped.",
        "group": "health_check",
    },
    "cqs_check_rate_limit_delay_seconds": {
        "value": "3",
        "secret": False,
        "desc": "Delay between individual CQS checks in a batch (seconds)",
        "group": "health_check",
    },
    "cqs_check_tasks_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Kill switch for CQS check task generation. When false, the daily CQS task scheduler skips execution.",
        "group": "health_check",
    },
    # --- Automated Posting ---
    "auto_posting_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Global kill switch for automated posting. Set to 'false' to halt all auto-posts immediately.",
        "group": "posting",
    },
    "auto_posting_daily_cap": {
        "value": "8",
        "secret": False,
        "desc": "Maximum automated posts per avatar per day (safety ceiling). Effective cap = min(phase_limit, this value).",
        "group": "posting",
    },
    # --- GEO/AEO Prompt Monitoring ---
    "geo_runs_per_prompt": {
        "value": "3",
        "secret": False,
        "desc": "Number of times each prompt is executed per batch (for statistical validity)",
        "group": "geo",
    },
    "geo_rate_limit_perplexity_rpm": {
        "value": "20",
        "secret": False,
        "desc": "Max Perplexity API requests per minute for GEO queries",
        "group": "geo",
    },
    "geo_provider_perplexity_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Enable Perplexity Sonar as GEO query provider",
        "group": "geo",
    },
    "geo_perplexity_api_key": {
        "value": "",
        "secret": True,
        "desc": "Perplexity API key for GEO monitoring queries",
        "group": "geo",
    },
    "geo_provider_openai_enabled": {
        "value": "false",
        "secret": False,
        "desc": "Enable OpenAI (ChatGPT) as GEO query provider. Requires openai_api_key set.",
        "group": "geo",
    },
    "geo_provider_anthropic_enabled": {
        "value": "false",
        "secret": False,
        "desc": "Enable Anthropic (Claude) as GEO query provider. Uses shared llm_api_key (Anthropic).",
        "group": "geo",
    },
    "geo_rate_limit_openai_rpm": {
        "value": "20",
        "secret": False,
        "desc": "Max OpenAI API requests per minute for GEO queries",
        "group": "geo",
    },
    "geo_rate_limit_anthropic_rpm": {
        "value": "20",
        "secret": False,
        "desc": "Max Anthropic API requests per minute for GEO queries",
        "group": "geo",
    },
    "openai_api_key": {
        "value": "",
        "secret": True,
        "desc": "OpenAI API key for GEO monitoring and embeddings",
        "group": "geo",
    },
    "geo_monthly_cost_alert_threshold": {
        "value": "100",
        "secret": False,
        "desc": "Monthly cost alert threshold in USD for GEO queries",
        "group": "geo",
    },
    # --- EPG 2.0 (Attention Portfolio Manager) ---
    "epg2_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Enable EPG 2.0 Attention Portfolio Manager. When false, uses legacy build_daily_epg().",
        "group": "epg",
    },
    "epg2_min_opportunities": {
        "value": "10",
        "secret": False,
        "desc": "Minimum opportunities to find before allocation (below this triggers market_scarcity).",
        "group": "epg",
    },
    "epg2_max_opportunities": {
        "value": "50",
        "secret": False,
        "desc": "Maximum opportunities to evaluate per avatar per daily run.",
        "group": "epg",
    },
    "epg2_min_return_threshold": {
        "value": "20",
        "secret": False,
        "desc": "Minimum Expected_Return_Score (0-100) for an opportunity to be considered viable.",
        "group": "epg",
    },
    "epg2_subreddit_max_share": {
        "value": "40",
        "secret": False,
        "desc": "Maximum percentage of daily actions allocated to a single subreddit (diversification cap).",
        "group": "epg",
    },
    "epg2_zero_day_alert_threshold": {
        "value": "50",
        "secret": False,
        "desc": "Zero-day rate percentage (14-day window) above which an admin alert is generated.",
        "group": "epg",
    },
    "epg2_decision_retention_days": {
        "value": "90",
        "secret": False,
        "desc": "Number of days to retain full decision records before archival (metadata kept, details pruned).",
        "group": "epg",
    },
    # --- Email Task Delivery ---
    "email_tasks_enabled": {
        "value": "false",
        "secret": False,
        "desc": "Enable email task delivery for approved EPG slots. When true, approved slots generate execution tasks and send emails.",
        "group": "email_tasks",
    },
    "email_tasks_default_recipient": {
        "value": "",
        "secret": False,
        "desc": "Default recipient email for execution tasks (fallback if no executor assigned).",
        "group": "email_tasks",
    },
    "email_tasks_max_resends": {
        "value": "3",
        "secret": False,
        "desc": "Maximum number of resend attempts per task (anti-spam).",
        "group": "email_tasks",
    },
    "email_tasks_cooldown_minutes": {
        "value": "10",
        "secret": False,
        "desc": "Minimum minutes between delivery attempts for the same task (anti-spam).",
        "group": "email_tasks",
    },
    "email_tasks_deadline_hours": {
        "value": "4",
        "secret": False,
        "desc": "Default deadline offset in hours from scheduled_at (or created_at if no schedule).",
        "group": "email_tasks",
    },
    "epg_slot_window_hours": {
        "value": "2",
        "secret": False,
        "desc": "Soft execution window in hours. Task can be posted any time within scheduled_at + this window.",
        "group": "email_tasks",
    },
    "smtp_host": {
        "value": "",
        "secret": False,
        "desc": "SMTP server hostname (e.g. mail.goramp.it)",
        "group": "email_tasks",
    },
    "smtp_port": {
        "value": "587",
        "secret": False,
        "desc": "SMTP server port (587 for STARTTLS, 465 for SSL)",
        "group": "email_tasks",
    },
    "smtp_user": {
        "value": "",
        "secret": False,
        "desc": "SMTP authentication username",
        "group": "email_tasks",
    },
    "smtp_password": {
        "value": "",
        "secret": True,
        "desc": "SMTP authentication password (stored encrypted)",
        "group": "email_tasks",
    },
    "smtp_from_email": {
        "value": "tasks@gorampit.com",
        "secret": False,
        "desc": "From email address for task delivery emails",
        "group": "email_tasks",
    },
    "smtp_from_name": {
        "value": "RAMP Task System",
        "secret": False,
        "desc": "From display name for task delivery emails",
        "group": "email_tasks",
    },
    "smtp_use_tls": {
        "value": "true",
        "secret": False,
        "desc": "Use TLS for SMTP connection (true for STARTTLS on port 587)",
        "group": "email_tasks",
    },
    # --- Fitness Gate ---
    "fitness_gate_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Enable/disable Fitness Gate in the generation pipeline. When false, all Smart Scoring engage results pass through to generation unfiltered.",
        "group": "pipeline_v2",
    },
    # --- Risk-Aware Activation ---
    "activation_routing_enabled": {
        "value": "false",
        "secret": False,
        "desc": "Enable risk-aware zone routing for Phase 0-1 avatars (safe → bridge → target). When false, legacy hobby_subreddits used.",
        "group": "pipeline_v2",
    },
    # --- Draft Expiry ---
    "draft_expiry_approved_hours": {
        "value": "48",
        "secret": False,
        "desc": "Hours before approved drafts are automatically expired",
        "group": "pipeline",
    },
    "draft_expiry_pending_hours": {
        "value": "72",
        "secret": False,
        "desc": "Hours before pending drafts are automatically expired",
        "group": "pipeline",
    },
    "draft_expiry_enabled": {
        "value": "true",
        "secret": False,
        "desc": "Kill switch for automatic draft expiry",
        "group": "pipeline",
    },
    # --- Trial Conversion Intelligence ---
    "trial_scoring_weights": {
        "value": '{"engagement": 0.20, "intent": 0.25, "value_realization": 0.25, "conversion": 0.20, "negative_cap": 0.30}',
        "secret": False,
        "desc": "JSON weights for trial scoring categories (engagement, intent, value_realization, conversion, negative_cap)",
        "group": "trial_intelligence",
    },
    # --- Telegram Draft Review ---
    "telegram_draft_review_enabled": {
        "value": "false",
        "secret": False,
        "desc": "Enable Telegram draft review notifications. When true, users with linked Telegram and notification level 'all' or 'warning' receive draft cards for approval.",
        "group": "telegram",
    },
    "telegram_webhook_secret": {
        "value": "",
        "secret": True,
        "desc": "Secret token for Telegram webhook validation (X-Telegram-Bot-Api-Secret-Token header). Generate a random string.",
        "group": "telegram",
    },
    # Billing Plan Enforcement
    "billing_enabled": {
        "value": "false",
        "secret": False,
        "desc": "Master kill switch for billing enforcement. When false, all plan limit checks are bypassed (existing behavior preserved).",
        "group": "billing",
    },
    "grace_period_default_days": {
        "value": "7",
        "secret": False,
        "desc": "Standard grace period duration in days after payment failure (self-serve clients).",
        "group": "billing",
    },
    "grace_period_repeat_days": {
        "value": "3",
        "secret": False,
        "desc": "Shortened grace period for repeat offenders (previous grace within 60 days).",
        "group": "billing",
    },
    "grace_period_agency_days": {
        "value": "14",
        "secret": False,
        "desc": "Extended grace period for agency tier clients (invoice-based billing).",
        "group": "billing",
    },
    "stripe_webhook_secret": {
        "value": "",
        "secret": True,
        "desc": "Stripe webhook signing secret (whsec_...). Required for webhook signature verification.",
        "group": "billing",
    },
    "stripe_secret_key": {
        "value": "",
        "secret": True,
        "desc": "Stripe API secret key (sk_live_... or sk_test_...). Required for checkout session creation and subscription management.",
        "group": "billing",
    },
    "stripe_publishable_key": {
        "value": "",
        "secret": True,
        "desc": "Stripe Publishable Key (pk_test_... or pk_live_...). Required for client-side checkout.",
        "group": "billing",
    },
    # --- Engineering Memory (Notion) ---
    "notion_engineering_memory_token": {
        "value": "",
        "secret": True,
        "desc": "Notion integration token for Engineering Memory database",
        "group": "engineering_memory",
    },
    "notion_engineering_memory_database_id": {
        "value": "",
        "secret": False,
        "desc": "Notion database ID for Engineering Memory",
        "group": "engineering_memory",
    },
}

# ---------------------------------------------------------------------------
# In-memory cache
# ---------------------------------------------------------------------------
_cache: dict[str, str] = {}
_cache_loaded: bool = False


# ---------------------------------------------------------------------------
# Health check parameter validation
# ---------------------------------------------------------------------------

HEALTH_CHECK_VALIDATORS: dict[str, tuple[callable, str]] = {
    "health_check_interval_hours": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
    "health_check_min_comments": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
    "health_check_visibility_threshold": (
        lambda v: 0.0 <= float(v) <= 1.0,
        "Must be a number between 0.0 and 1.0",
    ),
    "health_check_rate_limit_delay_seconds": (
        lambda v: int(v) >= 0,
        "Must be an integer >= 0",
    ),
    "health_check_max_failures_before_unknown": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
    "health_check_max_failures_before_limited": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
    "health_check_comment_lookback_days": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
    "health_check_max_comments_to_sample": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
    "cqs_check_interval_days": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
    "cqs_check_rate_limit_delay_seconds": (
        lambda v: float(v) >= 0,
        "Must be a number >= 0",
    ),
}

# ---------------------------------------------------------------------------
# EPG 2.0 setting validators
# ---------------------------------------------------------------------------

EPG2_VALIDATORS: dict[str, tuple[callable, str]] = {
    "epg2_enabled": (
        lambda v: v.lower() in ("true", "false", "0", "1"),
        "Must be 'true' or 'false'",
    ),
    "epg2_min_opportunities": (
        lambda v: 1 <= int(v) <= 100,
        "Must be an integer between 1 and 100",
    ),
    "epg2_max_opportunities": (
        lambda v: 1 <= int(v) <= 200,
        "Must be an integer between 1 and 200",
    ),
    "epg2_min_return_threshold": (
        lambda v: 0 <= int(v) <= 100,
        "Must be an integer between 0 and 100",
    ),
    "epg2_subreddit_max_share": (
        lambda v: 1 <= int(v) <= 100,
        "Must be an integer between 1 and 100 (percentage)",
    ),
    "epg2_zero_day_alert_threshold": (
        lambda v: 1 <= int(v) <= 100,
        "Must be an integer between 1 and 100 (percentage)",
    ),
    "epg2_decision_retention_days": (
        lambda v: int(v) >= 1,
        "Must be an integer >= 1",
    ),
}


def validate_setting(key: str, value: str) -> tuple[bool, str]:
    """Validate a setting value against known constraints.

    Returns (is_valid, error_message). If valid, error_message is empty.
    """
    # Check health check validators
    if key in HEALTH_CHECK_VALIDATORS:
        validator_fn, error_msg = HEALTH_CHECK_VALIDATORS[key]
        try:
            if not validator_fn(value):
                return False, f"{key}: {error_msg}"
        except (ValueError, TypeError):
            return False, f"{key}: {error_msg}"
        return True, ""

    # Check EPG 2.0 validators
    if key in EPG2_VALIDATORS:
        validator_fn, error_msg = EPG2_VALIDATORS[key]
        try:
            if not validator_fn(value):
                return False, f"{key}: {error_msg}"
        except (ValueError, TypeError):
            return False, f"{key}: {error_msg}"
        return True, ""

    return True, ""


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


def get_setting_int(db: Session, key: str, default: int = 0) -> int:
    """Get a setting value as an integer with safe fallback.

    Returns the default if the key is missing, empty, or not a valid integer.
    """
    raw = get_setting(db, key)
    if not raw:
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning("Setting '%s' has non-integer value '%s', using default %d", key, raw, default)
        return default


def get_setting_float(db: Session, key: str, default: float = 0.0) -> float:
    """Get a setting value as a float with safe fallback.

    Returns the default if the key is missing, empty, or not a valid number.
    """
    raw = get_setting(db, key)
    if not raw:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        logger.warning("Setting '%s' has non-numeric value '%s', using default %s", key, raw, default)
        return default


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
        "geo_perplexity_api_key": "PERPLEXITY_API_KEY",
        "stripe_secret_key": "STRIPE_SECRET_KEY",
        "stripe_webhook_secret": "STRIPE_WEBHOOK_SECRET",
        "stripe_publishable_key": "STRIPE_PUBLISHABLE_KEY",
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
#
# These ALWAYS read directly from the database, bypassing the in-memory cache.
# Kill switches are checked infrequently (once per task execution) and must
# reflect the latest value set by the admin — even from a different process
# (e.g., Celery worker reading a value set by the FastAPI admin UI).
# ---------------------------------------------------------------------------


def _get_setting_fresh(db: Session, key: str) -> str:
    """Read a setting directly from DB, bypassing in-memory cache.

    Used for kill switches and other critical settings that must reflect
    cross-process changes immediately.
    """
    row = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if row:
        return row.value
    # Fallback to default
    if key in DEFAULTS:
        return DEFAULTS[key]["value"]
    return ""


def is_pipeline_enabled(db: Session) -> bool:
    """Check if the pipeline master switch is on (always fresh from DB)."""
    return _get_setting_fresh(db, "pipeline_enabled").lower() == "true"


def is_generation_enabled(db: Session) -> bool:
    """Check if generation is enabled (always fresh from DB)."""
    return _get_setting_fresh(db, "generation_enabled").lower() == "true"


def is_scrape_enabled(db: Session) -> bool:
    """Check if scraping is enabled (always fresh from DB)."""
    return _get_setting_fresh(db, "scrape_enabled").lower() == "true"

def is_fitness_gate_enabled(db: Session) -> bool:
    """Check if the Fitness Gate is enabled (always fresh from DB).

    When enabled, the pipeline evaluates avatar-subreddit fitness before
    generation. When disabled, all engage threads pass through unfiltered.
    """
    return _get_setting_fresh(db, "fitness_gate_enabled").lower() == "true"

