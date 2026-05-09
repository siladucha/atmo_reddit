from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "reddit_saas",
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
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Beat schedule — automated pipeline runs
    beat_schedule={
        "system-heartbeat": {
            "task": "system_heartbeat",
            "schedule": 60.0,  # Every 60s — system health pulse
        },
        "ai-pipeline-morning": {
            "task": "run_full_pipeline_all_clients",
            "schedule": crontab(hour=8, minute=0),
        },
        "ai-pipeline-afternoon": {
            "task": "run_full_pipeline_all_clients",
            "schedule": crontab(hour=14, minute=0),
        },
        "hobby-pipeline-daily": {
            "task": "run_hobby_pipeline_all_avatars",
            "schedule": crontab(hour=10, minute=0),
        },
        "avatar-visibility-health-check": {
            "task": "health_check_all_avatars",
            "schedule": crontab(hour="7,13", minute=30),  # 30 min before AI pipelines
        },
        "scrape-queue-tick": {
            "task": "queue_tick",
            "schedule": 60.0,  # Fires every 60s; actual interval gated by DB setting
        },
        "evaluate-avatar-phases-daily": {
            "task": "evaluate_all_avatar_phases",
            "schedule": crontab(hour=6, minute=0),
        },
        "karma-tracking-4h": {
            "task": "track_karma_all_avatars",
            "schedule": crontab(hour="*/4", minute=15),
        },
        "profile-analytics-snapshots-daily": {
            "task": "snapshot_profile_analytics_all_avatars",
            "schedule": crontab(hour=5, minute=20),
        },
    },
    # Broker connection resilience
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=None,  # Retry forever
    broker_connection_timeout=10,
    # Worker resilience
    worker_cancel_long_running_tasks_on_connection_loss=True,
)
