#!/bin/bash
# =============================================================================
# RAMP External Watchdog — Runs on HOST (outside Docker)
# =============================================================================
# Checks: Beat alive, PostgreSQL alive, App health, Disk space, Redis alive
# Actions: Auto-restart dead containers, Telegram state change notifications
# Install: systemd timer (every 30s) — see ramp-watchdog.timer
#
# STATE CHANGE NOTIFICATIONS:
# Every time a component transitions state (e.g. running→dead, dead→running),
# a Telegram message is sent with: component, old_state→new_state, reason.
# =============================================================================

set -uo pipefail

# --- Configuration ---
COMPOSE_DIR="/app"
COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
LOG_FILE="/var/log/ramp-watchdog.log"
STATE_DIR="/var/lib/ramp-watchdog"
ALERT_COOLDOWN=300  # seconds between duplicate alerts (for non-state-change alerts only)

# Telegram (loaded from env file)
TG_CONFIG="/opt/ramp/watchdog.env"
if [ -f "$TG_CONFIG" ]; then
    source "$TG_CONFIG"
fi

# Ensure state dir exists
mkdir -p "$STATE_DIR"
mkdir -p "$STATE_DIR/component_state"

# --- Deploy Grace Period ---
# If a deploy is in progress (marker file exists and is fresh < 90s), skip auto-RESTART
# but still CHECK and REPORT state changes. This way operator sees downtime during deploys.
DEPLOY_MARKER="$STATE_DIR/deploying"
DEPLOY_IN_PROGRESS=false
if [ -f "$DEPLOY_MARKER" ]; then
    marker_age=$(( $(date +%s) - $(stat -c %Y "$DEPLOY_MARKER" 2>/dev/null || echo "0") ))
    if [ "$marker_age" -lt 90 ]; then
        DEPLOY_IN_PROGRESS=true
        log "Deploy in progress (${marker_age}s ago). Checks run but auto-restart disabled."
    else
        rm -f "$DEPLOY_MARKER"
    fi
fi

# --- Helpers ---
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" >> "$LOG_FILE"
}

send_telegram() {
    local message="$1"
    if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
        curl -s --max-time 5 \
            "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TG_CHAT_ID}" \
            -d "text=${message}" \
            -d "parse_mode=HTML" > /dev/null 2>&1 || true
    fi
}

# --- State Change Tracking ---
# Stores previous state per component. Sends Telegram on ANY transition.
# No cooldown for state changes — every transition is reported exactly once.
# Includes downtime duration when recovering (dead → running).
report_state() {
    local component="$1"   # e.g. "redis", "postgres", "app", "beat", "worker", "worker_fast", "disk"
    local new_state="$2"   # e.g. "running", "dead", "degraded", "warning"
    local reason="$3"      # e.g. "Container not running", "HTTP 500", "Disk at 85%"
    
    local state_file="$STATE_DIR/component_state/${component}"
    local time_file="$STATE_DIR/component_state/${component}.ts"
    local prev_state="unknown"
    local now_ts=$(date +%s)
    
    if [ -f "$state_file" ]; then
        prev_state=$(cat "$state_file")
    fi
    
    # Only notify on actual state CHANGE
    if [ "$prev_state" != "$new_state" ]; then
        # Determine icon
        local icon="🔄"
        case "$new_state" in
            running|healthy|ok) icon="✅" ;;
            dead|down|critical)  icon="🔴" ;;
            degraded|warning)    icon="🟡" ;;
            restarting)          icon="🔄" ;;
        esac
        
        # Calculate downtime if recovering from dead/critical state
        local downtime_line=""
        if [ -f "$time_file" ]; then
            local prev_ts=$(cat "$time_file")
            if [ -n "$prev_ts" ]; then
                local elapsed=$((now_ts - prev_ts))
                if [ "$elapsed" -ge 3600 ]; then
                    downtime_line="Длительность: $((elapsed / 3600))ч $((elapsed % 3600 / 60))мин"
                elif [ "$elapsed" -ge 60 ]; then
                    downtime_line="Длительность: $((elapsed / 60))мин $((elapsed % 60))с"
                else
                    downtime_line="Длительность: ${elapsed}с"
                fi
            fi
        fi
        
        local msg="${icon} <b>${component}</b>: ${prev_state} → ${new_state}
Причина: ${reason}"
        
        if [ -n "$downtime_line" ]; then
            msg="${msg}
${downtime_line}"
        fi
        
        msg="${msg}
Время: $(date '+%H:%M:%S %d.%m')"
        
        send_telegram "$msg"
        log "STATE_CHANGE [$component] $prev_state → $new_state | $reason | ${downtime_line:-no_prev_ts}"
        
        # Save new state + timestamp
        echo "$new_state" > "$state_file"
        echo "$now_ts" > "$time_file"
    fi
}

send_alert() {
    local severity="$1"
    local message="$2"
    local alert_key="$3"
    
    # Cooldown check — don't spam (for non-state-change alerts like disk warnings)
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
    fi
}

# --- Check Functions ---

