#!/usr/bin/env python3
"""RAMP Telegram Bot — owner command interface.

Runs on HOST as systemd service. Listens for commands from authorized chat_id only.
Provides: service status, pipeline overview, cost info, restart capability.

Dependencies: pip install python-telegram-bot httpx
Install: systemd service (see watchdog/systemd/ramp-telegram-bot.service)
"""

import os
import sys
import json
import subprocess
import logging
from datetime import datetime, timezone

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/var/log/ramp-telegram-bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# --- Config ---
ENV_FILE = "/opt/ramp/watchdog.env"
COMPOSE_DIR = "/app"
COMPOSE_CMD = "docker compose -f docker-compose.yml -f docker-compose.prod.yml"
HEALTH_URL = "https://gorampit.com/health"
STATE_DIR = "/var/lib/ramp-watchdog/component_state"

# Load env
BOT_TOKEN = ""
ALLOWED_CHAT_IDS: set[str] = set()

if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line.startswith("TG_BOT_TOKEN="):
                BOT_TOKEN = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("TG_CHAT_ID="):
                chat_id = line.split("=", 1)[1].strip().strip('"').strip("'")
                ALLOWED_CHAT_IDS.add(chat_id)
            elif line.startswith("TG_ALLOWED_IDS="):
                # comma-separated additional IDs
                ids = line.split("=", 1)[1].strip().strip('"').strip("'")
                for cid in ids.split(","):
                    cid = cid.strip()
                    if cid:
                        ALLOWED_CHAT_IDS.add(cid)

if not BOT_TOKEN:
    logger.error("TG_BOT_TOKEN not configured in %s", ENV_FILE)
    sys.exit(1)

if not ALLOWED_CHAT_IDS:
    logger.warning("No TG_CHAT_ID or TG_ALLOWED_IDS configured — bot will reject all commands")


# --- Helpers ---

def is_authorized(chat_id: int | str) -> bool:
    return str(chat_id) in ALLOWED_CHAT_IDS


