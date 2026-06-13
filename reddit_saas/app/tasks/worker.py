from celery import Celery
from celery.schedules import crontab

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
        # "hobby-pipeline-daily" removed: EPG handles hobby slot decisions.
        # Hobby scraping (discovery) runs separately to supply opportunity pool.
        "hobby-discovery-scrape": {
            "task": "scrape_hobby_all_avatars",
            "schedule": crontab(hour="7,13", minute=45),  # Before EPG runs (08:15, 14:15)
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
        "cqs-check-daily": {
            "task": "check_cqs_all_avatars",
            "schedule": crontab(hour=6, minute=30),  # After phase evaluation (06:00), before health check (07:30)
        },
        "repurpose-scrape-weekly": {
            "task": "scrape_repurpose_all_subreddits",
            "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),  # Weekly, low-traffic time
        },
        "execute-pending-posts": {
            "task": "execute_pending_posts",
            "schedule": 300.0,  # Every 5 minutes — check for approved slots due for posting
        },
        "epg-build-generate-morning": {
            "task": "build_and_generate_epg_all_avatars",
            "schedule": crontab(hour=8, minute=15),  # After AI pipeline (08:00) scores threads
        },
        "epg-build-generate-afternoon": {
            "task": "build_and_generate_epg_all_avatars",
            "schedule": crontab(hour=14, minute=15),  # After afternoon pipeline (14:00)
        },
        "check-karma-outcomes-4h": {
            "task": "check_karma_outcomes",
            "schedule": crontab(hour="12,18", minute=15),  # 4h after EPG runs (08:15, 14:15)
        },
        "check-karma-outcomes-28h": {
            "task": "check_karma_outcomes",
            "schedule": crontab(hour="0,6", minute=15),  # ~24-28h after EPG runs for next-day checks
        },
        "compute-daily-performance-metrics": {
            "task": "compute_daily_performance_metrics",
            "schedule": crontab(hour=1, minute=0),  # 01:00 daily — aggregate yesterday's metrics
        },
        "archive-old-decision-records": {
            "task": "archive_old_decision_records",
            "schedule": crontab(hour=1, minute=30),  # 01:30 daily — prune records > 90 days
        },
        "snapshot-comment-outcomes-4h": {
            "task": "snapshot_comment_outcomes",
            "schedule": crontab(hour="*/4", minute=45),  # Every 4h at :45 — karma/reply/deletion snapshots
        },
        "run-feedback-loop-daily": {
            "task": "run_feedback_loop_all",
            "schedule": crontab(hour=2, minute=0),  # 02:00 daily — after outcomes collected, before next EPG
        },
        "continuous-discovery-weekly": {
            "task": "run_continuous_discovery_all",
            "schedule": crontab(hour=4, minute=0, day_of_week="sunday"),  # Weekly, after feedback loop
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
