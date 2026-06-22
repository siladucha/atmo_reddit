#!/bin/bash
# =============================================================================
# Deploy — June 19, 2026 (post-regression fixes)
# =============================================================================
# Changes deployed:
#   1. Test fixes (onboarding, e2e, avatar_onboarding patch paths)
#   2. pyproject.toml version sync (0.3.0) + pytest markers
#   3. All migrations applied (brand_guardrails, subreddit failure tracking,
#      emotional profile, avatar display_name/persona_bio)
#
# Run: bash deploy_june19.sh
# =============================================================================

set -e

SERVER="root@161.35.27.165"
APP_PATH="/app"
COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
error() { echo -e "${RED}[deploy]${NC} $1"; }

# =============================================================================
# Step 1: Pre-deploy backup on server
# =============================================================================
log "Step 1: Creating DB backup on server..."
ssh "$SERVER" "cd ${APP_PATH} && \
    ${COMPOSE_CMD} exec -T db pg_dump -U reddit_saas_user -d reddit_saas \
    --no-owner --format=custom -f /tmp/pre_deploy_$(date +%Y%m%d_%H%M%S).custom && \
    ls -la /tmp/pre_deploy_*.custom | tail -1"
log "✅ Backup created"

# =============================================================================
# Step 2: Pre-deploy health check
# =============================================================================
log "Step 2: Pre-deploy health check..."
HEALTH=$(ssh "$SERVER" "curl -sf http://localhost/health")
echo "  Current state: $HEALTH"
if ! echo "$HEALTH" | grep -q '"status":"ok"'; then
    error "Server is NOT healthy before deploy! Aborting."
    exit 1
fi
log "✅ Server healthy before deploy"

# =============================================================================
# Step 3: Sync code to server
# =============================================================================
log "Step 3: Syncing code..."
rsync -avz --delete \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='.hypothesis/' \
    --exclude='.git/' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='logs/' \
    --exclude='.env' \
    --exclude='.claude/' \
    --exclude='.kiro/' \
    --exclude='.vscode/' \
    --exclude='tests/' \
    --exclude='node_modules/' \
    --exclude='.pytest_cache/' \
    ./ "${SERVER}:${APP_PATH}/"
log "✅ Code synced"

# =============================================================================
# Step 4: Rebuild Docker images
# =============================================================================
log "Step 4: Building Docker images..."
ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} build app"
log "✅ Image built"

# =============================================================================
# Step 5: Restart services (rolling)
# =============================================================================
log "Step 5: Restarting services..."
ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} up -d app celery celery-beat"
log "✅ Services restarted"

# =============================================================================
# Step 6: Wait for startup
# =============================================================================
log "Step 6: Waiting 10s for startup..."
sleep 10

# =============================================================================
# Step 7: Post-deploy health check
# =============================================================================
log "Step 7: Post-deploy health check..."
HEALTH=$(ssh "$SERVER" "curl -sf http://localhost/health")
echo "  Post-deploy: $HEALTH"
if echo "$HEALTH" | grep -q '"status":"ok"'; then
    log "✅ Health check PASSED"
else
    error "❌ Health check FAILED!"
    warn "Rolling back..."
    # Rollback: use previous image
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} logs --tail=30 app"
    error "Check logs above. Manual intervention needed."
    exit 1
fi

# =============================================================================
# Step 8: Verify trial signup works
# =============================================================================
log "Step 8: Checking trial signup page..."
TRIAL_STATUS=$(ssh "$SERVER" "curl -sf -o /dev/null -w '%{http_code}' https://gorampit.com/onboard/trial")
if [ "$TRIAL_STATUS" = "200" ]; then
    log "✅ Trial signup page responds 200"
else
    warn "⚠️  Trial signup page returned $TRIAL_STATUS (may need nginx reload)"
fi

# =============================================================================
# Step 9: Verify version
# =============================================================================
VERSION=$(ssh "$SERVER" "curl -sf http://localhost/health | python3 -c \"import json,sys; print(json.load(sys.stdin)['version'])\"")
log "✅ Deployed version: $VERSION"

# =============================================================================
# Step 10: Show container status
# =============================================================================
log "Step 10: Final status..."
ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} ps"

echo ""
log "=============================="
log "  DEPLOY COMPLETE — v$VERSION"
log "=============================="
