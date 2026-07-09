"""Weekly intelligence report generation tasks.

Generates and publishes intelligence reports for eligible clients.
Scheduled: Monday 08:00 (after weekend pipeline, before Tue GEO batch).
"""

from datetime import datetime, timezone

from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="generate_weekly_reports_all_clients", bind=True, max_retries=0)
def generate_weekly_reports_all_clients(self):
    """Generate intelligence reports for all eligible clients.

    Eligibility:
    - client.is_active = True
    - client has geo_monitoring_enabled = True
    - client has at least 1 completed/partial GeoExecutionBatch

    Flow:
    1. Query all eligible clients
    2. For each client: compose_full_report(db, client_id)
    3. Publish report (status = 'published', published_at = now)
    4. Optionally send notification to client
    """
    from app.database import SessionLocal
    from app.models.client import Client
    from app.models.geo_execution import GeoExecutionBatch
    from app.services.forecast.report_composer import ReportComposer

    db = SessionLocal()
    try:
        # Find eligible clients: active + geo_monitoring_enabled + ≥1 completed batch
        eligible_client_ids = (
            db.query(Client.id)
            .filter(
                Client.is_active == True,
                Client.geo_monitoring_enabled == True,
            )
            .join(
                GeoExecutionBatch,
                GeoExecutionBatch.client_id == Client.id,
            )
            .filter(
                GeoExecutionBatch.status.in_(["completed", "partial"]),
            )
            .distinct()
            .all()
        )

        client_ids = [row[0] for row in eligible_client_ids]

        if not client_ids:
            logger.info(
                "Weekly reports: No eligible clients found (need geo_monitoring_enabled + completed batch)"
            )
            return {"status": "skipped", "reason": "no_eligible_clients"}

        logger.info("Weekly reports: Generating for %d eligible clients", len(client_ids))

        composer = ReportComposer()
        results = []

        for client_id in client_ids:
            try:
                # Generate full 5-layer report
                report = composer.compose_full_report(db, client_id)

                # Publish immediately
                report.status = "published"
                report.published_at = datetime.now(timezone.utc)

                db.commit()

                # Send notification (fire-and-forget)
                _notify_report_published(client_id, report.report_period)

                # Send weekly visibility digest email to client
                _send_visibility_digest(client_id)

                results.append({
                    "client_id": str(client_id),
                    "status": "published",
                    "period": report.report_period,
                    "version": report.report_version,
                })

                logger.info(
                    "Weekly reports: Published report for client %s (period %s, v%d)",
                    client_id,
                    report.report_period,
                    report.report_version,
                )

            except Exception as e:
                db.rollback()
                logger.error(
                    "Weekly reports: Failed for client %s: %s",
                    client_id,
                    e,
                    exc_info=True,
                )
                results.append({
                    "client_id": str(client_id),
                    "status": "error",
                    "error": str(e)[:200],
                })

        logger.info(
            "Weekly reports: Completed — %d clients processed, %d published, %d errors",
            len(results),
            sum(1 for r in results if r["status"] == "published"),
            sum(1 for r in results if r["status"] == "error"),
        )

        return {
            "status": "done",
            "clients_processed": len(results),
            "published": sum(1 for r in results if r["status"] == "published"),
            "errors": sum(1 for r in results if r["status"] == "error"),
            "results": results,
        }

    except Exception as e:
        db.rollback()
        logger.error("Weekly reports: Task failed: %s", e, exc_info=True)
        raise
    finally:
        db.close()


@celery_app.task(name="generate_intelligence_report_for_client", bind=True, max_retries=1)
def generate_intelligence_report_for_client(self, client_id: str):
    """Generate intelligence report for a specific client (manual trigger).

    Args:
        client_id: UUID string of the client.
    """
    import uuid as uuid_mod

    from app.database import SessionLocal
    from app.models.client import Client
    from app.services.forecast.report_composer import ReportComposer

    db = SessionLocal()
    try:
        client_uuid = uuid_mod.UUID(client_id)

        # Verify client exists and is active
        client = db.query(Client).filter(Client.id == client_uuid).first()
        if not client:
            logger.warning("Generate report: Client %s not found", client_id)
            return {"status": "error", "reason": "client_not_found"}

        if not client.is_active:
            logger.warning("Generate report: Client %s is not active", client_id)
            return {"status": "error", "reason": "client_inactive"}

        # Generate full 5-layer report
        composer = ReportComposer()
        report = composer.compose_full_report(db, client_uuid)

        # Publish
        report.status = "published"
        report.published_at = datetime.now(timezone.utc)

        db.commit()

        # Send notification
        _notify_report_published(client_uuid, report.report_period)

        logger.info(
            "Generate report: Published for client %s (period %s, v%d)",
            client_id,
            report.report_period,
            report.report_version,
        )

        return {
            "status": "published",
            "client_id": client_id,
            "report_id": str(report.id),
            "period": report.report_period,
            "version": report.report_version,
        }

    except Exception as e:
        db.rollback()
        logger.error(
            "Generate report: Failed for client %s: %s",
            client_id,
            e,
            exc_info=True,
        )
        raise self.retry(exc=e, countdown=120)
    finally:
        db.close()


def _notify_report_published(client_id, report_period: str):
    """Send notification to client about published report. Fire-and-forget."""
    try:
        from app.services.task_notifications import _notify

        _notify(
            client_id,
            type="info",
            title="Weekly Intelligence Report published",
            body=f"Your visibility report for {report_period} is ready.",
            link=f"/clients/{client_id}/report/weekly",
        )
    except Exception as e:
        logger.debug("Report notification failed (non-critical): %s", e)


def _send_visibility_digest(client_id):
    """Send weekly visibility digest email to client. Fire-and-forget."""
    try:
        from app.services.client_emails import send_weekly_visibility_digest

        send_weekly_visibility_digest(client_id)
    except Exception as e:
        logger.debug("Visibility digest email failed (non-critical): %s", e)
