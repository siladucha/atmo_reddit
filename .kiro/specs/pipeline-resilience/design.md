# Technical Design — Pipeline Resilience & Hardening

## Overview

This design adds a resilience layer to the RAMP system covering 13 requirements: emergency kill switch, freeze circuit breaker, approved-by provenance, Beat catch-up prevention, operator alerts, external health endpoint, heartbeat watcher, task dedup decorator, structured error classification, feedback loop observability, worker memory protection, Redis health check, and log persistence. All components are additive — they wrap or extend existing services without replacing them.

## Architecture

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        RESILIENCE LAYER                                │
│                                                                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐                │
│  │ Kill Switch │  │ Circuit Brkr │  │ Error Classif │                │
│  │  (Redis)    │  │ (in-memory)  │  │   (utility)   │                │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘                │
│         │                 │                   │                        │
│  ┌──────┴──────┐  ┌──────┴───────┐  ┌───────┴───────┐                │
│  │ Task Dedup  │  │ Operator     │  │ Feedback Loop │                │
│  │ (decorator) │  │ Alerts       │  │ Observability │                │
│  └─────────────┘  └──────────────┘  └───────────────┘                │
│                                                                        │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐                │
│  │ /health/ext │  │ Heartbeat    │  │ Redis Health  │                │
│  │ (endpoint)  │  │ Watcher      │  │ (task)        │                │
│  └─────────────┘  └──────────────┘  └───────────────┘                │
└──────────────────────────────────────────────────────────────────────┘
         │                    │                     │
         ▼                    ▼                     ▼
┌─────────────────────────────────────────────────────────────────────┐
│  EXISTING INFRASTRUCTURE: Celery Workers + Redis Broker + PostgreSQL │
└─────────────────────────────────────────────────────────────────────┘
```

All resilience components are additive — they wrap or extend existing services
without replacing them. The kill switch and task dedup use Redis (same instance
as broker). The circuit breaker uses in-memory counters (per batch run). Operator
alerts use Redis PubSub + optional external channels.


---

## Components and Interfaces

### 2.1 Kill Switch Utility — `app/services/kill_switch.py`

**Purpose:** Single-line check at the top of every Celery task to halt execution
when an emergency stop is active.

**Redis Key Format:**
- Global: `ramp:kill:all` → value is reason string (e.g., "incident: Reddit API 500s")
- Per-group: `ramp:kill:{group}` → group ∈ {scraping, scoring, generation, posting, epg, email, health}

**Function Signatures:**

```python
from __future__ import annotations
import redis
from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# Task group mapping — each task declares its group
TASK_GROUPS: dict[str, str] = {
    "queue_tick": "scraping",
    "scrape_subreddit": "scraping",
    "run_full_pipeline_all_clients": "scoring",
    "generate_comments": "generation",
    "execute_pending_posts": "posting",
    "build_and_generate_epg_all_avatars": "epg",
    "dispatch_due_email_tasks": "email",
    "health_check_all_avatars": "health",
    # ... more mappings
}


def is_killed(task_name: str | None = None) -> tuple[bool, str]:
    """Check if the system or task group is killed.

    Returns (is_killed: bool, reason: str).
    Fail-open: if Redis unreachable, returns (False, "").

    Usage in any Celery task:
        killed, reason = is_killed("my_task_name")
        if killed:
            logger.warning("KILL_SWITCH | task=%s reason=%s", self.name, reason)
            return
    """
    try:
        settings = get_settings()
        r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)

        # Check global kill first
        global_reason = r.get("ramp:kill:all")
        if global_reason:
            return True, f"global: {global_reason}"

        # Check group kill
        if task_name:
            group = TASK_GROUPS.get(task_name)
            if group:
                group_reason = r.get(f"ramp:kill:{group}")
                if group_reason:
                    return True, f"group({group}): {group_reason}"

        return False, ""

    except (redis.ConnectionError, redis.TimeoutError, Exception) as e:
        # Fail-open: proceed with execution
        logger.warning("KILL_SWITCH_CHECK_FAILED | error=%s", str(e)[:100])
        return False, ""


def set_kill_switch(
    key: str = "ramp:kill:all",
    reason: str = "manual",
    ttl: int | None = None,
) -> bool:
    """Activate a kill switch. Returns True on success."""
    try:
        settings = get_settings()
        r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        if ttl:
            r.set(key, reason, ex=ttl)
        else:
            r.set(key, reason)
        logger.warning("KILL_SWITCH_SET | key=%s reason=%s ttl=%s", key, reason, ttl)
        return True
    except Exception as e:
        logger.error("KILL_SWITCH_SET_FAILED | key=%s error=%s", key, str(e)[:100])
        return False


def clear_kill_switch(key: str = "ramp:kill:all") -> bool:
    """Remove a kill switch. Returns True on success."""
    try:
        settings = get_settings()
        r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        r.delete(key)
        logger.info("KILL_SWITCH_CLEARED | key=%s", key)
        return True
    except Exception as e:
        logger.error("KILL_SWITCH_CLEAR_FAILED | key=%s error=%s", key, str(e)[:100])
        return False


def get_active_kill_switches() -> dict[str, str]:
    """Return all active kill switches. For admin UI display."""
    try:
        settings = get_settings()
        r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        keys = ["ramp:kill:all"] + [f"ramp:kill:{g}" for g in
                ("scraping", "scoring", "generation", "posting", "epg", "email", "health")]
        result = {}
        for key in keys:
            val = r.get(key)
            if val:
                result[key] = val
        return result
    except Exception:
        return {}
```

**Admin Route (in `routes/admin.py`):**

```python
@router.post("/admin/settings/kill-switch")
async def toggle_kill_switch(
    action: str = Form(...),  # "activate" or "deactivate"
    scope: str = Form("all"),  # "all" or group name
    reason: str = Form("manual operator action"),
    current_user=Depends(require_superuser),
):
    key = f"ramp:kill:{scope}"
    if action == "activate":
        set_kill_switch(key, reason)
    else:
        clear_kill_switch(key)
    return RedirectResponse("/admin/settings", status_code=303)
