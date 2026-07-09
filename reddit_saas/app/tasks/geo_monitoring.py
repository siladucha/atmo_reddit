"""GEO/AEO monitoring scheduled tasks.

Runs GEO batch for all clients with geo_monitoring_enabled=True.
Daily smoothing: each day runs ~1/7 of prompts (deterministic via UUID.int % 7).
"""

from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="run_geo_monitoring_daily", bind=True, max_retries=1)
def run_geo_monitoring_daily(self):
    """Run GEO monitoring for today's day group only.

    Each prompt is deterministically assigned to a weekday via prompt.id.int % 7.
    Monday=0, Tuesday=1, ..., Sunday=6.
    Spreads GEO cost evenly across the week instead of Tue+Fri spikes.
    """
    from datetime import datetime, timezone

    from app.database import SessionLocal
    from app.models.client import Client
    from app.models.geo_prompt import GeoPrompt
    from app.services.geo_query_runner import run_geo_batch_for_client

    db = SessionLocal()
    try:
        # Current weekday: Monday=0 ... Sunday=6
        weekday_index = datetime.now(timezone.utc).weekday()

        clients = (
            db.query(Client)
            .filter(Client.is_active == True, Client.geo_monitoring_enabled == True)
            .all()
        )

        if not clients:
            logger.info("GEO daily: No clients with geo_monitoring_enabled, skipping")
            return {"status": "skipped", "reason": "no_clients"}

        results = []
        for client in clients:
            try:
                # Load active prompts for this client
                all_prompts = (
                    db.query(GeoPrompt)
                    .filter(GeoPrompt.client_id == client.id, GeoPrompt.is_active == True)
                    .all()
                )

                # Filter to today's day group (stable: UUID.int % 7)
                today_prompts = [p for p in all_prompts if p.id.int % 7 == weekday_index]

                if not today_prompts:
                    results.append({
                        "client": client.client_name,
                        "status": "skipped",
                        "reason": "no_prompts_today",
                    })
                    continue

                logger.info(
                    "GEO daily: Running %d/%d prompts for %s (day_group=%d)",
                    len(today_prompts), len(all_prompts),
                    client.brand_name or client.client_name, weekday_index,
                )

                prompt_ids = [p.id for p in today_prompts]
                batch = run_geo_batch_for_client(
                    db=db,
                    client=client,
                    triggered_by="scheduler",
                    prompts_override=prompt_ids,
                )

                if batch:
                    results.append({
                        "client": client.client_name,
                        "status": batch.status,
                        "successful": batch.successful_queries,
                        "total": batch.total_queries,
                        "prompts_today": len(today_prompts),
                    })
                else:
                    results.append({
                        "client": client.client_name,
                        "status": "skipped",
                        "reason": "batch_returned_none",
                    })

            except Exception as e:
                logger.error("GEO daily: Failed for client %s: %s", client.client_name, e)
                results.append({
                    "client": client.client_name,
                    "status": "error",
                    "error": str(e)[:200],
                })

        logger.info(
            "GEO daily: Completed for %d clients (day_group=%d) — %s",
            len(results), weekday_index, results,
        )
        return {"status": "done", "day_group": weekday_index, "clients": len(results), "results": results}

    except Exception as e:
        logger.error("GEO daily: Task failed: %s", e)
        raise
    finally:
        db.close()


@celery_app.task(name="run_geo_monitoring_all_clients", bind=True, max_retries=1)
def run_geo_monitoring_all_clients(self):
    """Run GEO monitoring batch for ALL prompts for all enabled clients.

    Used for manual triggers (admin "Run Now" button). Not scheduled.
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
