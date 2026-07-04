#!/bin/bash
# =============================================================================
# RAMP External Watchdog — Runs on HOST (outside Docker)
# =============================================================================
# Checks: Beat alive, PostgreSQL alive, App health, Disk space, Redis alive
# Actions: Auto-restart dead containers, Telegram alerts
# Install: systemd timer (every 30s) — see ramp-watchdog.timer
# =============================================================================

set -uo pipefail

# --- Configuration ---
COMPOSE_DIR="/app"
COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
LOG_FILE="/var/log/ramp-watchdog.log"
STATE_DIR="/var/lib/ramp-watchdog"
ALERT_COOLDOWN=300  # seconds between duplicate alerts

# Telegram (loaded from env file)
TG_CONFIG="/opt/ramp/watchdog.env"
if [ -f "$TG_CONFIG" ]; then
    source "$TG_CONFIG"
fi

# Ensure state dir exists
mkdir -p "$STATE_DIR"

# --- Helpers ---
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" >> "$LOG_FILE"
}

send_alert() {
    local severity="$1"
    local message="$2"
    local alert_key="$3"
    
    # Cooldown check — don't spam
    local cooldown_file="$STATE_DIR/cooldown_${alert_key}"
    if [ -f "$cooldown_file" ]; then
        local last_alert=$(cat "$cooldown_file")
        local now=$(date +%s)
        if [ $((now - last_alert)) -lt $ALERT_COOLDOWN ]; then
            return 0  # Skip — too recent
        fi
    fi
    
    # Send Telegram
    if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
        local icon="⚠️"
        [ "$severity" = "CRITICAL" ] && icon="🔴"
        [ "$severity" = "RECOVERED" ] && icon="✅"
        
        curl -s --max-time 5 \
            "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TG_CHAT_ID}" \
            -d "text=${icon} RAMP Watchdog: ${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1 || true
    fi
    
    # Update cooldown
    date +%s > "$cooldown_file"
    log "ALERT [$severity] $message"
}

clear_alert() {
    local alert_key="$1"
    local cooldown_file="$STATE_DIR/cooldown_${alert_key}"
    if [ -f "$cooldown_file" ]; then
        rm -f "$cooldown_file"
        send_alert "RECOVERED" "$2" "${alert_key}_recovered"
    fi
}

# --- Check Functions ---

check_beat() {
    # Check if Beat container is running
    local beat_status
    beat_status=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD ps celery-beat --format '{{.State}}' 2>/dev/null || echo "unknown")
    
    if [ "$beat_status" != "running" ]; then
        log "BEAT: Container not running (state=$beat_status). Restarting..."
        cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery-beat 2>/dev/null
        send_alert "CRITICAL" "Celery Beat was DEAD (state=$beat_status). Auto-restarted." "beat_dead"
        return 1
    fi
    
    # Check heartbeat timestamp in Redis
    local redis_pass
    redis_pass=$(grep -oP 'REDIS_PASSWORD=\K[^\s]+' "$COMPOSE_DIR/.env" 2>/dev/null || echo "")
    
    if [ -n "$redis_pass" ]; then
        local last_hb
        last_hb=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD exec -T redis redis-cli -a "$redis_pass" GET "ramp:heartbeat:last_at" 2>/dev/null | tr -d '\r')
        
        if [ -z "$last_hb" ] || [ "$last_hb" = "(nil)" ]; then
            # No heartbeat key — Beat may have just started or Redis was flushed
            local uptime
            uptime=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD exec -T celery-beat ps -o etimes= -p 1 2>/dev/null | tr -d ' ' || echo "0")
            
            if [ "${uptime:-0}" -gt 180 ]; then
                log "BEAT: No heartbeat after ${uptime}s uptime. Restarting..."
                cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery-beat 2>/dev/null
                send_alert "CRITICAL" "Celery Beat has no heartbeat after ${uptime}s. Auto-restarted." "beat_silent"
                return 1
            fi
        fi
    fi
    
    clear_alert "beat_dead" "Celery Beat recovered and running."
    clear_alert "beat_silent" "Celery Beat heartbeat restored."
    return 0
}