```


---

### 2.2 Freeze Circuit Breaker — in `health_checker.py`

**Purpose:** Halt health check batch processing when too many avatars freeze in
a single run, preventing cascade freeze from Reddit API instability.

**Design:** In-memory counter scoped to a single `run_health_check_batch()` call.
No persistence between runs.

**Integration Point:** Inside the `for i, avatar in enumerate(eligible_avatars)` loop
in `run_health_check_batch()`.

```python
# Added to run_health_check_batch():

from app.services.settings import get_setting_int

def run_health_check_batch(db: Session) -> dict:
    # ... existing setup ...

    # Circuit breaker state (reset per batch)
    freeze_threshold = get_setting_int(db, "health_check_freeze_circuit_breaker_threshold", default=5)
    new_freeze_count = 0
    frozen_usernames: list[str] = []

    for i, avatar in enumerate(eligible_avatars):
        try:
            # Snapshot frozen state BEFORE check
            was_frozen_before = avatar.is_frozen

            result = check_avatar_health(db, avatar)
            checked_count += 1

            if result.status_changed:
                changed_count += 1

            # Circuit breaker: detect NEW freeze
            if not was_frozen_before and avatar.is_frozen:
                new_freeze_count += 1
                frozen_usernames.append(avatar.reddit_username)

                # Check threshold
                if new_freeze_count >= freeze_threshold:
                    logger.error(
                        "FREEZE_CIRCUIT_BREAKER_TRIGGERED | freeze_count=%d "
                        "threshold=%d batch_size=%d frozen_avatars=%s",
                        new_freeze_count, freeze_threshold, batch_size,
                        ",".join(frozen_usernames),
                    )
                    # Emit operator alert
                    from app.services.operator_alerts import emit_alert
                    emit_alert(
                        severity="critical",
                        title="Freeze Circuit Breaker Triggered",
                        message=(
                            f"{new_freeze_count} avatars frozen in single batch. "
                            f"Halting remaining {batch_size - i - 1} checks. "
                            f"Investigate Reddit API stability."
                        ),
                        metadata={"frozen_usernames": frozen_usernames},
                    )
                    # Record ActivityEvent
                    from app.models.activity_event import ActivityEvent
                    db.add(ActivityEvent(
                        event_type="freeze_circuit_breaker_triggered",
                        message=f"Circuit breaker: {new_freeze_count} freezes",
                        event_metadata={
                            "freeze_count": new_freeze_count,
                            "threshold": freeze_threshold,
                            "frozen_usernames": frozen_usernames,
                            "remaining_unchecked": batch_size - i - 1,
                        },
                    ))
                    db.commit()
                    break  # HALT batch processing

        except Exception as e:
            error_count += 1
            # ... existing error handling ...
```


---

### 2.3 Approved-By Provenance Field

**Database Change (Alembic Migration):**

```python
# alembic/versions/res01_approved_by_field.py
"""Add approved_by field to comment_drafts."""

from alembic import op
import sqlalchemy as sa

revision = "res01"
down_revision = "<previous_head>"


def upgrade():
    op.add_column(
        "comment_drafts",
        sa.Column("approved_by", sa.String(100), nullable=True),
    )


def downgrade():
    op.drop_column("comment_drafts", "approved_by")
```

**Model Change (`app/models/comment_draft.py`):**

```python
class CommentDraft(Base):
    # ... existing fields ...
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
```

**EPG Executor Integration (`app/services/epg_executor.py`):**

In the auto-approve path where `_should_auto_approve()` returns True:

```python
if _should_auto_approve(db, slot.client_id, slot.avatar_id):
    slot.status = "approved"
    draft.status = "approved"
    draft.approved_by = "autopilot"  # <-- NEW
    # ... rest of existing logic
