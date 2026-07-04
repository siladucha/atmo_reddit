"""GEO/AEO monitoring scheduled tasks.

Runs GEO batch for all clients with geo_monitoring_enabled=True.
"""

from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="run_geo_monitoring_all_clients", bind=True, max_retries=1)
def run_geo_monitoring_all_clients(self):
    """Run GEO monitoring batch for all clients that have it enabled.

    Scheduled every 3 days. Skips clients without active prompts.
    """
    from app.database import SessionLocal
    from app.models.client import Client
    from app.services.geo_query_runner import run_geo_batch_for_client

    db = SessionLocal()
    try:
        # Find all clients with GEO monitoring enabled
        clients = (
            db.query(Client)
            .filter(
                Client.is_active == True,
                Client.geo_monitoring_enabled == True,
            )
            .all()
        )

        if not clients:
            logger.info("GEO scheduled: No clients with geo_monitoring_enabled, skipping")
            return {"status": "skipped", "reason": "no_clients"}

        results = []
        for client in clients:
            try:
                logger.info("GEO scheduled: Running batch for %s", client.brand_name or client.client_name)
                batch = run_geo_batch_for_client(
                    db=db,
                    client=client,
                    triggered_by="scheduler",
                )
                if batch:
                    results.append({
                        "client": client.client_name,
                        "status": batch.status,
                        "successful": batch.successful_queries,
                        "total": batch.total_queries,
                    })
                else:
                    results.append({
                        "client": client.client_name,
                        "status": "skipped",
                        "reason": "no_prompts_or_disabled",
                    })
            except Exception as e:
                logger.error("GEO scheduled: Failed for client %s: %s", client.client_name, e)
                results.append({
                    "client": client.client_name,
                    "status": "error",
                    "error": str(e)[:200],
                })

        logger.info("GEO scheduled: Completed for %d clients — %s", len(results), results)
        return {"status": "done", "clients": len(results), "results": results}

    except Exception as e:
        logger.error("GEO scheduled: Task failed: %s", e)
        raise
    finally:
        db.close()