check_postgres() {
    local pg_status
    pg_status=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD exec -T db pg_isready -U reddit_saas_user -d reddit_saas 2>/dev/null)
    
    if [ $? -ne 0 ]; then
        log "POSTGRES: Not ready. Restarting..."
        cd "$COMPOSE_DIR" && $COMPOSE_CMD restart db 2>/dev/null
        send_alert "CRITICAL" "PostgreSQL was DOWN. Auto-restarted. Check data integrity!" "pg_dead"
        return 1
    fi
    
    clear_alert "pg_dead" "PostgreSQL recovered and accepting connections."
    return 0
}

check_app_health() {
    local http_code
    http_code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 https://localhost/health 2>/dev/null || echo "000")
    
    if [ "$http_code" != "200" ]; then
        log "APP: /health returned HTTP $http_code. Restarting app..."
        cd "$COMPOSE_DIR" && $COMPOSE_CMD restart app 2>/dev/null
        send_alert "CRITICAL" "App /health returned HTTP $http_code. Auto-restarted." "app_dead"
        return 1
    fi
    
    clear_alert "app_dead" "App /health recovered (HTTP 200)."
    return 0
}

check_redis() {
    local redis_pass
    redis_pass=$(grep -oP 'REDIS_PASSWORD=\K[^\s]+' "$COMPOSE_DIR/.env" 2>/dev/null || echo "")
    
    local pong
    pong=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD exec -T redis redis-cli -a "$redis_pass" ping 2>/dev/null | tr -d '\r')
    
    if [ "$pong" != "PONG" ]; then
        log "REDIS: Not responding. Restarting..."
        cd "$COMPOSE_DIR" && $COMPOSE_CMD restart redis 2>/dev/null
        send_alert "CRITICAL" "Redis was DOWN. Auto-restarted." "redis_dead"
        return 1
    fi
    
    clear_alert "redis_dead" "Redis recovered."
    return 0
}

check_disk() {
    local usage
    usage=$(df /app --output=pcent 2>/dev/null | tail -1 | tr -dc '0-9')
    
    if [ "${usage:-0}" -gt 90 ]; then
        send_alert "CRITICAL" "Disk usage at ${usage}%! Server may run out of space." "disk_full"
        return 1
    elif [ "${usage:-0}" -gt 80 ]; then
        send_alert "WARNING" "Disk usage at ${usage}%. Consider cleanup." "disk_warning"
        return 0
    fi
    
    clear_alert "disk_full" "Disk usage back to normal (${usage}%)."
    clear_alert "disk_warning" "Disk usage back to normal (${usage}%)."
    return 0
}

check_workers() {
    local celery_status
    celery_status=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD ps celery --format '{{.State}}' 2>/dev/null || echo "unknown")
    
    if [ "$celery_status" != "running" ]; then
        log "WORKER: celery container not running. Restarting..."
        cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery 2>/dev/null
        send_alert "CRITICAL" "Celery worker was DEAD. Auto-restarted." "worker_dead"
        return 1
    fi
    
    local fast_status
    fast_status=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD ps celery-fast --format '{{.State}}' 2>/dev/null || echo "unknown")
    
    if [ "$fast_status" != "running" ]; then
        log "WORKER-FAST: celery-fast container not running. Restarting..."
        cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery-fast 2>/dev/null
        send_alert "HIGH" "Celery-fast worker was DEAD. Auto-restarted." "worker_fast_dead"
        return 1
    fi
    
    clear_alert "worker_dead" "Celery worker recovered."
    clear_alert "worker_fast_dead" "Celery-fast worker recovered."
    return 0
}

# --- Main Execution ---

log "--- Watchdog check started ---"

FAILURES=0

check_redis || ((FAILURES++))
check_postgres || ((FAILURES++))
check_app_health || ((FAILURES++))
check_beat || ((FAILURES++))
check_workers || ((FAILURES++))
check_disk || ((FAILURES++))

if [ $FAILURES -eq 0 ]; then
    # Write success marker for external monitoring
    date +%s > "$STATE_DIR/last_success"
fi

log "--- Watchdog check complete (failures=$FAILURES) ---"
exit 0