```

**Review Routes Integration (`app/routes/review.py`):**

```python
@router.post("/api/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    draft = db.query(CommentDraft).get(draft_id)
    draft.status = "approved"
    draft.approved_by = current_user.email  # <-- NEW
    # ... existing logic
```

---

### 2.4 Beat Catch-Up Prevention — `entrypoint.sh` Modification

**Change:** Add schedule file cleanup to the celery-beat container command.

**Modified `docker-compose.yml` celery-beat command:**

```yaml
celery-beat:
  image: reddit-saas-app:latest
  command: >
    sh -c "
      until getent hosts db && getent hosts redis; do echo 'waiting for docker dns...'; sleep 2; done;
      until nc -z db 5432; do echo 'waiting for postgres...'; sleep 2; done;
      until nc -z redis 6379; do echo 'waiting for redis...'; sleep 2; done;
      echo 'Checking for stale celerybeat-schedule...';
      if [ -f /app/celerybeat-schedule ]; then
        rm -f /app/celerybeat-schedule && echo 'INFO: Stale celerybeat-schedule deleted';
      else
        echo 'INFO: No stale celerybeat-schedule found';
      fi;
      celery -A app.tasks.worker beat --loglevel=info
    "
```

**Key points:**
- No persistent volume for celerybeat-schedule (already satisfied — no volume mount exists)
- Deletion happens BEFORE beat process starts
- If deletion fails, beat still starts (non-blocking `rm -f`)
- Logs whether file was found and deleted


---

### 2.5 Operator Alert Service — `app/services/operator_alerts.py`

**Purpose:** Unified alert delivery system with rate limiting, deduplication,
and multi-channel support.

```python
"""Operator Alert Service — unified alert delivery with rate limiting.

Channels: Redis PubSub (for admin SSE), Telegram, Email.
Rate limit: 20 alerts/hour max. Dedup: same type+entity > 3 times/hour suppressed.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

import redis

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class OperatorAlert:
    severity: AlertSeverity
    title: str
    message: str
    alert_type: str = ""        # e.g., "freeze_circuit_breaker", "avatar_demoted"
    entity_id: str = ""         # e.g., avatar UUID
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# Rate limiting state (in Redis)
_RATE_LIMIT_KEY = "ramp:alerts:rate_limit"
_RATE_LIMIT_WINDOW = 3600  # 1 hour
_RATE_LIMIT_MAX = 20

# Dedup state
_DEDUP_KEY_PREFIX = "ramp:alerts:dedup"
_DEDUP_MAX_PER_TYPE = 3


def emit_alert(
    severity: str,
    title: str,
    message: str,
    alert_type: str = "",
    entity_id: str = "",
    metadata: dict | None = None,
) -> bool:
    """Emit an operator alert. Returns True if delivered, False if suppressed.

    Rate limited to 20/hour. Dedup: same alert_type+entity > 3/hour suppressed.
    """
    alert = OperatorAlert(
        severity=AlertSeverity(severity),
        title=title,
        message=message,
        alert_type=alert_type,
        entity_id=entity_id,
        metadata=metadata or {},
    )

    try:
        settings = get_settings()
        r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)

        # Check rate limit
        now = time.time()
        r.zremrangebyscore(_RATE_LIMIT_KEY, 0, now - _RATE_LIMIT_WINDOW)
        current_count = r.zcard(_RATE_LIMIT_KEY)

        if current_count >= _RATE_LIMIT_MAX:
            logger.warning("ALERT_RATE_LIMITED | title=%s count=%d", title, current_count)
            # Queue summary alert for next window
            r.set("ramp:alerts:suppressed_count",
                   int(r.get("ramp:alerts:suppressed_count") or 0) + 1, ex=3600)
            return False

        # Check dedup
        if alert_type and entity_id:
            dedup_key = f"{_DEDUP_KEY_PREFIX}:{alert_type}:{entity_id}"
            dedup_count = r.incr(dedup_key)
            if dedup_count == 1:
                r.expire(dedup_key, _RATE_LIMIT_WINDOW)
            if dedup_count > _DEDUP_MAX_PER_TYPE:
                logger.info("ALERT_DEDUPED | type=%s entity=%s count=%d",
                           alert_type, entity_id, dedup_count)
                return False

        # Record in rate limit window
        r.zadd(_RATE_LIMIT_KEY, {f"{alert.timestamp}:{title}": now})
        r.expire(_RATE_LIMIT_KEY, _RATE_LIMIT_WINDOW)

        # Deliver to channels
        _deliver_redis_pubsub(r, alert)
        _deliver_telegram(alert)

        logger.info("ALERT_EMITTED | severity=%s title=%s", severity, title)
        return True

    except Exception as e:
        logger.error("ALERT_EMIT_FAILED | title=%s error=%s", title, str(e)[:100])
        return False


def _deliver_redis_pubsub(r: redis.Redis, alert: OperatorAlert) -> None:
    """Publish alert to Redis PubSub for admin SSE consumption."""
    payload = json.dumps({
        "type": "operator_alert",
        "severity": alert.severity.value,
        "title": alert.title,
        "message": alert.message,
        "alert_type": alert.alert_type,
        "entity_id": alert.entity_id,
        "metadata": alert.metadata,
        "timestamp": alert.timestamp,
    })
    r.publish("ramp:operator_alerts", payload)


def _deliver_telegram(alert: OperatorAlert) -> None:
    """Send alert to Telegram bot (if configured)."""
    try:
        from app.database import SessionLocal
        from app.services.settings import get_setting

        db = SessionLocal()
        try:
            channels_json = get_setting(db, "operator_alert_channels")
            channels = json.loads(channels_json) if channels_json else ["redis_pubsub"]

            if "telegram" not in channels:
                return

            bot_token = get_setting(db, "telegram_bot_token")
            chat_id = get_setting(db, "telegram_chat_id")

            if not bot_token or not chat_id:
                return

            import httpx
            emoji = {"critical": "🚨", "high": "⚠️", "medium": "📢", "low": "ℹ️"}
            text = f"{emoji.get(alert.severity.value, '📢')} *{alert.title}*\n{alert.message}"

            httpx.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                timeout=5,
            )
        finally:
            db.close()
    except Exception as e:
        logger.warning("TELEGRAM_ALERT_FAILED | error=%s", str(e)[:100])
```

**New System Settings:**

| Key | Default | Description |
|-----|---------|-------------|
| `operator_alert_channels` | `["redis_pubsub"]` | JSON array of channels |
| `telegram_bot_token` | `""` | Telegram bot token |
| `telegram_chat_id` | `""` | Telegram chat ID for alerts |
| `operator_alert_email` | `""` | Email for alert delivery |

---

### 2.6 External Health Endpoint — `/health/external`

**Purpose:** Unauthenticated endpoint for external monitoring services (UptimeRobot,
Pingdom, etc.) to detect system outages.

**Route (`app/routes/health.py` or added to `app/main.py`):**

```python
import time
from datetime import datetime, timezone
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/health/external")
async def health_external():
    """External health check — no auth required.

    Returns system status for monitoring services.
    Timeout: individual checks capped at 2s, total response < 3s.
    """
    start = time.time()
    checks = {}
    degraded_components = 0

    # Redis check
    checks["redis"] = _check_redis_health()
    if checks["redis"]["status"] != "ok":
        degraded_components += 1

    # DB check
    checks["db"] = _check_db_health()
    if checks["db"]["status"] != "ok":
        degraded_components += 1

    # Worker check (via heartbeat age)
    checks["workers"] = _check_worker_health()
    if checks["workers"]["status"] != "ok":
        degraded_components += 1

    # Determine overall status
    if degraded_components == 0:
        status = "healthy"
        http_code = 200
    elif degraded_components == 1:
        status = "degraded"
        http_code = 200
    else:
        status = "critical"
        http_code = 503

    from app.version import __version__

    response = {
        "status": status,
        "version": __version__,
        "uptime_seconds": _get_uptime_seconds(),
        "last_heartbeat_age_seconds": checks["workers"].get("heartbeat_age_seconds"),
        "worker_status": checks["workers"]["status"],
        "redis_status": checks["redis"]["status"],
        "db_status": checks["db"]["status"],
        "checks": checks,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    return JSONResponse(content=response, status_code=http_code)


def _check_redis_health() -> dict:
    """Redis ping + latency (2s timeout)."""
    try:
        import redis as _redis
        settings = get_settings()
        r = _redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        start = time.time()
        r.ping()
        latency_ms = int((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:100]}


def _check_db_health() -> dict:
    """PostgreSQL SELECT 1 (2s timeout)."""
    try:
        from app.database import SessionLocal
        from sqlalchemy import text
        start = time.time()
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            latency_ms = int((time.time() - start) * 1000)
            return {"status": "ok", "latency_ms": latency_ms}
        finally:
            db.close()
    except Exception as e:
        return {"status": "unreachable", "error": str(e)[:100]}


def _check_worker_health() -> dict:
    """Check heartbeat age from Redis key ramp:heartbeat:last_at."""
    try:
        import redis as _redis
        settings = get_settings()
        r = _redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        last_at = r.get("ramp:heartbeat:last_at")
        if not last_at:
            return {"status": "unknown", "heartbeat_age_seconds": None}
        last_dt = datetime.fromisoformat(last_at)
        age_seconds = (datetime.now(timezone.utc) - last_dt).total_seconds()
        if age_seconds > 300:
            return {"status": "stale", "heartbeat_age_seconds": int(age_seconds)}
        return {"status": "ok", "heartbeat_age_seconds": int(age_seconds)}
    except Exception as e:
        return {"status": "error", "heartbeat_age_seconds": None, "error": str(e)[:100]}


# Process start time for uptime calculation
_PROCESS_START = time.time()

def _get_uptime_seconds() -> int:
    return int(time.time() - _PROCESS_START)
```

---

### 2.7 Heartbeat Watcher — `scripts/heartbeat_watcher.py`

**Purpose:** Independent process that monitors the heartbeat Redis key and attempts
worker recovery if stale. Runs as a separate Docker container.

```python
#!/usr/bin/env python3
"""Heartbeat Watcher — monitors worker health, triggers recovery.

Runs as independent process (Docker container).
Checks ramp:heartbeat:last_at every 60s.
If stale > 5 min: alert + attempt docker restart.
"""

import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
STALE_THRESHOLD = int(os.environ.get("HEARTBEAT_STALE_THRESHOLD_SECONDS", "300"))
CHECK_INTERVAL = 60
RECOVERY_COOLDOWN = 180  # 3 min between recovery attempts

last_recovery_at: float = 0


def log(msg: str) -> None:
    """Print timestamped log to stdout."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] HEARTBEAT_WATCHER | {msg}", flush=True)


