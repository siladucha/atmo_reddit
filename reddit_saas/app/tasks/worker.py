from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ramp",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.queue_ticker",
        "app.tasks.scraping",
        "app.tasks.orchestrator",
        "app.tasks.ai_pipeline",
        "app.tasks.heartbeat",
        "app.tasks.karma_tracking",
        "app.tasks.health_check",
        "app.tasks.presence",
        "app.tasks.profile_analytics",
        "app.tasks.strategy",
        "app.tasks.posting",
        "app.tasks.epg",
        "app.tasks.discovery",
        "app.tasks.karma_outcomes",
        "app.tasks.performance_metrics",
        "app.tasks.snapshot_outcomes",
        "app.tasks.feedback",
        "app.tasks.emotional_profile",
        "app.tasks.trial_scoring",
        "app.tasks.trial_negative_signals",
        "app.tasks.byoa",
        "app.tasks.risk_profile",
        "app.tasks.execution_tasks",
        "app.tasks.subreddit_ban_probe",
        "app.tasks.cqs_tasks",
        "app.tasks.extension_tasks",
        "app.tasks.geo_monitoring",
        "app.tasks.intelligence_report",
        "app.tasks.ab_test",
        "app.tasks.draft_expiry",
        "app.tasks.cost_reconciliation",
        "app.tasks.provider_budget_check",
        "app.tasks.weekly_emails",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Jerusalem",
    enable_utc=False,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Beat schedule lives in app/tasks/beat_app.py (lightweight, no heavy imports).
    # Workers don't need it — they only execute tasks, not schedule them.
    # Task routing: on-demand user-triggered tasks go to 'fast' queue
    # so they don't get blocked behind long-running bulk tasks.
    # Both queues share the same Redis rate limiter (global, Redis-based).
    task_routes={
        # On-demand / interactive tasks → fast queue
        'analyze_subreddit_emotional_profile': {'queue': 'fast'},
        'run_full_pipeline_single_client': {'queue': 'fast'},
        'build_epg_single_avatar': {'queue': 'fast'},
        'generate_strategy_for_client': {'queue': 'fast'},
        'generate_intelligence_report_for_client': {'queue': 'fast'},
        # Everything else → default 'celery' queue (implicit)
    },
    task_default_queue='celery',
    # Broker connection resilience
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=None,  # Retry forever
    broker_connection_timeout=10,
    # Worker resilience
    worker_cancel_long_running_tasks_on_connection_loss=True,
)
