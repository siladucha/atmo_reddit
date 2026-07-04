#!/bin/bash
# =============================================================================
# RAMP PostgreSQL Backup — Daily automated backup
# =============================================================================
# Creates a compressed pg_dump, rotates old backups (14 days), alerts on failure.
# Install: cron 0 3 * * * /opt/ramp/pg_backup.sh
# =============================================================================

set -euo pipefail

# --- Configuration ---
COMPOSE_DIR="/app"
COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
BACKUP_DIR="/opt/ramp/backups"
RETENTION_DAYS=14
LOG_FILE="/var/log/ramp-backup.log"
DATE=$(date '+%Y-%m-%d_%H%M')
BACKUP_FILE="$BACKUP_DIR/ramp_${DATE}.custom"

# Telegram config
TG_CONFIG="/opt/ramp/watchdog.env"
if [ -f "$TG_CONFIG" ]; then
    source "$TG_CONFIG"
fi

# --- Helpers ---
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') | $1" >> "$LOG_FILE"
}

alert() {
    local message="$1"
    if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
        curl -s --max-time 5 \
            "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TG_CHAT_ID}" \
            -d "text=$message" > /dev/null 2>&1 || true
    fi
    log "ALERT: $message"
}

# --- Main ---
log "=== Backup started ==="

# Ensure backup dir exists
mkdir -p "$BACKUP_DIR"

# Run pg_dump inside Docker
if cd "$COMPOSE_DIR" && $COMPOSE_CMD exec -T db \
    pg_dump -U reddit_saas_user -d reddit_saas \
    --no-owner --format=custom 2>/dev/null > "$BACKUP_FILE"; then
    
    FILESIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
    log "Backup created: $BACKUP_FILE ($FILESIZE)"
    
    # Verify backup is not empty
    BYTES=$(stat -c%s "$BACKUP_FILE" 2>/dev/null || stat -f%z "$BACKUP_FILE" 2>/dev/null || echo "0")
    if [ "$BYTES" -lt 1024 ]; then
        alert "🔴 RAMP Backup FAILED: dump file too small ($BYTES bytes). Likely empty DB or permission error."
        rm -f "$BACKUP_FILE"
        exit 1
    fi
    
    # Rotate old backups
    DELETED=$(find "$BACKUP_DIR" -name "ramp_*.custom" -mtime +${RETENTION_DAYS} -delete -print | wc -l)
    if [ "$DELETED" -gt 0 ]; then
        log "Rotated $DELETED old backups (>${RETENTION_DAYS} days)"
    fi
    
    # Count remaining backups
    TOTAL=$(ls "$BACKUP_DIR"/ramp_*.custom 2>/dev/null | wc -l)
    log "=== Backup complete. $TOTAL backups on disk. ==="
    
    # Optional: weekly Telegram summary (only on Sunday)
    if [ "$(date +%u)" = "7" ]; then
        alert "📦 RAMP Weekly backup summary: $TOTAL backups on disk. Latest: $FILESIZE. Retention: ${RETENTION_DAYS}d."
    fi
    
else
    alert "🔴 RAMP Backup FAILED: pg_dump returned non-zero exit code. Check database health!"
    rm -f "$BACKUP_FILE"
    log "=== Backup FAILED ==="
    exit 1
fi