def check_heartbeat() -> tuple[bool, int | None]:
    """Check heartbeat age. Returns (is_healthy, age_seconds)."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=5)
        last_at = r.get("ramp:heartbeat:last_at")
        if not last_at:
            return False, None
        last_dt = datetime.fromisoformat(last_at)
        age = int((datetime.now(timezone.utc) - last_dt).total_seconds())
        return age <= STALE_THRESHOLD, age
    except redis.ConnectionError as e:
        log(f"REDIS_UNREACHABLE | error={str(e)[:100]}")
        emit_alert_redis_down(str(e)[:100])
        return True, None  # Can't check, skip recovery


def attempt_recovery() -> None:
    """Restart Celery worker containers via Docker socket."""
    global last_recovery_at
    now = time.time()

    if now - last_recovery_at < RECOVERY_COOLDOWN:
        log(f"RECOVERY_COOLDOWN | seconds_remaining={int(RECOVERY_COOLDOWN - (now - last_recovery_at))}")
        return

    last_recovery_at = now
    log("ATTEMPTING_RECOVERY | restarting celery + celery-fast")

    for container in ("celery", "celery-fast"):
        try:
            result = subprocess.run(
                ["docker", "restart", container],
                capture_output=True, text=True, timeout=30,
            )
            log(f"RESTART_{container.upper()} | exit={result.returncode} stdout={result.stdout.strip()}")
        except Exception as e:
            log(f"RESTART_FAILED | container={container} error={str(e)[:100]}")


def emit_alert_stale(age_seconds: int) -> None:
    """Emit operator alert for stale heartbeat."""
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
        import json
        r.publish("ramp:operator_alerts", json.dumps({
            "type": "operator_alert",
            "severity": "critical",
            "title": "Workers Unresponsive",
            "message": f"Heartbeat stale for {age_seconds}s. Recovery attempted.",
            "alert_type": "heartbeat_stale",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
    except Exception:
        pass  # Best effort


def emit_alert_redis_down(error: str) -> None:
    """Log Redis connectivity failure (can't publish to Redis if it's down)."""
    log(f"CANNOT_EMIT_ALERT | redis_down | error={error}")


def main() -> None:
    """Main loop: check heartbeat every 60s, log status every 5 min."""
    log(f"STARTED | threshold={STALE_THRESHOLD}s interval={CHECK_INTERVAL}s")
    iterations = 0

    while True:
        is_healthy, age = check_heartbeat()

        if not is_healthy and age is not None:
            log(f"HEARTBEAT_STALE | age={age}s threshold={STALE_THRESHOLD}s")
            emit_alert_stale(age)
            attempt_recovery()
        elif age is not None:
            # Log status every 5 minutes (every 5th iteration)
            iterations += 1
            if iterations % 5 == 0:
                log(f"STATUS_OK | heartbeat_age={age}s")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
```

**Docker Compose Service:**

```yaml
heartbeat-watcher:
  image: reddit-saas-app:latest
  command: python scripts/heartbeat_watcher.py
  env_file:
    - .env
  environment:
    - TZ=Asia/Jerusalem
    - HEARTBEAT_STALE_THRESHOLD_SECONDS=300
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:rw
  depends_on:
    redis:
      condition: service_healthy
  restart: unless-stopped
  deploy:
    resources:
      limits:
        memory: 64M
        cpus: '0.1'
```


---

### 2.8 Task Deduplication Decorator — `app/services/task_dedup.py`

**Purpose:** Prevent duplicate task execution within a configurable time window.
Secondary guard behind Beat catch-up prevention.

```python
"""Task deduplication decorator — prevents duplicate task runs within a cooldown.

Usage:
    @celery_app.task(name="my_task")
    @task_dedup(cooldown_seconds=600)
    def my_task():
        ...

