"""
Lightweight Celery app for Beat scheduler only.

Beat does NOT need to import task modules — it only sends task names to the broker.
By removing `include=` and `backend=`, we avoid loading SQLAlchemy, LiteLLM, PRAW,
scipy, etc. — reducing memory from ~225 MB (leaking) to ~25 MB (stable).

Workers still use the full `worker.py` app with all includes.
"""
from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

beat_app = Celery(
    "ramp",
    broker=settings.redis_url,
    # No backend — Beat never reads results
    # No include — Beat never executes tasks, only sends their names
)

beat_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Jerusalem",
    enable_utc=False,
    # Beat schedule — all periodic tasks
    beat_schedule={
        "system-heartbeat": {
            "task": "system_heartbeat",
            "schedule": 60.0,
        },
        "ai-pipeline-morning": {
            "task": "run_full_pipeline_all_clients",
            "schedule": crontab(hour=8, minute=0),
        },
        "ai-pipeline-afternoon": {
            "task": "run_full_pipeline_all_clients",
            "schedule": crontab(hour=14, minute=0),
        },
        "hobby-discovery-scrape": {
            "task": "scrape_hobby_all_avatars",
            "schedule": crontab(hour="7,13", minute=45),
        },
        "avatar-visibility-health-check": {
            "task": "health_check_all_avatars",
            "schedule": crontab(hour="7,13", minute=30),
        },
        "scrape-queue-tick": {
            "task": "queue_tick",
            "schedule": 60.0,
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
            "schedule": crontab(hour=6, minute=30),
        },
        "repurpose-scrape-weekly": {
            "task": "scrape_repurpose_all_subreddits",
            "schedule": crontab(hour=3, minute=0, day_of_week="sunday"),
        },
        "execute-pending-posts": {
            "task": "execute_pending_posts",
            "schedule": 300.0,
        },
        "dispatch-due-email-tasks": {
            "task": "dispatch_due_email_tasks",
            "schedule": 300.0,
        },
        "dispatch-approved-post-drafts": {
            "task": "dispatch_approved_post_drafts",
            "schedule": 300.0,
        },
        "cqs-check-tasks-daily": {
            "task": "generate_cqs_check_tasks_all_avatars",
            "schedule": crontab(hour=7, minute=0),
        },
        "epg-build-generate": {
            "task": "build_and_generate_epg_all_avatars",
            "schedule": crontab(hour=8, minute=15),
        },
        "epg-ensure-daily-minimum": {
            "task": "ensure_daily_epg_minimum",
            "schedule": crontab(hour=9, minute=0),
        },
        "generate-posts-daily": {
            "task": "generate_posts_all_clients",
            "schedule": crontab(hour=10, minute=0),
        },
        "epg-topup-afternoon": {
            "task": "epg_topup_underfilled_avatars",
            "schedule": crontab(hour=14, minute=15),
        },
        "check-karma-outcomes-4h": {
            "task": "check_karma_outcomes",
            "schedule": crontab(hour="12,18", minute=15),
        },
        "check-karma-outcomes-28h": {
            "task": "check_karma_outcomes",
            "schedule": crontab(hour="0,6", minute=15),
        },
        "compute-daily-performance-metrics": {
            "task": "compute_daily_performance_metrics",
            "schedule": crontab(hour=1, minute=0),
        },
        "archive-old-decision-records": {
            "task": "archive_old_decision_records",
            "schedule": crontab(hour=1, minute=30),
        },
        "snapshot-comment-outcomes-4h": {
            "task": "snapshot_comment_outcomes",
            "schedule": crontab(hour="*/4", minute=45),
        },
        "run-feedback-loop-daily": {
            "task": "run_feedback_loop_all",
            "schedule": crontab(hour=2, minute=0),
        },
        "check-trial-negative-signals-4h": {
            "task": "check_trial_negative_signals",
            "schedule": crontab(hour="*/4", minute=30),
        },
        "classify-expired-trials-daily": {
            "task": "classify_expired_trials",
            "schedule": crontab(hour=2, minute=30),
        },
        "refresh-emotional-profiles-weekly": {
            "task": "refresh_subreddit_emotional_profiles",
            "schedule": crontab(hour=4, minute=30, day_of_week="sunday"),
        },
        "check-stale-avatar-drafts": {
            "task": "check_stale_avatar_drafts",
            "schedule": 600.0,
        },
        "check-avatar-invariant-daily": {
            "task": "check_avatar_invariant",
            "schedule": crontab(hour=2, minute=30),
        },
        "check-onboarding-stall-hourly": {
            "task": "check_onboarding_stall",
            "schedule": crontab(minute=45),
        },
        "continuous-discovery-weekly": {
            "task": "run_continuous_discovery_all",
            "schedule": crontab(hour=4, minute=0, day_of_week="sunday"),
        },
        "risk-profile-rules-weekly": {
            "task": "extract_subreddit_rules_batch",
            "schedule": crontab(hour=5, minute=0, day_of_week="sunday"),
        },
        "risk-profile-moderation-weekly": {
            "task": "compute_moderation_profiles_batch",
            "schedule": crontab(hour=5, minute=15, day_of_week="sunday"),
        },
        "risk-profile-scores-weekly": {
            "task": "compute_risk_scores_batch",
            "schedule": crontab(hour=5, minute=30, day_of_week="sunday"),
        },
        "risk-profile-adaptive-daily": {
            "task": "refresh_due_risk_profiles",
            "schedule": crontab(hour=5, minute=0),
        },
        "probe-subreddit-bans-weekly": {
            "task": "probe_subreddit_bans",
            "schedule": crontab(hour=3, minute=45, day_of_week="sunday"),
        },
        "expire-extension-leases": {
            "task": "expire_extension_leases",
            "schedule": 300.0,
        },
        "geo-monitoring-daily": {
            "task": "run_geo_monitoring_daily",
            "schedule": crontab(hour=9, minute=30),
        },
        "cost-reconciliation-daily": {
            "task": "run_cost_reconciliation",
            "schedule": crontab(hour=1, minute=5),
        },
        "provider-budget-check-4h": {
            "task": "check_provider_budgets",
            "schedule": crontab(hour="3,7,11,15,19,23", minute=45),
        },
        "generate-weekly-reports": {
            "task": "generate_weekly_reports_all_clients",
            "schedule": crontab(hour=8, minute=0, day_of_week=1),
        },
        "ab-test-collect-metrics-weekly": {
            "task": "collect_weekly_ab_metrics",
            "schedule": crontab(hour=2, minute=30, day_of_week=1),
        },
        "ab-test-check-durations-daily": {
            "task": "check_experiment_durations",
            "schedule": crontab(hour=7, minute=0),
        },
        "expire-stale-drafts": {
            "task": "expire_stale_drafts",
            "schedule": crontab(minute=0),
        },
        # Weekly email digests (Sunday 19:00 Israel time)
        "weekly-system-health-email": {
            "task": "send_weekly_system_health_email",
            "schedule": crontab(hour=19, minute=0, day_of_week=0),
        },
        "weekly-business-summary-email": {
            "task": "send_weekly_business_summary_email",
            "schedule": crontab(hour=19, minute=15, day_of_week=0),
        },
    },
    # Broker connection resilience
    broker_connection_retry_on_startup=True,
    broker_connection_retry=True,
    broker_connection_max_retries=None,
    broker_connection_timeout=10,
)
