#!/bin/bash
# =============================================================================
# Sync prod DB → staging (daily after EPG generation)
# Triggered by systemd timer at 09:30 Israel time
#
# Flow:
#   1. Fresh pg_dump from prod (not yesterday's backup — includes today's EPG)
#   2. SCP to staging server
#   3. Stop staging app services
#   4. Drop + recreate DB
#   5. pg_restore
#   6. Sanitize sensitive data (passwords, tokens, executor emails)
#   7. Start staging services
#   8. Health check
#
# Prerequisites:
#   - SSH key from prod → staging (root@167.172.191.42)
#   - Docker running on both servers
# =============================================================================

set -euo pipefail

STAGING_HOST="167.172.191.42"
STAGING_USER="root"
DUMP_FILE="/tmp/staging_sync_$(date +%Y%m%d).custom"
REMOTE_DUMP="/tmp/prod_sync.custom"
LOG_TAG="[STAGING-SYNC]"

# Load Telegram credentials (same as watchdog/backup)
TG_CONFIG="/opt/ramp/watchdog.env"
if [ -f "$TG_CONFIG" ]; then
    source "$TG_CONFIG"
fi

log() { echo "$LOG_TAG $(date '+%H:%M:%S') $1"; }

notify() {
    if [ -n "${TG_BOT_TOKEN:-}" ] && [ -n "${TG_CHAT_ID:-}" ]; then
        curl -sf -X POST "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" \
            -d "chat_id=${TG_CHAT_ID}" \
            -d "text=$1" \
            -d "parse_mode=HTML" >/dev/null 2>&1 || true
    fi
}

cleanup() {
    rm -f "$DUMP_FILE"
    ssh -o ConnectTimeout=10 "${STAGING_USER}@${STAGING_HOST}" "rm -f $REMOTE_DUMP" 2>/dev/null || true
}
trap cleanup EXIT

# --- Step 1: Fresh dump from prod ---
log "Starting fresh pg_dump..."
docker compose -f /app/docker-compose.yml -f /app/docker-compose.prod.yml exec -T db \
    pg_dump -U reddit_saas_user -d reddit_saas --no-owner --format=custom \
    > "$DUMP_FILE"

DUMP_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
log "Dump complete: $DUMP_SIZE"

# --- Step 2: Transfer to staging ---
log "Transferring to staging..."
scp -o ConnectTimeout=30 -o StrictHostKeyChecking=no "$DUMP_FILE" "${STAGING_USER}@${STAGING_HOST}:${REMOTE_DUMP}"
log "Transfer complete"

# --- Step 3: Stop staging services ---
log "Stopping staging services..."
ssh -o ConnectTimeout=10 "${STAGING_USER}@${STAGING_HOST}" "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml stop app celery celery-fast celery-beat" || true

# --- Step 4: Drop + recreate DB ---
log "Recreating staging DB..."
ssh "${STAGING_USER}@${STAGING_HOST}" bash <<'REMOTE_SCRIPT'
set -e
cd /app
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# Kill existing connections
$DC exec -T db psql -U reddit_saas_user -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='reddit_saas' AND pid <> pg_backend_pid();" >/dev/null 2>&1 || true

$DC exec -T db dropdb -U reddit_saas_user --if-exists reddit_saas
$DC exec -T db createdb -U reddit_saas_user reddit_saas
REMOTE_SCRIPT

# --- Step 5: Restore ---
log "Restoring on staging..."
ssh "${STAGING_USER}@${STAGING_HOST}" bash <<REMOTE_SCRIPT
set -e
cd /app
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

docker cp $REMOTE_DUMP app-db-1:/tmp/prod_sync.custom
\$DC exec -T db pg_restore -U reddit_saas_user -d reddit_saas --no-owner --clean --if-exists /tmp/prod_sync.custom || true
docker exec app-db-1 rm -f /tmp/prod_sync.custom
REMOTE_SCRIPT

# --- Step 6: Sanitize sensitive data ---
log "Sanitizing sensitive data..."
ssh "${STAGING_USER}@${STAGING_HOST}" bash <<'REMOTE_SCRIPT'
set -e
cd /app
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$DC exec -T db psql -U reddit_saas_user -d reddit_saas <<SQL
-- Mask passwords (set all to bcrypt hash of 'staging123')
UPDATE users SET hashed_password = '\$2b\$12\$ZNRqF8qql9igR/ShNkK2.eAKndrst3wcVfYeW4ER6vpnordCp/oMu' WHERE hashed_password IS NOT NULL;

-- Clear sensitive tokens
UPDATE users SET password_reset_token_hash = NULL, email_verification_token_hash = NULL;

-- Mask executor emails (keep domain structure for testing)
UPDATE avatars SET executor_email = 'staging+' || LEFT(id::text, 8) || '@gorampit.com' WHERE executor_email IS NOT NULL;

-- Clear encrypted credentials (proxy URLs, Reddit passwords)
UPDATE avatars SET reddit_password_encrypted = NULL, proxy_url_encrypted = NULL;

-- Clear OAuth tokens
UPDATE avatars SET reddit_refresh_token_encrypted = NULL;

-- Mark as staging environment
INSERT INTO system_settings (key, value, group_name) VALUES ('environment_label', 'STAGING (synced from prod)', 'system')
ON CONFLICT (key) DO UPDATE SET value = 'STAGING (synced from prod)';
SQL
REMOTE_SCRIPT
log "Sanitization complete"

# --- Step 7: Start services ---
log "Starting staging services..."
ssh "${STAGING_USER}@${STAGING_HOST}" "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app celery celery-fast celery-beat"

# --- Step 8: Health check (wait up to 60s) ---
log "Waiting for health..."
for i in $(seq 1 6); do
    sleep 10
    status=$(ssh "${STAGING_USER}@${STAGING_HOST}" "curl -sf -o /dev/null -w '%{http_code}' http://localhost:80/health" 2>/dev/null || echo "000")
    if [ "$status" = "200" ]; then
        log "✅ Staging healthy after sync ($DUMP_SIZE)"
        notify "✅ <b>Staging synced</b> from prod ($DUMP_SIZE). Healthy."
        exit 0
    fi
    log "  Health attempt $i: HTTP $status"
done

log "❌ Staging health check failed after sync"
notify "❌ <b>Staging sync failed</b> — health check timeout after restore"
exit 1