Key format: task_dedup:{task_name} or task_dedup:{task_name}:{args_hash}
"""

from __future__ import annotations

import functools
import hashlib
import json
import time

import redis

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def task_dedup(cooldown_seconds: int = 300, include_args: bool = False):
    """Decorator factory for task deduplication.

    Args:
        cooldown_seconds: Minimum interval between executions.
        include_args: If True, dedup key includes task arguments hash,
                      allowing same task with different args to run concurrently.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            task_name = getattr(func, "name", func.__name__)

            # Build dedup key
            if include_args and (args or kwargs):
                args_str = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, default=str)
                args_hash = hashlib.md5(args_str.encode()).hexdigest()[:8]
                dedup_key = f"task_dedup:{task_name}:{args_hash}"
            else:
                dedup_key = f"task_dedup:{task_name}"

            try:
                settings = get_settings()
                r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)

                # Check existing dedup key
                existing = r.get(dedup_key)
                if existing:
                    age = time.time() - float(existing)
                    logger.info(
                        "TASK_DEDUP_SKIPPED | task=%s key=%s age=%.0fs cooldown=%ds",
                        task_name, dedup_key, age, cooldown_seconds,
                    )
                    return None  # Skip execution, no exception

                # Set dedup key with TTL
                r.set(dedup_key, str(time.time()), ex=cooldown_seconds)

            except (redis.ConnectionError, redis.TimeoutError, Exception) as e:
                # Fail-open: allow execution if Redis unreachable
                logger.warning(
                    "TASK_DEDUP_REDIS_FAIL | task=%s error=%s (proceeding)",
                    task_name, str(e)[:100],
                )

            return func(*args, **kwargs)

        return wrapper
    return decorator
```

**Usage Example:**

```python
@celery_app.task(name="build_and_generate_epg_all_avatars")
@task_dedup(cooldown_seconds=600)  # 10 min cooldown
def build_and_generate_epg_all_avatars():
    ...

@celery_app.task(name="run_full_pipeline_all_clients")
@task_dedup(cooldown_seconds=900)  # 15 min cooldown
def run_full_pipeline_all_clients():
    ...
```


---

### 2.9 Error Classification Module — `app/services/error_classification.py`

**Purpose:** Categorize exceptions into transient/permanent/critical for
consistent handling across all pipeline tasks.

```python
"""Structured Error Classification — categorize exceptions for pipeline handling.

Three categories:
- TRANSIENT: retry later (network timeouts, rate limits, temp API errors)
- PERMANENT: skip item (invalid data, missing fields, deleted entities)
- CRITICAL: halt + alert (auth failures, Redis down, config errors)

Usage:
    from app.services.error_classification import classify_error, ErrorType

    try:
        do_work(item)
    except Exception as e:
        error_type = classify_error(e)
        if error_type == ErrorType.TRANSIENT:
            skip_item(item)
            continue
        elif error_type == ErrorType.PERMANENT:
            log_and_skip(item, e)
            continue
        elif error_type == ErrorType.CRITICAL:
            emit_alert(...)
            raise
"""

from __future__ import annotations

from enum import Enum

from app.logging_config import get_logger

logger = get_logger(__name__)


class ErrorType(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    CRITICAL = "critical"


def classify_error(exc: BaseException) -> ErrorType:
    """Classify an exception into transient, permanent, or critical.

    Classification rules (ordered by specificity):
    """
    exc_type = type(exc).__name__
    exc_module = type(exc).__module__ or ""

    # --- CRITICAL ---
    # Redis connection failures
    import redis
    if isinstance(exc, (redis.ConnectionError, redis.TimeoutError)):
        return ErrorType.CRITICAL

    # Auth/config errors
    if isinstance(exc, (PermissionError, OSError)):
        return ErrorType.CRITICAL

    # SQLAlchemy integrity errors — UNIQUE is permanent, others critical
    try:
        import sqlalchemy.exc
        if isinstance(exc, sqlalchemy.exc.IntegrityError):
            error_str = str(exc).lower()
            if "unique" in error_str or "duplicate" in error_str:
                return ErrorType.PERMANENT
            return ErrorType.CRITICAL
        if isinstance(exc, sqlalchemy.exc.OperationalError):
            return ErrorType.CRITICAL
    except ImportError:
        pass

    # --- TRANSIENT ---
    # HTTP/network timeouts
    try:
        import httpx
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout)):
            return ErrorType.TRANSIENT
    except ImportError:
        pass

    # LLM provider timeouts (litellm wraps them)
    if "timeout" in exc_type.lower() or "timeout" in str(exc).lower():
        return ErrorType.TRANSIENT

    # Rate limiting (various forms)
    if "ratelimit" in exc_type.lower() or "429" in str(exc):
        return ErrorType.TRANSIENT

    # Connection reset / broken pipe (transient network)
    if isinstance(exc, ConnectionError):
        return ErrorType.TRANSIENT

    # --- PERMANENT ---
    if isinstance(exc, (ValueError, TypeError, KeyError, AttributeError)):
        return ErrorType.PERMANENT

    if isinstance(exc, (json.JSONDecodeError,)):
        return ErrorType.PERMANENT

    # Reddit-specific: deleted, banned, removed
    exc_str = str(exc).lower()
    if any(kw in exc_str for kw in ("not found", "deleted", "removed", "banned", "404")):
        return ErrorType.PERMANENT

    # Default: treat unknown errors as transient (fail-safe for batch processing)
    logger.warning("ERROR_CLASSIFICATION_DEFAULT | type=%s module=%s classified=transient",
                   exc_type, exc_module)
    return ErrorType.TRANSIENT


import json  # noqa: E402 — needed for JSONDecodeError check above
```


---

### 2.10 Enhanced Feedback Loop Observability

**Changes to `app/services/feedback_loop.py`:**

Add granular ActivityEvent emission at each adjustment point.

```python
# In _apply_hypothesis_updates(), after each successful update:
db.add(ActivityEvent(
    event_type="feedback_hypothesis_update",
    client_id=client_id,
    message=f"Hypothesis confidence: {old_confidence} → {new_confidence}",
    event_metadata={
        "hypothesis_id": str(hyp_id),
        "previous_confidence": old_confidence,
        "new_confidence": new_confidence,
        "delta": delta,
        "reason": reason,
        "subreddit": update.get("subreddit", ""),
        "supporting_outcomes": update.get("data_points", 0),
        "contradicting_outcomes": update.get("contradicting", 0),
    },
))

