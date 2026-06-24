import re

filepath = '/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/app/services/alert_aggregation.py'
with open(filepath, 'r') as f:
    content = f.read()

# Find the function and replace it
pattern = r'(def _get_worker_alert\(db: Session\) -> list\[Alert\]:.*?)(?=\ndef _get_kill_switch_alerts)'

replacement = '''def _get_worker_alert(db: Session) -> list[Alert]:
    """Check if Celery worker is offline (no heartbeat in 2 min).

    Reads the ramp:heartbeat:last_at key from Redis (written by system_heartbeat task).
    Falls back to showing "no heartbeat" if Redis is unreachable.
    """
    import redis as _redis
    from app.config import get_settings

    now = datetime.now(timezone.utc)

    try:
        settings = get_settings()
        client = _redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=2)
        last_at_str = client.get("ramp:heartbeat:last_at")
        client.close()
    except Exception:
        last_at_str = None

    if not last_at_str:
        return [Alert(
            type="worker_offline",
            severity="critical",
            message="Worker offline \\u2014 no heartbeat detected",
            link="/admin/tasks",
            icon="\\U0001f534",
        )]

    try:
        last_at = datetime.fromisoformat(last_at_str)
        if (now - last_at).total_seconds() > 180:
            return [Alert(
                type="worker_offline",
                severity="critical",
                message="Worker offline \\u2014 last heartbeat >3 min ago",
                link="/admin/tasks",
                icon="\\U0001f534",
            )]
    except (ValueError, TypeError):
        return [Alert(
            type="worker_offline",
            severity="critical",
            message="Worker offline \\u2014 invalid heartbeat timestamp",
            link="/admin/tasks",
            icon="\\U0001f534",
        )]

    return []


'''

result = re.sub(pattern, replacement, content, flags=re.DOTALL)
if result != content:
    with open(filepath, 'w') as f:
        f.write(result)
    print("REPLACED OK")
else:
    print("PATTERN NOT FOUND")
