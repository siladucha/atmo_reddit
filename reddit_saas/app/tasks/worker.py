from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "reddit_saas",
    broker=settings.redis_url,
    backend=settings.redis_url,
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
        "scrape-and-generate-morning": {
            "task": "run_full_pipeline_all_clients",
            "schedule": crontab(hour=8, minute=0),
        },
        "scrape-and-generate-afternoon": {
            "task": "run_full_pipeline_all_clients",
            "schedule": crontab(hour=14, minute=0),
        },
        "hobby-pipeline-daily": {
            "task": "run_hobby_pipeline_all_avatars",
            "schedule": crontab(hour=10, minute=0),
        },
        "avatar-health-check": {
            "task": "check_all_avatars_health",
            "schedule": crontab(hour="*/12", minute=30),
        },
    },
)

# Import tasks so Celery discovers them
celery_app.autodiscover_tasks(["app.tasks"])