# In _store_epg_adjustments(), for each subreddit adjustment:
db.add(ActivityEvent(
    event_type="feedback_adjustment",
    client_id=client_id,
    message=f"Subreddit priority: r/{subreddit} adjusted by {delta:+.3f}",
    event_metadata={
        "avatar_id": str(avatar_id),
        "subreddit_name": subreddit,
        "adjustment_delta": delta,
        "adjustment_reason": "outcome_analysis",
    },
))

# At the end of run_feedback_loop(), emit summary:
db.add(ActivityEvent(
    event_type="feedback_loop_summary",
    client_id=client_id,
    message=f"Feedback loop: {results['hypotheses_updated']} hyps, "
            f"{results['adjustments_applied']} adjustments",
    event_metadata={
        "avatar_id": str(avatar_id),
        "total_adjustments_count": results["adjustments_applied"],
        "hypotheses_updated": results["hypotheses_updated"],
        "subreddits_affected": len(results.get("subreddit_adjustments", {})),
        "run_duration_ms": int((time.time() - start_time) * 1000),
        "direction": _compute_direction(results),
    },
))
```

**Drift Warning:**

```python
def _check_drift(avatar_id: UUID, adjustments: dict[str, float]) -> bool:
    """Warn if total absolute adjustments exceed 30% of allocation."""
    total_abs = sum(abs(v) for v in adjustments.values())
    # Assume uniform allocation = 1.0 / num_subreddits per sub
    num_subs = len(adjustments) or 1
    normalized_drift = total_abs / num_subs

    if normalized_drift > 0.3:
        from app.services.operator_alerts import emit_alert
        emit_alert(
            severity="medium",
            title="Feedback Loop Drift Warning",
            message=f"Avatar {avatar_id}: cumulative adjustment {normalized_drift:.1%} "
                    f"exceeds 30% threshold",
            alert_type="feedback_drift",
            entity_id=str(avatar_id),
        )
        return True
    return False
```

---

### 2.11 Worker Memory Protection — `worker.py` Config Change

**Change:** Add `worker_max_tasks_per_child` to Celery config.

```python
# In app/tasks/worker.py celery_app.conf.update():

celery_app.conf.update(
    # ... existing config ...

    # Worker memory protection — recycle after N tasks
    worker_max_tasks_per_child=int(
        os.environ.get("CELERY_MAX_TASKS_PER_CHILD", "200")
    ),
)
```

**Behavior:** Celery's prefork pool terminates a child process after 200 tasks
and spawns a fresh one. This prevents memory leaks from accumulating over
multi-day uptime. The value is configurable via environment variable without
code changes.


---

### 2.12 Redis Health Check Task

**New file: `app/tasks/redis_health.py`**

```python
"""Redis Health Check Task — periodic Redis connectivity and latency validation."""

import time
from datetime import datetime, timezone

import redis

from app.config import get_settings
from app.logging_config import get_logger
from app.tasks.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name="check_redis_health", ignore_result=True)
def check_redis_health() -> dict:
    """Verify Redis connectivity and basic operations.

    Checks: PING, SET/GET round-trip, latency measurement.
    Runs every 5 min via Beat. Emits alert on failure or high latency.
    """
    settings = get_settings()
    results = {"checked_at": datetime.now(timezone.utc).isoformat()}

    try:
        r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5)

        # PING check
        start = time.time()
        r.ping()
        ping_latency_ms = int((time.time() - start) * 1000)
        results["ping"] = {"status": "ok", "latency_ms": ping_latency_ms}

        # SET/GET round-trip
        test_key = "ramp:health_check:test"
        test_value = f"check_{int(time.time())}"
        start = time.time()
        r.set(test_key, test_value, ex=60)
        read_back = r.get(test_key)
        roundtrip_ms = int((time.time() - start) * 1000)

        if read_back != test_value:
            results["roundtrip"] = {"status": "inconsistent", "latency_ms": roundtrip_ms}
            _emit_critical_alert("Redis SET/GET returned inconsistent data")
        else:
            results["roundtrip"] = {"status": "ok", "latency_ms": roundtrip_ms}

        # Check latency threshold
        if ping_latency_ms > 100:
            results["ping"]["warning"] = "high_latency"
            from app.services.operator_alerts import emit_alert
            emit_alert(
                severity="high",
                title="Redis High Latency",
                message=f"Redis PING latency: {ping_latency_ms}ms (threshold: 100ms)",
                alert_type="redis_latency",
            )

        # Write results to heartbeat structure
        r.hset("ramp:redis_health", mapping={
            "last_check": results["checked_at"],
            "ping_ms": str(ping_latency_ms),
            "roundtrip_ms": str(roundtrip_ms),
            "status": "ok",
        })
        r.expire("ramp:redis_health", 600)

        results["status"] = "ok"

    except (redis.ConnectionError, redis.TimeoutError) as e:
        results["status"] = "unreachable"
        results["error"] = str(e)[:100]
        logger.error("REDIS_HEALTH_CHECK_FAILED | error=%s", str(e)[:200])
        # Cannot emit alert via Redis — will be visible via /health/external

    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)[:100]
        logger.error("REDIS_HEALTH_CHECK_ERROR | error=%s", str(e)[:200])

    return results


def _emit_critical_alert(message: str) -> None:
    try:
        from app.services.operator_alerts import emit_alert
        emit_alert(
            severity="critical",
            title="Redis Data Inconsistency",
            message=message,
            alert_type="redis_inconsistency",
        )
    except Exception:
        pass
```

**Beat Schedule Entry (in `worker.py`):**

```python
"check-redis-health": {
    "task": "check_redis_health",
    "schedule": 300.0,  # Every 5 minutes
},
```


---

### 2.13 Log Persistence Strategy — Docker Compose Logging Config

**Change:** Add `json-file` logging driver with rotation to all services.

```yaml
# Add to each service in docker-compose.yml:

x-logging: &default-logging
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"

services:
  app:
    # ... existing config ...
    logging: *default-logging

  celery:
    # ... existing config ...
    logging: *default-logging

  celery-fast:
    # ... existing config ...
    logging: *default-logging

  celery-beat:
    # ... existing config ...
    logging: *default-logging

  heartbeat-watcher:
    # ... existing config ...
    logging: *default-logging

  redis:
    # ... existing config ...
    logging: *default-logging

  db:
    # ... existing config ...
    logging: *default-logging
