"""Celery tasks for EPG 2.0 daily performance metrics computation and archival.

Tasks:
- compute_daily_performance_metrics: Runs at 01:00 daily, computes per-avatar metrics
- archive_old_decision_records: Runs at 01:30 daily, prunes records > 90 days

Metrics computed per avatar:
- Return_On_Attention: karma_gained / actions_taken
- Risk_Adjusted_Return: ROA / avg_risk_score
- Portfolio_Diversification: Shannon entropy of subreddit distribution
- Decision_Accuracy: % of actions with positive karma
- Opportunity_Cost: max(0, highest_rejected_composite - avg_selected_composite)
- Zero_Day_Rate: % of days with zero_day=True in last 30 days

Requirements: 9.1, 13.4, 13.5, 6.5, 6.6, 9.5, 7.6
"""

import math
from datetime import date, datetime, timedelta, timezone

from celery import shared_task
from sqlalchemy import and_, func as sa_func

from app.database import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)

# Alert thresholds
ZERO_DAY_RATE_ALERT_THRESHOLD = 50.0  # percent over 14 days
DECISION_ACCURACY_ALERT_THRESHOLD = 50.0  # percent over 14 days
ARCHIVAL_RETENTION_DAYS = 90


@shared_task(name="compute_daily_performance_metrics")
def compute_daily_performance_metrics():
    """Compute daily performance metrics for all avatars with EPG 2.0 activity.

    Scheduled at 01:00 daily. Computes metrics for yesterday's date.
    Uses UNIQUE constraint (avatar_id, metric_date) with upsert logic.

    Also checks alert conditions:
    - zero_day_rate > 50% over 14 days → admin alert
    - decision_accuracy < 50% over 14 days → model review alert
    """
    from app.models.avatar import Avatar
    from app.models.decision_record import DecisionRecord
    from app.models.opportunity import Opportunity
    from app.models.performance_metric import PerformanceMetric

    db = SessionLocal()
    try:
        yesterday = date.today() - timedelta(days=1)
        now = datetime.now(timezone.utc)

        # Find all avatars that have decision records (active in EPG 2.0)
        avatar_ids_with_records = (
            db.query(DecisionRecord.avatar_id)
            .filter(DecisionRecord.decision_date >= yesterday - timedelta(days=30))
            .distinct()
            .all()
        )
        avatar_ids = [row[0] for row in avatar_ids_with_records]

        if not avatar_ids:
            logger.debug("compute_daily_performance_metrics: no avatars with recent records")
            return {"processed": 0, "alerts": 0}

        stats = {"processed": 0, "updated": 0, "created": 0, "alerts": 0, "errors": 0}

        for avatar_id in avatar_ids:
            try:
                _compute_metrics_for_avatar(db, avatar_id, yesterday, stats)
            except Exception as e:
                stats["errors"] += 1
                logger.error(
                    "compute_daily_performance_metrics: error for avatar %s: %s",
                    avatar_id, str(e)[:200],
                )
                db.rollback()
                continue

        logger.info(
            "compute_daily_performance_metrics complete: processed=%d created=%d "
            "updated=%d alerts=%d errors=%d",
            stats["processed"], stats["created"], stats["updated"],
            stats["alerts"], stats["errors"],
        )
        return stats

    except Exception as e:
        logger.error("compute_daily_performance_metrics failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()


def _compute_metrics_for_avatar(db, avatar_id, metric_date: date, stats: dict):
    """Compute and persist all performance metrics for a single avatar."""
    from app.models.decision_record import DecisionRecord
    from app.models.opportunity import Opportunity
    from app.models.performance_metric import PerformanceMetric

    stats["processed"] += 1

    # --- Gather data for computations ---

    # Get opportunities that were selected/executed on the metric date
    selected_opportunities = (
        db.query(Opportunity)
        .filter(
            Opportunity.avatar_id == avatar_id,
            Opportunity.decision_date == metric_date,
            Opportunity.status.in_(["selected", "executed"]),
        )
        .all()
    )

    # Get rejected opportunities for opportunity cost
    rejected_opportunities = (
        db.query(Opportunity)
        .filter(
            Opportunity.avatar_id == avatar_id,
            Opportunity.decision_date == metric_date,
            Opportunity.status == "rejected",
        )
        .all()
    )

    # Count actions taken and karma gained
    actions_taken = len(selected_opportunities)
    karma_gained = sum(
        (opp.actual_karma or 0) for opp in selected_opportunities
    )

    # --- Compute metrics ---

    # Return_On_Attention: karma_gained / actions_taken
    return_on_attention = None
    if actions_taken > 0:
        return_on_attention = karma_gained / actions_taken

    # Risk_Adjusted_Return: ROA / avg_risk
    risk_adjusted_return = None
    if actions_taken > 0 and return_on_attention is not None:
        avg_risk = sum(opp.risk_score for opp in selected_opportunities) / actions_taken
        if avg_risk > 0:
            risk_adjusted_return = return_on_attention / avg_risk

    # Portfolio_Diversification: Shannon entropy of subreddit distribution
    portfolio_diversification = _compute_shannon_entropy(selected_opportunities)

    # Decision_Accuracy: % of actions with positive karma
    decision_accuracy = None
    actions_with_outcome = [
        opp for opp in selected_opportunities if opp.actual_karma is not None
    ]
    if actions_with_outcome:
        positive_karma_count = sum(
            1 for opp in actions_with_outcome if opp.actual_karma > 0
        )
        decision_accuracy = (positive_karma_count / len(actions_with_outcome)) * 100

    # Opportunity_Cost: max(0, highest_rejected_composite - avg_selected_composite)
    opportunity_cost = None
    if rejected_opportunities and selected_opportunities:
        highest_rejected = max(opp.composite_score for opp in rejected_opportunities)
        avg_selected = sum(opp.composite_score for opp in selected_opportunities) / actions_taken
        opportunity_cost = max(0.0, highest_rejected - avg_selected)
    elif rejected_opportunities and not selected_opportunities:
        # All rejected, no selected — opportunity cost is the highest rejected score
        opportunity_cost = float(max(opp.composite_score for opp in rejected_opportunities))
    else:
        opportunity_cost = 0.0

    # Zero_Day_Rate: % of days with zero_day=True in last 30 days
    zero_day_rate = _compute_zero_day_rate(db, avatar_id, metric_date, window_days=30)

    # --- Persist metrics (upsert) ---

    existing = (
        db.query(PerformanceMetric)
        .filter(
            PerformanceMetric.avatar_id == avatar_id,
            PerformanceMetric.metric_date == metric_date,
        )
        .first()
    )

    if existing:
        existing.return_on_attention = return_on_attention
        existing.risk_adjusted_return = risk_adjusted_return
        existing.portfolio_diversification = portfolio_diversification
        existing.decision_accuracy = decision_accuracy
        existing.opportunity_cost = opportunity_cost
        existing.zero_day_rate = zero_day_rate
        existing.actions_taken = actions_taken
        existing.karma_gained = karma_gained
        stats["updated"] += 1
    else:
        metric = PerformanceMetric(
            avatar_id=avatar_id,
            metric_date=metric_date,
            return_on_attention=return_on_attention,
            risk_adjusted_return=risk_adjusted_return,
            portfolio_diversification=portfolio_diversification,
            decision_accuracy=decision_accuracy,
            opportunity_cost=opportunity_cost,
            zero_day_rate=zero_day_rate,
            actions_taken=actions_taken,
            karma_gained=karma_gained,
        )
        db.add(metric)
        stats["created"] += 1

    db.commit()

    # --- Check alert conditions (14-day window) ---
    _check_alerts(db, avatar_id, metric_date, stats)


def _compute_shannon_entropy(opportunities) -> float:
    """Compute Shannon entropy of subreddit distribution among selected opportunities.

    Returns 0.0 for 0-1 opportunities.
    """
    if len(opportunities) <= 1:
        return 0.0

    sub_counts: dict[str, int] = {}
    for opp in opportunities:
        sub_counts[opp.subreddit] = sub_counts.get(opp.subreddit, 0) + 1

    total = len(opportunities)
    entropy = 0.0

    for count in sub_counts.values():
        if count > 0:
            p = count / total
            entropy -= p * math.log2(p)

    return entropy


def _compute_zero_day_rate(db, avatar_id, metric_date: date, window_days: int = 30) -> float:
    """Compute zero-day rate over last N days.

    Zero_Day_Rate = (count of DecisionRecords with zero_day=True / total days with records) × 100
    """
    from app.models.decision_record import DecisionRecord

    window_start = metric_date - timedelta(days=window_days)

    # Total days with decision records in window
    total_days_with_records = (
        db.query(sa_func.count(DecisionRecord.id))
        .filter(
            DecisionRecord.avatar_id == avatar_id,
            DecisionRecord.decision_date > window_start,
            DecisionRecord.decision_date <= metric_date,
        )
        .scalar()
    ) or 0

    if total_days_with_records == 0:
        return 0.0

    # Days with zero_day=True
    zero_day_count = (
        db.query(sa_func.count(DecisionRecord.id))
        .filter(
            DecisionRecord.avatar_id == avatar_id,
            DecisionRecord.decision_date > window_start,
            DecisionRecord.decision_date <= metric_date,
            DecisionRecord.zero_day == True,  # noqa: E712
        )
        .scalar()
    ) or 0

    return (zero_day_count / total_days_with_records) * 100


def _check_alerts(db, avatar_id, metric_date: date, stats: dict):
    """Check alert conditions over 14-day window and generate alerts if needed.

    Alerts:
    - zero_day_rate > 50% over 14 days → admin dashboard alert
    - decision_accuracy < 50% over 14 days → model review alert
    """
    from app.models.decision_record import DecisionRecord
    from app.models.opportunity import Opportunity

    window_start = metric_date - timedelta(days=14)

    # --- Zero-day rate alert (14-day window) ---
    zero_day_rate_14d = _compute_zero_day_rate(db, avatar_id, metric_date, window_days=14)

    if zero_day_rate_14d > ZERO_DAY_RATE_ALERT_THRESHOLD:
        stats["alerts"] += 1
        logger.warning(
            "ALERT: avatar %s zero_day_rate=%.1f%% over 14 days (threshold: %.0f%%). "
            "Avatar may need strategy reconfiguration or additional subreddit assignments.",
            avatar_id,
            zero_day_rate_14d,
            ZERO_DAY_RATE_ALERT_THRESHOLD,
        )
        _create_activity_event(
            db,
            avatar_id=avatar_id,
            event_type="portfolio_alert",
            message=(
                f"High zero-day rate: {zero_day_rate_14d:.1f}% over 14 days. "
                f"Avatar may need strategy reconfiguration or additional subreddit assignments."
            ),
            metadata={
                "alert_type": "high_zero_day_rate",
                "zero_day_rate": round(zero_day_rate_14d, 1),
                "window_days": 14,
                "threshold": ZERO_DAY_RATE_ALERT_THRESHOLD,
                "avatar_id": str(avatar_id),
                "metric_date": str(metric_date),
            },
        )

    # --- Decision accuracy alert (14-day window) ---
    # Get all selected/executed opportunities with outcome data in last 14 days
    opportunities_14d = (
        db.query(Opportunity)
        .filter(
            Opportunity.avatar_id == avatar_id,
            Opportunity.decision_date > window_start,
            Opportunity.decision_date <= metric_date,
            Opportunity.status.in_(["selected", "executed"]),
            Opportunity.actual_karma.isnot(None),
        )
        .all()
    )

    if opportunities_14d:
        positive_count = sum(1 for opp in opportunities_14d if opp.actual_karma > 0)
        accuracy_14d = (positive_count / len(opportunities_14d)) * 100

        if accuracy_14d < DECISION_ACCURACY_ALERT_THRESHOLD:
            stats["alerts"] += 1
            logger.warning(
                "ALERT: avatar %s decision_accuracy=%.1f%% over 14 days (threshold: %.0f%%). "
                "Model review recommended.",
                avatar_id,
                accuracy_14d,
                DECISION_ACCURACY_ALERT_THRESHOLD,
            )
            _create_activity_event(
                db,
                avatar_id=avatar_id,
                event_type="portfolio_alert",
                message=(
                    f"Low decision accuracy: {accuracy_14d:.1f}% over 14 days. "
                    f"Model review recommended for this avatar."
                ),
                metadata={
                    "alert_type": "low_decision_accuracy",
                    "decision_accuracy": round(accuracy_14d, 1),
                    "window_days": 14,
                    "threshold": DECISION_ACCURACY_ALERT_THRESHOLD,
                    "total_actions": len(opportunities_14d),
                    "positive_actions": positive_count,
                    "avatar_id": str(avatar_id),
                    "metric_date": str(metric_date),
                },
            )


def _create_activity_event(db, avatar_id, event_type: str, message: str, metadata: dict):
    """Create an ActivityEvent for admin dashboard visibility."""
    from app.models.activity_event import ActivityEvent

    event = ActivityEvent(
        event_type=event_type,
        message=message,
        event_metadata=metadata,
    )
    db.add(event)
    db.commit()


@shared_task(name="archive_old_decision_records")
def archive_old_decision_records():
    """Archive decision records older than 90 days.

    Scheduled at 01:30 daily. Prunes the full opportunity records (Opportunity rows)
    older than 90 days while keeping DecisionRecord metadata intact.

    Per Requirement 7.6: retain Decision_Records for 90 days, after which
    records older than 90 days are archived (metadata retained, full opportunity list pruned).
    """
    from app.models.decision_record import DecisionRecord
    from app.models.opportunity import Opportunity

    db = SessionLocal()
    try:
        cutoff_date = date.today() - timedelta(days=ARCHIVAL_RETENTION_DAYS)

        # Prune Opportunity records older than retention period
        # Keep DecisionRecord metadata intact — only remove the detailed opportunity rows
        deleted_count = (
            db.query(Opportunity)
            .filter(Opportunity.decision_date < cutoff_date)
            .delete(synchronize_session=False)
        )

        db.commit()

        logger.info(
            "archive_old_decision_records complete: pruned %d opportunity records "
            "older than %s (retention: %d days)",
            deleted_count,
            cutoff_date.isoformat(),
            ARCHIVAL_RETENTION_DAYS,
        )

        return {
            "pruned_opportunities": deleted_count,
            "cutoff_date": cutoff_date.isoformat(),
            "retention_days": ARCHIVAL_RETENTION_DAYS,
        }

    except Exception as e:
        db.rollback()
        logger.error("archive_old_decision_records failed: %s", e, exc_info=True)
        return {"status": "error", "error": str(e)}
    finally:
        db.close()
