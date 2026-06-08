"""System Heartbeat — periodic health pulse logged every minute.

Provides continuous visibility into system state even during idle periods.
Logs connectivity status for all critical dependencies (DB, Redis, Reddit API)
and key operational metrics.

Designed to be resilient: never raises, always logs something.
"""

from app.logging_config import get_logger
import time
from datetime import datetime, timezone

import redis
import sqlalchemy.exc

from app.tasks.worker import celery_app

logger = get_logger(__name__)

# Heartbeat log prefix for easy grep/filtering
_PREFIX = "HEARTBEAT"


def _check_redis(redis_url: str) -> dict:
    """Check Redis connectivity and basic info."""
    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=3)
        start = time.time()
        client.ping()
        latency_ms = int((time.time() - start) * 1000)
        info = client.info(section="memory")
        used_mb = round(info.get("used_memory", 0) / (1024 * 1024), 1)
        client.close()
        return {"status": "ok", "latency_ms": latency_ms, "memory_mb": used_mb}
    except redis.ConnectionError as e:
        return {"status": "unreachable", "error": str(e)[:100]}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


def _check_database(database_url: str) -> dict:
    """Check PostgreSQL connectivity."""
    from sqlalchemy import create_engine, text

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        start = time.time()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency_ms = int((time.time() - start) * 1000)
        engine.dispose()
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:100]}


def _check_celery_workers() -> dict:
    """Check if Celery workers are responding."""
    try:
        inspector = celery_app.control.inspect(timeout=3)
        active = inspector.active()
        if active is None:
            return {"status": "no_workers", "count": 0}
        worker_count = len(active)
        total_tasks = sum(len(tasks) for tasks in active.values())
        return {"status": "ok", "count": worker_count, "active_tasks": total_tasks}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


def _get_queue_depth(redis_url: str) -> dict:
    """Check Celery queue depth in Redis."""
    try:
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_timeout=3)
        # Default Celery queue name
        depth = client.llen("celery")
        client.close()
        return {"queue": "celery", "depth": depth}
    except Exception:
        return {"queue": "celery", "depth": -1}


def _get_scrape_stats() -> dict:
    """Get quick scrape queue stats from DB."""
    try:
        from app.database import SessionLocal
        from app.models.subreddit import ClientSubreddit
        from app.models.client import Client
        from datetime import timedelta

        db = SessionLocal()
        try:
            now = datetime.now(timezone.utc)
            stale_threshold = now - timedelta(hours=12)

            total_active = (
                db.query(ClientSubreddit)
                .join(Client, Client.id == ClientSubreddit.client_id)
                .filter(
                    ClientSubreddit.is_active.is_(True),
                    Client.is_active.is_(True),
                )
                .count()
            )

            stale_count = (
                db.query(ClientSubreddit)
                .join(Client, Client.id == ClientSubreddit.client_id)
                .filter(
                    ClientSubreddit.is_active.is_(True),
                    Client.is_active.is_(True),
                )
                .filter(
                    (ClientSubreddit.last_scraped_at < stale_threshold)
                    | (ClientSubreddit.last_scraped_at.is_(None))
                )
                .count()
            )

            return {"active_subs": total_active, "stale_subs": stale_count}
        finally:
            db.close()
    except Exception:
        return {"active_subs": -1, "stale_subs": -1}


@celery_app.task(name="system_heartbeat", ignore_result=True)
def system_heartbeat() -> dict:
    """Log system health status. Runs every 60s via Beat.

    Never raises — always produces a log line regardless of failures.
    """
    from app.config import get_settings

    settings = get_settings()
    results = {}

    try:
        results["redis"] = _check_redis(settings.redis_url)
        results["database"] = _check_database(settings.database_url)
        results["workers"] = _check_celery_workers()
        results["queue"] = _get_queue_depth(settings.redis_url)
        results["scrape"] = _get_scrape_stats()

        # Determine overall status
        statuses = [
            results["redis"]["status"],
            results["database"]["status"],
            results["workers"]["status"],
        ]
        if all(s == "ok" for s in statuses):
            overall = "HEALTHY"
        elif any(s in ("unreachable", "no_workers") for s in statuses):
            overall = "DEGRADED"
        else:
            overall = "WARNING"

        # Single structured log line
        logger.info(
            "%s | status=%s | redis=%s (latency=%sms, mem=%sMB) | "
            "db=%s (latency=%sms) | workers=%s (count=%s, active_tasks=%s) | "
            "queue_depth=%s | scrape: active=%s stale=%s",
            _PREFIX,
            overall,
            results["redis"].get("status"),
            results["redis"].get("latency_ms", "?"),
            results["redis"].get("memory_mb", "?"),
            results["database"].get("status"),
            results["database"].get("latency_ms", "?"),
            results["workers"].get("status"),
            results["workers"].get("count", "?"),
            results["workers"].get("active_tasks", "?"),
            results["queue"].get("depth", "?"),
            results["scrape"].get("active_subs", "?"),
            results["scrape"].get("stale_subs", "?"),
        )

        # Log warnings for degraded components
        if results["redis"]["status"] != "ok":
            logger.warning(
                "%s | REDIS_DOWN | %s", _PREFIX, results["redis"].get("error", "unknown")
            )
        if results["database"]["status"] != "ok":
            logger.warning(
                "%s | DB_DOWN | %s", _PREFIX, results["database"].get("error", "unknown")
            )
        if results["workers"]["status"] != "ok":
            logger.warning(
                "%s | NO_WORKERS | %s", _PREFIX, results["workers"].get("error", "no workers responding")
            )

    except Exception as e:
        # Absolute fallback — heartbeat must never crash
        overall = "ERROR"
        logger.error("%s | status=ERROR | exception=%s", _PREFIX, str(e)[:200])
        results = {"error": str(e)[:200]}

    return {"status": overall, "checks": results}