def run_shell(cmd: str, timeout: int = 30) -> tuple[int, str]:
    """Run shell command and return (exit_code, output)."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output[:2000]
    except subprocess.TimeoutExpired:
        return 1, "⏰ Timeout"
    except Exception as e:
        return 1, str(e)[:500]


def get_component_states() -> dict[str, str]:
    """Read saved component states from watchdog state files."""
    states = {}
    if os.path.isdir(STATE_DIR):
        for fname in os.listdir(STATE_DIR):
            fpath = os.path.join(STATE_DIR, fname)
            if os.path.isfile(fpath):
                with open(fpath) as f:
                    states[fname] = f.read().strip()
    return states


# --- Command Handlers ---

def cmd_status() -> str:
    """Service status from watchdog state files + external health."""
    states = get_component_states()

    lines = ["<b>🖥 Service Status</b>\n"]
    icon_map = {
        "running": "🟢", "ok": "🟢", "healthy": "🟢",
        "dead": "🔴", "down": "🔴", "critical": "🔴",
        "warning": "🟡", "degraded": "🟡",
        "unknown": "⚪",
    }

    components = ["redis", "postgres", "app", "beat", "worker", "worker_fast", "disk"]
    for comp in components:
        state = states.get(comp, "unknown")
        icon = icon_map.get(state, "⚪")
        lines.append(f"  {icon} <b>{comp}</b>: {state}")

    # External health check
    try:
        resp = httpx.get(HEALTH_URL, timeout=10, verify=False)
        if resp.status_code == 200:
            data = resp.json()
            ver = data.get("version", "?")
            db_status = data.get("database", "?")
            redis_status = data.get("redis", "?")
            worker_alive = data.get("worker_alive", False)
            lines.append(f"\n<b>📡 /health (external):</b>")
            lines.append(f"  Version: {ver}")
            lines.append(f"  DB: {db_status} · Redis: {redis_status}")
            lines.append(f"  Worker: {'alive' if worker_alive else '❌ dead'}")
        else:
            lines.append(f"\n⚠️ /health returned HTTP {resp.status_code}")
    except Exception as e:
        lines.append(f"\n🔴 /health unreachable: {str(e)[:100]}")

    return "\n".join(lines)


def cmd_pipelines() -> str:
    """Last pipeline run info — from DB via docker exec."""
    query = """
    SELECT pipeline_type, status, started_at, duration_ms, items_succeeded, items_failed
    FROM pipeline_runs
    WHERE id IN (
        SELECT DISTINCT ON (pipeline_type) id
        FROM pipeline_runs
        ORDER BY pipeline_type, started_at DESC
    )
    ORDER BY started_at DESC
    LIMIT 15;
    """
    cmd = f'cd {COMPOSE_DIR} && {COMPOSE_CMD} exec -T db psql -U reddit_saas_user -d reddit_saas -t -A -F "|" -c "{query}"'
    code, output = run_shell(cmd, timeout=15)

    if code != 0 or not output.strip():
        return "❌ Не удалось получить данные из pipeline_runs\n" + output[:200]

    lines = ["<b>⚙️ Pipeline Last Run</b>\n"]
    icon_map = {"completed": "✅", "failed": "❌", "partial": "⚠️", "running": "🔄"}

    for row in output.strip().split("\n"):
        parts = row.split("|")
        if len(parts) < 6:
            continue
        ptype, status, started, duration, ok, fail = parts[:6]
        icon = icon_map.get(status, "❓")
        dur = ""
        if duration and duration != "":
            try:
                ms = int(duration)
                dur = f" ({ms/1000:.1f}s)" if ms < 60000 else f" ({ms/60000:.1f}m)"
            except ValueError:
                pass
        time_str = ""
        if started:
            try:
                dt = datetime.fromisoformat(started)
                time_str = dt.strftime("%H:%M %d.%m")
            except ValueError:
                time_str = started[:16]

        lines.append(f"  {icon} <code>{ptype:20s}</code> {time_str}{dur}  {ok}✓ {fail}✗")

    return "\n".join(lines)


def cmd_costs() -> str:
    """AI costs today."""
    query = """
    SELECT
        COALESCE(SUM(cost_usd), 0) as total,
        COUNT(*) as calls,
        MAX(cost_usd) as max_call
    FROM ai_usage_log
    WHERE created_at >= CURRENT_DATE;
    """
    cmd = f'cd {COMPOSE_DIR} && {COMPOSE_CMD} exec -T db psql -U reddit_saas_user -d reddit_saas -t -A -F "|" -c "{query}"'
    code, output = run_shell(cmd, timeout=10)

    if code != 0:
        return "❌ Не удалось получить AI costs\n" + output[:200]

    parts = output.strip().split("|")
    if len(parts) >= 3:
        total = float(parts[0]) if parts[0] else 0
        calls = int(parts[1]) if parts[1] else 0
        max_call = float(parts[2]) if parts[2] else 0
        return (
            f"<b>💰 AI Costs Today</b>\n\n"
            f"  Total: <b>${total:.3f}</b>\n"
            f"  Calls: {calls}\n"
            f"  Max single: ${max_call:.4f}"
        )
    return "❌ Unexpected format: " + output[:200]


def cmd_avatars() -> str:
    """Avatar fleet status."""
    query = """
    SELECT
        COUNT(*) FILTER (WHERE is_active AND NOT is_frozen) as active,
        COUNT(*) FILTER (WHERE is_frozen) as frozen,
        COUNT(*) FILTER (WHERE is_shadowbanned) as banned,
        COUNT(*) FILTER (WHERE health_status = 'suspended') as suspended,
        COUNT(*) as total
    FROM avatars WHERE is_active = true;
    """
    cmd = f'cd {COMPOSE_DIR} && {COMPOSE_CMD} exec -T db psql -U reddit_saas_user -d reddit_saas -t -A -F "|" -c "{query}"'
    code, output = run_shell(cmd, timeout=10)

    if code != 0:
        return "❌ Не удалось получить данные аватаров\n" + output[:200]

    parts = output.strip().split("|")
    if len(parts) >= 5:
        active, frozen, banned, suspended, total = [int(p) if p else 0 for p in parts[:5]]
        return (
            f"<b>👤 Avatar Fleet</b>\n\n"
            f"  🟢 Active: {active}\n"
            f"  🧊 Frozen: {frozen}\n"
            f"  🚫 Shadowbanned: {banned}\n"
            f"  ☠️ Suspended: {suspended}\n"
            f"  ─────────\n"
            f"  Total active: {total}"
        )
    return "❌ Unexpected format: " + output[:200]


def cmd_drafts() -> str:
    """Pending drafts count."""
    query = """
    SELECT
        COUNT(*) FILTER (WHERE status = 'pending') as pending,
        COUNT(*) FILTER (WHERE status = 'approved') as approved,
        COUNT(*) FILTER (WHERE status = 'posted' AND posted_at >= CURRENT_DATE) as posted_today
    FROM comment_drafts;
    """
    cmd = f'cd {COMPOSE_DIR} && {COMPOSE_CMD} exec -T db psql -U reddit_saas_user -d reddit_saas -t -A -F "|" -c "{query}"'
    code, output = run_shell(cmd, timeout=10)

    if code != 0:
        return "❌ Не удалось получить drafts\n" + output[:200]

    parts = output.strip().split("|")
    if len(parts) >= 3:
        pending, approved, posted = [int(p) if p else 0 for p in parts[:3]]
        return (
            f"<b>📝 Drafts</b>\n\n"
            f"  ⏳ Pending review: {pending}\n"
            f"  ✅ Approved (awaiting post): {approved}\n"
            f"  📤 Posted today: {posted}"
        )
    return "❌ Unexpected format: " + output[:200]


def cmd_errors() -> str:
    """Recent pipeline errors (24h)."""
    query = """
    SELECT pipeline_type, status, error_message, started_at
    FROM pipeline_runs
    WHERE status IN ('failed', 'partial')
      AND started_at >= now() - interval '24 hours'
    ORDER BY started_at DESC
    LIMIT 10;
    """
    cmd = f'cd {COMPOSE_DIR} && {COMPOSE_CMD} exec -T db psql -U reddit_saas_user -d reddit_saas -t -A -F "|" -c "{query}"'
    code, output = run_shell(cmd, timeout=10)

    if code != 0:
        return "❌ Не удалось получить ошибки\n" + output[:200]

    if not output.strip():
        return "✅ <b>Нет ошибок за 24ч</b> — всё чисто!"

    lines = ["<b>🚨 Errors (24h)</b>\n"]
    for row in output.strip().split("\n")[:10]:
        parts = row.split("|")
        if len(parts) < 4:
            continue
        ptype, status, err, started = parts[:4]
        icon = "❌" if status == "failed" else "⚠️"
        time_str = ""
        try:
            dt = datetime.fromisoformat(started)
            time_str = dt.strftime("%H:%M")
        except ValueError:
            time_str = "?"
        err_short = (err or "no message")[:60]
        lines.append(f"  {icon} {time_str} <code>{ptype}</code>\n     {err_short}")

    return "\n".join(lines)


def cmd_restart(service: str) -> str:
    """Restart a Docker service."""
    allowed = {"app", "celery", "celery-fast", "celery-beat", "redis", "db", "nginx"}
    if service not in allowed:
        return f"❌ Unknown service. Allowed: {', '.join(sorted(allowed))}"

    cmd = f"cd {COMPOSE_DIR} && {COMPOSE_CMD} restart {service}"
    code, output = run_shell(cmd, timeout=60)

    if code == 0:
        return f"✅ <b>{service}</b> restarted successfully."
    else:
        return f"❌ Restart failed:\n<code>{output[:300]}</code>"


def cmd_help() -> str:
    """Help message."""
    return (
        "<b>🤖 RAMP Bot Commands</b>\n\n"
        "/status — Статус сервисов\n"
        "/pipelines — Последний запуск пайплайнов\n"
        "/errors — Ошибки за 24ч\n"
        "/costs — AI-расходы за сегодня\n"
        "/avatars — Статус аватаров\n"
        "/drafts — Pending drafts\n"
        "/restart &lt;service&gt; — Рестарт контейнера\n"
        "/help — Эта справка\n"
        "\n<i>Только для авторизованных chat_id.</i>"
    )


# --- Bot Loop (long-polling) ---

def handle_message(chat_id: int, text: str) -> str:
    """Route message to command handler."""
    text = text.strip()
    if not text.startswith("/"):
        return cmd_help()

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().split("@")[0]  # strip @botname suffix
    arg = parts[1].strip() if len(parts) > 1 else ""

    handlers = {
        "/status": lambda: cmd_status(),
        "/start": lambda: cmd_help(),
        "/help": lambda: cmd_help(),
        "/pipelines": lambda: cmd_pipelines(),
        "/errors": lambda: cmd_errors(),
        "/costs": lambda: cmd_costs(),
        "/avatars": lambda: cmd_avatars(),
        "/drafts": lambda: cmd_drafts(),
        "/restart": lambda: cmd_restart(arg) if arg else "Usage: /restart <service>",
    }

    handler = handlers.get(cmd)
    if handler:
        try:
            return handler()
        except Exception as e:
            logger.exception("Command %s failed", cmd)
            return f"❌ Error: {str(e)[:200]}"
    else:
        return f"❓ Unknown command: {cmd}\n\n" + cmd_help()


def send_message(chat_id: int, text: str) -> None:
    """Send reply via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        resp = httpx.post(
            url,
            data={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.warning("Send failed (%d): %s", resp.status_code, resp.text[:200])
    except Exception as e:
        logger.warning("Send error: %s", e)


def main():
    """Long-polling loop."""
    logger.info("RAMP Telegram Bot starting (allowed chat_ids: %s)", ALLOWED_CHAT_IDS)

    offset = 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    while True:
        try:
            resp = httpx.get(
                url,
                params={"offset": offset, "timeout": 30, "allowed_updates": '["message"]'},
                timeout=40,
            )
            if resp.status_code != 200:
                logger.warning("getUpdates failed: %d", resp.status_code)
                continue

            data = resp.json()
            if not data.get("ok"):
                logger.warning("getUpdates not ok: %s", data)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                chat_id = msg.get("chat", {}).get("id")
                text = msg.get("text", "")

                if not chat_id or not text:
                    continue

                # /start is always allowed — returns chat_id for self-service setup
                if text.strip().startswith("/start"):
                    logger.info("/start from chat_id=%s", chat_id)
                    reply = (
                        f"👋 Welcome! Your Chat ID is: <code>{chat_id}</code>\n\n"
                        f"Paste this into your RAMP profile (/admin/profile) to receive notifications.\n\n"
                    )
                    if is_authorized(chat_id):
                        reply += cmd_help()
                    else:
                        reply += "<i>You are not yet authorized for commands. Ask the admin to add your Chat ID.</i>"
                    send_message(chat_id, reply)
                    continue

                if not is_authorized(chat_id):
                    logger.warning("Unauthorized access from chat_id=%s: %s", chat_id, text[:50])
                    send_message(chat_id, "⛔ Unauthorized. Your chat_id is not allowed.")
                    continue

                logger.info("Command from %s: %s", chat_id, text[:100])
                reply = handle_message(chat_id, text)
                send_message(chat_id, reply)

        except httpx.TimeoutException:
            continue  # Normal long-poll timeout
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            break
        except Exception as e:
            logger.exception("Main loop error: %s", e)
            import time
            time.sleep(5)


if __name__ == "__main__":
    main()
