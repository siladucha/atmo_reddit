# Deploy Session — July 7, 2026 (Beat Memory Leak Fix)

## Problem

Celery Beat процесс утекает из 41 MB до 225 MB за 3 часа, упирается в Docker лимит 256 MB, убивается OOM killer. Watchdog поднимает его обратно каждый раз — но это маскирует хроническую проблему (1-3 краша в день, Telegram спам DEAD/RECOVERED).

## Root Cause

Beat использовал `celery -A app.tasks.worker` — это загружает ВСЕ 31 task-модулей через `include=[]` (SQLAlchemy + все 65 моделей, LiteLLM, PRAW, scipy, pydantic schemas...). C-level allocations из этих библиотек постепенно растут (Python GC не видит их — только 4798 Python-объектов при 225 MB RSS).

Beat НЕ НУЖНЫ task-реализации. Он только шлёт task names в Redis по расписанию.

## Solution

Отдельный лёгкий Celery app для Beat (`beat_app.py`) — только broker + schedule, без `include=`, без `backend=`. Никаких тяжёлых импортов.

**Результат:** ~25 MB стабильно. Утечки нет — нечему утекать.

## Changes

| File | What |
|------|------|
| `app/tasks/beat_app.py` | **NEW** — lightweight Celery app: broker + 40 beat_schedule entries only |
| `app/tasks/worker.py` | Removed `beat_schedule` dict + unused `crontab` import. Workers only execute, never schedule. |
| `docker-compose.yml` | Beat: `celery -A app.tasks.beat_app beat`, `exec` (PID1=celery), schedule in `/tmp`, removes old BDB files |
| `docker-compose.prod.yml` | Beat memory limit: 256M → 128M (25 MB process needs 128M max with overhead) |
| `watchdog/ramp_watchdog.sh` | Deploy grace period (skip checks if marker <90s) + container age check before restart alert |

## Migration Required: No

## One-Off Scripts: No

## Pre-Flight Checklist

- [ ] `beat_app.py` compiles
- [ ] `worker.py` compiles
- [ ] `beat_app` has 40 schedule entries (matches previous worker.py)
- [ ] `worker.py` has 0 schedule entries, 30 includes
- [ ] docker-compose.yml uses `app.tasks.beat_app`
- [ ] docker-compose.prod.yml memory = 128M

## Deploy Steps

1. rsync to server
2. docker compose build + up -d
3. Health check
4. Verify Beat memory: `docker stats --no-stream | grep beat` → should be ~25-40 MB
5. Wait 10 min, check again → should NOT grow significantly
6. Update watchdog script on host: `cp /app/watchdog/ramp_watchdog.sh /opt/ramp/ramp_watchdog.sh`

## Rollback Plan

If Beat doesn't start or schedule is broken:
- Change `beat_app` back to `worker` in docker-compose.yml celery-beat command
- Increase memory limit back to 256M
- Rebuild + restart

## Verification (Post-Deploy)

1. `docker stats --no-stream | grep beat` → < 50 MB
2. `docker logs app-celery-beat-1 --tail=5` → shows "beat: Starting..." + sending tasks
3. Wait 1 hour → `docker stats` still < 50 MB (no growth)
4. Check Telegram → no false DEAD alerts during deploy (grace period working)