check_beat() {
    # Check if Beat container is running
    local beat_status
    beat_status=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD ps celery-beat --format '{{.State}}' 2>/dev/null || echo "unknown")
    
    if [ "$beat_status" != "running" ]; then
        # Check if container was recently restarted (deploy in progress)
        local container_created
        container_created=$(docker inspect app-celery-beat-1 --format '{{.Created}}' 2>/dev/null || echo "")
        if [ -n "$container_created" ]; then
            local created_ts=$(date -d "$container_created" +%s 2>/dev/null || echo "0")
            local now_ts=$(date +%s)
            if [ $((now_ts - created_ts)) -lt 60 ]; then
                log "BEAT: Container recreating (deploy in progress). Skipping restart."
                return 0
            fi
        fi
        
        report_state "beat" "dead" "Контейнер не запущен (docker state=$beat_status)."
        if [ "$DEPLOY_IN_PROGRESS" = false ]; then
            log "BEAT: Container not running (state=$beat_status). Restarting..."
            cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery-beat 2>/dev/null
        else
            log "BEAT: Container not running during deploy. NOT restarting."
        fi
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
                report_state "beat" "dead" "Нет heartbeat ${uptime}с после старта."
                if [ "$DEPLOY_IN_PROGRESS" = false ]; then
                    log "BEAT: No heartbeat after ${uptime}s uptime. Restarting..."
                    cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery-beat 2>/dev/null
                else
                    log "BEAT: No heartbeat during deploy. NOT restarting."
                fi
                return 1
            fi
        fi
    fi
    
    report_state "beat" "running" "Контейнер работает, heartbeat в норме."
    clear_alert "beat_dead"
    clear_alert "beat_silent"
    return 0
}

check_postgres() {
    cd "$COMPOSE_DIR" && $COMPOSE_CMD exec -T db pg_isready -U reddit_saas_user -d reddit_saas >/dev/null 2>&1
    local pg_ready=$?
    
    if [ "$pg_ready" -ne 0 ]; then
        report_state "postgres" "dead" "pg_isready вернул ошибку."
        if [ "$DEPLOY_IN_PROGRESS" = false ]; then
            log "POSTGRES: Not ready. Restarting..."
            cd "$COMPOSE_DIR" && $COMPOSE_CMD restart db 2>/dev/null
        else
            log "POSTGRES: Not ready during deploy. NOT restarting."
        fi
        return 1
    fi
    
    report_state "postgres" "running" "Принимает подключения (pg_isready OK)."
    clear_alert "pg_dead"
    return 0
}

check_app_health() {
    # Check EXTERNAL URL (as user sees it) — detects downtime during deploys too
    local http_code
    http_code=$(curl -sk -o /dev/null -w '%{http_code}' --max-time 10 https://gorampit.com/health 2>/dev/null || echo "000")
    
    if [ "$http_code" != "200" ]; then
        report_state "app" "dead" "/health вернул HTTP $http_code (внешний URL gorampit.com)."
        
        # Auto-restart only if NOT deploying
        if [ "$DEPLOY_IN_PROGRESS" = false ]; then
            log "APP: /health returned HTTP $http_code. Restarting app..."
            cd "$COMPOSE_DIR" && $COMPOSE_CMD restart app 2>/dev/null
        else
            log "APP: /health returned HTTP $http_code during deploy. NOT restarting (grace period)."
        fi
        return 1
    fi
    
    report_state "app" "running" "/health HTTP 200 (gorampit.com доступен)."
    clear_alert "app_dead"
    return 0
}

check_redis() {
    local redis_pass
    redis_pass=$(grep -oP 'REDIS_PASSWORD=\K[^\s]+' "$COMPOSE_DIR/.env" 2>/dev/null || echo "")
    
    local pong
    pong=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD exec -T redis redis-cli -a "$redis_pass" ping 2>/dev/null | tr -d '\r')
    
    if [ "$pong" != "PONG" ]; then
        report_state "redis" "dead" "PING не ответил PONG."
        if [ "$DEPLOY_IN_PROGRESS" = false ]; then
            log "REDIS: Not responding. Restarting..."
            cd "$COMPOSE_DIR" && $COMPOSE_CMD restart redis 2>/dev/null
        else
            log "REDIS: Not responding during deploy. NOT restarting."
        fi
        return 1
    fi
    
    report_state "redis" "running" "PING → PONG."
    clear_alert "redis_dead"
    return 0
}

check_disk() {
    local usage
    usage=$(df /app --output=pcent 2>/dev/null | tail -1 | tr -dc '0-9')
    
    if [ "${usage:-0}" -gt 90 ]; then
        report_state "disk" "critical" "Использование диска ${usage}%! Места почти нет."
        return 1
    elif [ "${usage:-0}" -gt 80 ]; then
        report_state "disk" "warning" "Использование диска ${usage}%. Нужна очистка."
        return 0
    fi
    
    report_state "disk" "ok" "Использование диска ${usage}%."
    clear_alert "disk_full"
    clear_alert "disk_warning"
    return 0
}

check_workers() {
    local celery_status
    celery_status=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD ps celery --format '{{.State}}' 2>/dev/null || echo "unknown")
    
    if [ "$celery_status" != "running" ]; then
        report_state "worker" "dead" "Контейнер celery не запущен (state=$celery_status)."
        if [ "$DEPLOY_IN_PROGRESS" = false ]; then
            log "WORKER: celery container not running. Restarting..."
            cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery 2>/dev/null
        else
            log "WORKER: celery not running during deploy. NOT restarting."
        fi
        return 1
    fi
    
    local fast_status
    fast_status=$(cd "$COMPOSE_DIR" && $COMPOSE_CMD ps celery-fast --format '{{.State}}' 2>/dev/null || echo "unknown")
    
    if [ "$fast_status" != "running" ]; then
        report_state "worker_fast" "dead" "Контейнер celery-fast не запущен (state=$fast_status)."
        if [ "$DEPLOY_IN_PROGRESS" = false ]; then
            log "WORKER-FAST: celery-fast container not running. Restarting..."
            cd "$COMPOSE_DIR" && $COMPOSE_CMD restart celery-fast 2>/dev/null
        else
            log "WORKER-FAST: celery-fast not running during deploy. NOT restarting."
        fi
        return 1
    fi
    
    report_state "worker" "running" "Celery worker активен."
    report_state "worker_fast" "running" "Celery-fast worker активен."
    clear_alert "worker_dead"
    clear_alert "worker_fast_dead"
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