```

**Disk Impact:** 5 × 50 MB = 250 MB max per container. 7 containers × 250 MB = 1.75 GB
max total. Well within the 60 GB SSD budget.

---

## Data Models

### 3.1 New Column: `comment_drafts.approved_by`

| Column | Type | Nullable | Default |
|--------|------|----------|---------|
| `approved_by` | `String(100)` | Yes | `NULL` |

Values: `"autopilot"`, `"system:{process}"`, `"{user_email}"`, `NULL` (legacy)

### 3.2 New System Settings

| Key | Group | Default | Description |
|-----|-------|---------|-------------|
| `health_check_freeze_circuit_breaker_threshold` | health_check | `"5"` | Max new freezes before batch halt |
| `operator_alert_channels` | alerts | `'["redis_pubsub"]'` | JSON array of alert channels |
| `telegram_bot_token` | alerts | `""` | Telegram bot token |
| `telegram_chat_id` | alerts | `""` | Chat ID for alerts |
| `operator_alert_email` | alerts | `""` | Email for operator alerts |
| `heartbeat_stale_threshold_seconds` | health_check | `"300"` | Heartbeat staleness threshold |

### 3.3 New Redis Keys

| Key | Type | TTL | Purpose |
|-----|------|-----|---------|
| `ramp:kill:all` | String | None | Global kill switch |
| `ramp:kill:{group}` | String | None | Group kill switch |
| `task_dedup:{task_name}` | String | `cooldown_seconds` | Task dedup marker |
| `task_dedup:{task_name}:{hash}` | String | `cooldown_seconds` | Task dedup w/ args |
| `ramp:alerts:rate_limit` | Sorted Set | 3600s | Alert rate limit window |
| `ramp:alerts:dedup:{type}:{entity}` | String (counter) | 3600s | Alert dedup counter |
| `ramp:alerts:suppressed_count` | String | 3600s | Suppressed alert count |
| `ramp:redis_health` | Hash | 600s | Redis health check results |
| `ramp:health_check:test` | String | 60s | Redis roundtrip test |

---

## 4. API Endpoints

### New Routes

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health/external` | None | External monitoring health check |
| POST | `/admin/settings/kill-switch` | Superuser | Toggle kill switch |
| GET | `/admin/api/kill-switches` | Superuser | Get active kill switches (for banner) |


---

## 5. Configuration

### 5.1 New Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CELERY_MAX_TASKS_PER_CHILD` | `200` | Worker memory protection |
| `HEARTBEAT_STALE_THRESHOLD_SECONDS` | `300` | Heartbeat watcher threshold |

### 5.2 System Settings (DB)

All new settings are registered in `app/services/settings.py` DEFAULTS dict
under appropriate groups (`health_check`, `alerts`). They follow the existing
pattern: cached in memory, configurable via admin UI, with validators.

### 5.3 Redis Connection Timeout

All new Redis operations use `socket_timeout=2` for kill switch checks and
`socket_timeout=5` for health checks. The `distributed_lock.py` module
should be updated to include `socket_timeout=5` on its Redis client.

---

## 6. Deployment Changes

### 6.1 Docker Compose Additions

```yaml
# NEW SERVICE: heartbeat-watcher
heartbeat-watcher:
  image: reddit-saas-app:latest
  command: python scripts/heartbeat_watcher.py
  env_file:
    - .env
  environment:
    - TZ=Asia/Jerusalem
    - HEARTBEAT_STALE_THRESHOLD_SECONDS=300
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:rw
  depends_on:
    redis:
      condition: service_healthy
  restart: unless-stopped
  deploy:
    resources:
      limits:
        memory: 64M
        cpus: '0.1'
  logging:
    driver: json-file
    options:
      max-size: "50m"
      max-file: "5"
```

### 6.2 Celery Beat Command Change

Add `celerybeat-schedule` cleanup before Beat starts (shown in §2.4).

### 6.3 Logging Config

Add `x-logging` anchor and apply to all services (shown in §2.13).

### 6.4 Alembic Migration

Single migration `res01_approved_by_field.py` adding nullable `approved_by`
column to `comment_drafts`. Zero-downtime (nullable ADD COLUMN).

### 6.5 Worker Config Change

Add `worker_max_tasks_per_child` to `celery_app.conf.update()` in `worker.py`.

### 6.6 Beat Schedule Addition

Add `check_redis_health` task (every 5 min) to `beat_schedule` dict.

---

## 7. Dependency Order (Build Sequence)

Requirements have dependencies that dictate implementation order:

```
Layer 0 — Foundations (no dependencies):
  ├── Req 9:  Error Classification (utility, used by everything)
  ├── Req 5:  Operator Alerts (service, consumed by Req 2, 7, 12)
  └── Req 11: Worker Memory Protection (1-line config change)

Layer 1 — Core Safety (depends on Layer 0):
  ├── Req 1:  Kill Switch (uses Redis, standalone)
  ├── Req 8:  Task Dedup Decorator (uses Redis, standalone)
  ├── Req 4:  Beat Catch-Up Prevention (docker-compose only)
  └── Req 13: Log Persistence (docker-compose only)

Layer 2 — Integration (depends on Layer 0 + 1):
  ├── Req 2:  Freeze Circuit Breaker (uses Operator Alerts)
  ├── Req 3:  Approved-By Provenance (Alembic + code changes)
  ├── Req 6:  External Health Endpoint (uses Redis checks)
  └── Req 12: Redis Health Check Task (uses Operator Alerts)

Layer 3 — Monitoring (depends on Layer 2):
  ├── Req 7:  Heartbeat Watcher (uses Docker socket + Redis + Alerts)
  └── Req 10: Feedback Loop Observability (uses ActivityEvent model)
```

**Recommended implementation order:**

