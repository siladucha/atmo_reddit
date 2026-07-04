"""A/B Test Celery Tasks — automated metric collection and experiment monitoring.

Two scheduled tasks:
- collect_weekly_ab_metrics: Monday 02:30 IST — collects metrics and generates reports
- check_experiment_durations: Daily 07:00 IST — emits alerts when experiments reach duration

Both gated by `ab_test_enabled` system setting.
"""

from datetime import datetime, timezone

from app.database import SessionLocal
from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="collect_weekly_ab_metrics", bind=True, max_retries=1)
def collect_weekly_ab_metrics(self):
    """Collect weekly metrics for all active A/B experiments.

    Runs every Monday at 02:30 IST. For each active experiment:
    1. Determine if a new week boundary has been crossed since last collection
    2. If yes, collect metrics for that week
    3. Generate statistical report for that week

    Gated by `ab_test_enabled` system setting.
    """
    db = SessionLocal()
    try:
        from app.services.settings import get_setting

        if get_setting(db, "ab_test_enabled") != "true":
            logger.debug("A/B test framework disabled, skipping metric collection")
            return {"status": "disabled"}

        from app.models.ab_test import ExperimentRun, MetricSnapshot
        from app.services.ab_test.metric_collector import collect_week_metrics
        from app.services.ab_test.statistical_reporter import generate_weekly_report
        from sqlalchemy import func

        # Find all active experiments
        active_experiments = (
            db.query(ExperimentRun)
            .filter(ExperimentRun.status == "active")
            .all()
        )

        if not active_experiments:
            logger.debug("No active A/B experiments, skipping")
            return {"status": "no_active_experiments"}

        results = []
        now = datetime.now(timezone.utc)

        for experiment in active_experiments:
            if not experiment.started_at:
                continue

            # Determine current week number
            elapsed = now - experiment.started_at
            current_week = int(elapsed.days // 7) + 1

            if current_week < 1:
                continue

            # Check which weeks have already been collected
            last_collected_week = (
                db.query(func.max(MetricSnapshot.week_number))
                .filter(MetricSnapshot.experiment_id == experiment.id)
                .scalar()
            ) or 0

            # Collect for each uncollected week up to current_week - 1
            # (current week is still in progress)
            for week in range(last_collected_week + 1, current_week):
                try:
                    logger.info(
                        "Collecting metrics for experiment %s week %d",
                        experiment.id, week,
                    )
                    snapshots = collect_week_metrics(db, experiment.id, week)
                    db.commit()

                    # Generate report for this week
                    report = generate_weekly_report(db, experiment.id, week)
                    db.commit()

                    results.append({
                        "experiment_id": str(experiment.id),
                        "experiment_name": experiment.name,
                        "week": week,
                        "snapshots": len(snapshots),
                        "early_termination": report.early_termination_recommended,
                    })
                except Exception as e:
                    db.rollback()
                    logger.error(
                        "Error collecting metrics for experiment %s week %d: %s",
                        experiment.id, week, e,
                    )
                    results.append({
                        "experiment_id": str(experiment.id),
                        "week": week,
                        "error": str(e),
                    })

        logger.info("A/B metric collection complete: %d results", len(results))
        return {"status": "ok", "results": results}

    except Exception as e:
        db.rollback()
        logger.error("A/B metric collection task failed: %s", e)
        raise
    finally:
        db.close()


@celery_app.task(name="check_experiment_durations", bind=True)
def check_experiment_durations(self):
    """Check if any active experiment has reached its planned duration.

    Runs daily at 07:00 IST. Emits an activity event when experiment
    reaches planned_duration_weeks, notifying operator to conclude.

    Gated by `ab_test_enabled` system setting.
    """
    db = SessionLocal()
    try:
        from app.services.settings import get_setting

        if get_setting(db, "ab_test_enabled") != "true":
            return {"status": "disabled"}

        from app.models.ab_test import ExperimentRun
        from app.models.activity_event import ActivityEvent

        now = datetime.now(timezone.utc)

        active_experiments = (
            db.query(ExperimentRun)
            .filter(ExperimentRun.status == "active")
            .all()
        )

        alerts_sent = []

        for experiment in active_experiments:
            if not experiment.started_at:
                continue

            elapsed_weeks = (now - experiment.started_at).days / 7.0

            if elapsed_weeks >= experiment.planned_duration_weeks:
                # Check if we already emitted this alert (avoid daily spam)
                existing_alert = (
                    db.query(ActivityEvent)
                    .filter(
                        ActivityEvent.event_type == "ab_experiment_duration_reached",
                        ActivityEvent.event_metadata["experiment_id"].astext == str(experiment.id),
                    )
                    .first()
                )
                if existing_alert:
                    continue

                # Emit alert
                event = ActivityEvent(
                    event_type="ab_experiment_duration_reached",
                    message=(
                        f"A/B experiment '{experiment.name}' has reached its "
                        f"planned duration of {experiment.planned_duration_weeks} weeks. "
                        f"Consider concluding the experiment."
                    ),
                    event_metadata={
                        "experiment_id": str(experiment.id),
                        "experiment_name": experiment.name,
                        "planned_weeks": experiment.planned_duration_weeks,
                        "elapsed_weeks": round(elapsed_weeks, 1),
                    },
                )
                db.add(event)
                alerts_sent.append(experiment.name)

        if alerts_sent:
            db.commit()
            logger.info(
                "Duration alerts sent for experiments: %s", alerts_sent
            )

        return {"status": "ok", "alerts_sent": alerts_sent}

    except Exception as e:
        db.rollback()
        logger.error("Check experiment durations failed: %s", e)
        raise
    finally:
        db.close()
