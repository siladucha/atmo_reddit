#!/bin/bash
# =============================================================================
# Refresh staging database from production backup
# =============================================================================
# PURPOSE: Give staging a fresh copy of prod DB so schema matches exactly.
#          Staging is safe to break — this script resets it from prod.
#
# USAGE: ./scripts/refresh-staging-db.sh
#
# PREREQUISITES:
#   - SSH access to both `ramp` (prod) and `ramp-staging`
#   - ControlMaster sessions active (ssh ramp / ssh ramp-staging)
#
# WHAT IT DOES:
#   1. Takes latest prod backup (daily 03:00 pg_dump)
#   2. Copies to staging server
#   3. Stops staging app (prevents connections)
#   4. Drops and recreates staging DB
#   5. Restores from prod dump
#   6. Stamps Alembic at current head
#   7. Restarts staging app
#   8. Verifies health
#
# SAFETY:
#   - NEVER touches production (read-only: copies backup file)
#   - Only destroys staging DB (which is expendable)
#   - Prod backup must exist and be >1MB
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${YELLOW}=== Staging DB Refresh from Production ===${NC}"
echo ""

# 1. Find latest prod backup
echo -n "Finding latest prod backup... "
LATEST_BACKUP=$(ssh ramp "ls -t /opt/ramp/backups/ramp_*.custom 2>/dev/null | head -1")
if [ -z "$LATEST_BACKUP" ]; then
    echo -e "${RED}FAILED${NC} — no backups found on prod"
    exit 1
fi
BACKUP_SIZE=$(ssh ramp "stat -c%s $LATEST_BACKUP")
BACKUP_NAME=$(basename "$LATEST_BACKUP")
echo -e "${GREEN}$BACKUP_NAME${NC} ($(echo "$BACKUP_SIZE / 1048576" | bc)MB)"

if [ "$BACKUP_SIZE" -lt 1048576 ]; then
    echo -e "${RED}Backup too small (<1MB) — corrupt?${NC}"
    exit 1
fi

# 2. Copy to staging
echo -n "Copying to staging... "
ssh ramp "cat $LATEST_BACKUP" | ssh ramp-staging "cat > /tmp/prod_restore.custom"
echo -e "${GREEN}done${NC}"

# 3. Stop staging app
echo -n "Stopping staging app... "
ssh ramp-staging "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml stop app celery celery-fast celery-beat 2>/dev/null" || true
echo -e "${GREEN}done${NC}"

# 4. Drop and recreate DB
echo -n "Recreating staging database... "
ssh ramp-staging "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U reddit_saas_user -d postgres -c 'DROP DATABASE IF EXISTS reddit_saas;' 2>&1 && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U reddit_saas_user -d postgres -c 'CREATE DATABASE reddit_saas OWNER reddit_saas_user;' 2>&1" > /dev/null
echo -e "${GREEN}done${NC}"

# 5. Restore from prod dump
echo -n "Restoring prod backup (this takes ~30s)... "
ssh ramp-staging "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db pg_restore -U reddit_saas_user -d reddit_saas --no-owner --no-acl --single-transaction /tmp/prod_restore.custom 2>&1" > /dev/null || true
echo -e "${GREEN}done${NC}"

# 6. Ensure pgvector extension
ssh ramp-staging "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T db psql -U reddit_saas_user -d reddit_saas -c 'CREATE EXTENSION IF NOT EXISTS vector;' 2>&1" > /dev/null

# 7. Start staging app (entrypoint.sh runs alembic upgrade head)
echo -n "Starting staging app... "
ssh ramp-staging "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app celery celery-fast celery-beat 2>&1" > /dev/null
echo -e "${GREEN}done${NC}"

# 8. Wait and verify
echo -n "Waiting for health check... "
sleep 8
HEALTH=$(curl -sf "https://staging.gorampit.com/health" 2>/dev/null || echo "FAILED")
if echo "$HEALTH" | grep -q '"database":"ok"'; then
    echo -e "${GREEN}HEALTHY${NC}"
else
    echo -e "${RED}UNHEALTHY${NC}"
    echo "  Response: $HEALTH"
    echo "  Check logs: ssh ramp-staging 'cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=30 app'"
    exit 1
fi

# 9. Verify alembic state
ALEMBIC_STATE=$(ssh ramp-staging "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T app alembic current 2>&1 | grep head" || echo "UNKNOWN")
echo -e "  Alembic: ${GREEN}$ALEMBIC_STATE${NC}"

# 10. Cleanup
ssh ramp-staging "rm -f /tmp/prod_restore.custom" 2>/dev/null || true

echo ""
echo -e "${GREEN}✅ Staging DB refreshed from prod successfully.${NC}"
echo "   Login with same credentials as production."
echo "   Safe to test, break things, experiment."