1. **Req 9** — Error Classification (foundation, no deps)
2. **Req 5** — Operator Alerts (foundation, consumed by many)
3. **Req 11** — Worker Memory Protection (trivial, instant value)
4. **Req 13** — Log Persistence (docker-compose change, instant value)
5. **Req 4** — Beat Catch-Up Prevention (docker-compose change)
6. **Req 1** — Kill Switch (core safety mechanism)
7. **Req 8** — Task Dedup Decorator (complements Req 4)
8. **Req 2** — Freeze Circuit Breaker (uses Req 5)
9. **Req 3** — Approved-By Provenance (Alembic migration)
10. **Req 6** — External Health Endpoint
11. **Req 12** — Redis Health Check Task (uses Req 5)
12. **Req 7** — Heartbeat Watcher (Docker + recovery logic)
13. **Req 10** — Feedback Loop Observability (requires understanding of existing feedback_loop.py)


---

## 8. Integration with Existing Code

### 8.1 Kill Switch Integration (Every Celery Task)

Every task gets a 2-line check at the top:

```python
@celery_app.task(name="run_full_pipeline_all_clients", bind=True)
@task_dedup(cooldown_seconds=900)
def run_full_pipeline_all_clients(self):
    killed, reason = is_killed("run_full_pipeline_all_clients")
    if killed:
        logger.warning("KILL_SWITCH | task=%s reason=%s", self.name, reason)
        return {"status": "killed", "reason": reason}

    # ... existing task body ...
```

### 8.2 Error Classification in distributed_lock.py

Wrap Redis calls with classification:

```python
from app.services.error_classification import classify_error, ErrorType

class DistributedLock:
    def acquire(self) -> bool:
        try:
            r = self._get_redis()
            # ... existing lock logic ...
        except Exception as e:
            error_type = classify_error(e)
            if error_type == ErrorType.CRITICAL:
                logger.error("LOCK_CRITICAL | key=%s error=%s", self.key, e)
                raise  # Propagate critical errors
            else:
                logger.warning("LOCK_TRANSIENT | key=%s error=%s", self.key, e)
                return False  # Fail to acquire (transient)
```

### 8.3 Redis Timeout on All Operations

All Redis clients across the codebase should use `socket_timeout=5`:

```python
# In distributed_lock.py:
self._redis = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5)

# In rate_limiter.py:
self._redis = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5)
```

### 8.4 Admin UI Banner

In `admin_base.html`, add HTMX poll for active kill switches:

```html
<!-- Kill switch banner (polls every 30s) -->
<div hx-get="/admin/api/kill-switches"
     hx-trigger="load, every 30s"
     hx-swap="innerHTML">
</div>
```

Partial template `partials/kill_switch_banner.html`:

```html
{% if active_switches %}
<div class="bg-red-600 text-white px-4 py-2 text-center font-bold">
  ⚠️ SYSTEM HALTED —
  {% for key, reason in active_switches.items() %}
    {{ key }}: {{ reason }}{% if not loop.last %} | {% endif %}
  {% endfor %}
</div>
{% endif %}
```

---

## Error Handling

All resilience components follow the same error handling philosophy:
- **Kill switch check** — fail-open (Redis down → task proceeds)
- **Task dedup** — fail-open (Redis down → task proceeds)
- **Circuit breaker** — fail-safe (too many freezes → halt batch)
- **Operator alerts** — best-effort (delivery failure doesn't block the triggering action)
- **Heartbeat watcher** — conservative (Redis down → skip recovery attempt)
- **Error classification** — unknown errors default to TRANSIENT (continue batch processing)

See Requirement 9 implementation (§2.9) for the full classify_error() logic.

## Correctness Properties

### Property 1: Kill Switch Authoritativeness
Once `ramp:kill:all` is SET in Redis, no Celery task can proceed past its first 5 lines of execution. The only exception is the `system_heartbeat` task which must continue writing heartbeat data for the watcher.

**Validates: Requirements 1.1, 1.2**

### Property 2: Circuit Breaker Isolation
The freeze counter is a local Python integer within `run_health_check_batch()`. It has no persistence between invocations and cannot be affected by concurrent tasks or previous batch runs.

**Validates: Requirements 2.7**

### Property 3: Dedup Key Ephemerality
Every dedup Redis key has a TTL equal to `cooldown_seconds`. If Redis loses all data (restart without persistence), all dedup keys vanish and tasks can execute again — this is safe because it's equivalent to "cooldown expired".

**Validates: Requirements 8.3**

### Property 4: Alert Delivery Independence
Operator alert delivery failures (Telegram timeout, Redis PubSub unreachable) never block or fail the calling service. All alert emission is fire-and-forget with try/except.

**Validates: Requirements 5.5**

### Property 5: No Automatic Unfreeze
The system can freeze avatars autonomously but NEVER unfreezes them without human action. This invariant holds across all components (health checker, CQS checker, posting safety, circuit breaker).

**Validates: Requirements 2.8**

### Property 6: Heartbeat Watcher Independence
The watcher runs in its own Docker container with its own process. A Celery worker hang, OOM kill, or deadlock cannot affect the watcher's ability to detect and recover.

**Validates: Requirements 7.1**

## Testing Strategy

| Component | Test Type | Key Scenarios |
|-----------|-----------|---------------|
| Kill Switch | Unit | Redis up → killed; Redis down → fail-open; group kill |
| Circuit Breaker | Unit | Count resets per batch; triggers at threshold; doesn't trigger below |
| Task Dedup | Unit | First call passes; second call within cooldown skipped; Redis down → passes |
| Error Classification | Unit | Each exception type → correct category |
| Health Endpoint | Integration | All healthy → 200; 1 down → 200 degraded; 2 down → 503 |
| Operator Alerts | Unit | Rate limit at 20; dedup at 3; channel routing |
| Heartbeat Watcher | Integration | Stale heartbeat → recovery triggered; cooldown respected |

---

## 10. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Kill switch Redis unreachable | Tasks continue (fail-open) | By design — prefer running over stuck |
| Heartbeat watcher false positive | Workers restarted unnecessarily | 5 min threshold + 3 min cooldown |
| Docker socket access | Security surface | Watcher is internal, no external access |
| Alert storm | Operator fatigue | Rate limit (20/hr) + dedup (3/type/hr) |
| Dedup decorator blocks legitimate re-run | Task skipped | Cooldown < task interval; admin can DELETE Redis key |
| Circuit breaker too aggressive | Legitimate freezes halt batch | Configurable threshold (2-20); manual admin override |
