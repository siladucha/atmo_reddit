"""Generate RAMP_SYSTEM_DIAGNOSTIC.json — Part 1: meta + graph + entities."""
import json

d = {
  "meta": {
    "version": "1.0.0",
    "generated_at": "2026-06-25T20:00:00+03:00",
    "system_name": "RAMP",
    "system_version": "0.3.0",
    "extraction_method": "reverse_engineering_from_source",
    "completeness": "AS-IS from production codebase",
    "source_path": "reddit_saas/app/"
  },
  "deployment": {
    "provider": "DigitalOcean",
    "region": "FRA1 (Frankfurt)",
    "ip": "161.35.27.165",
    "domain": "gorampit.com",
    "ssl": "Lets Encrypt",
    "resources": {"vcpu": 2, "ram_gb": 4, "ssd_gb": 60},
    "containers": ["app (FastAPI)", "db (PostgreSQL 16)", "redis (Redis 7)", "celery (worker)", "celery-beat (scheduler)"],
    "timezone": "Asia/Jerusalem",
    "deploy_method": "rsync to /app/ + docker compose build + up -d",
    "code_in_image": True,
    "volume_mounted": False
  },
}

with open('RAMP_SYSTEM_DIAGNOSTIC.json', 'w') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
print("Part 1 done")
