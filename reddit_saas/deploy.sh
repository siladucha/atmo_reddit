#!/bin/bash
# =============================================================================
# Smart Deploy Script — Reddit SaaS
# =============================================================================
# Usage:
#   ./deploy.sh              — auto-detect changes, deploy only what's needed
#   ./deploy.sh app          — force deploy main app (app + celery + celery-beat)
#   ./deploy.sh marketing    — force deploy marketing site only
#   ./deploy.sh nginx        — reload nginx config only (zero downtime)
#   ./deploy.sh all          — full rebuild of everything
#   ./deploy.sh status       — check what's running on server
#
# Runs from local Mac, deploys to DigitalOcean server.
# =============================================================================

set -e

SERVER="root@161.35.27.165"
APP_PATH="/app"
MKT_PATH="/marketing_site"
COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log() { echo -e "${GREEN}[deploy]${NC} $1"; }
warn() { echo -e "${YELLOW}[deploy]${NC} $1"; }
error() { echo -e "${RED}[deploy]${NC} $1"; }
info() { echo -e "${BLUE}[deploy]${NC} $1"; }

# --- Rsync excludes (shared) ---
RSYNC_EXCLUDES=(
    --exclude='.venv/'
    --exclude='__pycache__/'
    --exclude='.hypothesis/'
    --exclude='.git/'
    --exclude='*.pyc'
    --exclude='.DS_Store'
    --exclude='logs/'
    --exclude='.env'
    --exclude='.claude/'
    --exclude='.kiro/'
    --exclude='.vscode/'
    --exclude='tests/'
    --exclude='node_modules/'
    --exclude='.pytest_cache/'
)

# =============================================================================
# Functions
# =============================================================================

sync_app_code() {
    log "Syncing main app code to server..."
    rsync -avz --delete "${RSYNC_EXCLUDES[@]}" \
        ./ "${SERVER}:${APP_PATH}/"
    log "App code synced."
}

sync_marketing_code() {
    log "Syncing marketing site code to server..."
    rsync -avz --delete "${RSYNC_EXCLUDES[@]}" \
        ../marketing_site/ "${SERVER}:${MKT_PATH}/"
    log "Marketing code synced."
}

build_app_image() {
    log "Building app image on server..."
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} build app"
    log "App image built."
}

build_marketing_image() {
    log "Building marketing image on server..."
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} build marketing"
    log "Marketing image built."
}

restart_app_services() {
    log "Signaling watchdog: deploy in progress..."
    ssh "$SERVER" "touch /var/lib/ramp-watchdog/deploying"
    log "Restarting app + celery + celery-beat..."
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} up -d app celery celery-fast celery-beat"
    log "App services restarted."
}

restart_marketing() {
    log "Restarting marketing service..."
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} up -d marketing"
    log "Marketing restarted."
}

reload_nginx() {
    log "Reloading nginx config (zero downtime)..."
    # First sync the nginx config
    rsync -avz ./nginx/ "${SERVER}:${APP_PATH}/nginx/"
    # Then reload inside container
    ssh "$SERVER" "cd ${APP_PATH} && docker compose exec nginx nginx -s reload"
    log "Nginx reloaded."
}

check_health() {
    log "Checking health..."
    local health
    health=$(ssh "$SERVER" "curl -sf http://localhost/health" 2>/dev/null || echo "FAILED")
    if echo "$health" | grep -q "ok\|healthy"; then
        log "✅ Health check passed: $health"
    else
        error "❌ Health check failed: $health"
        warn "Check logs: ssh ${SERVER} 'cd ${APP_PATH} && ${COMPOSE_CMD} logs --tail=30 app'"
        return 1
    fi
}

show_status() {
    info "Server container status:"
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} ps"
}

deploy_app() {
    sync_app_code
    build_app_image
    # Update watchdog script on host (lives outside Docker)
    log "Updating watchdog script..."
    ssh "$SERVER" "cp ${APP_PATH}/watchdog/ramp_watchdog.sh /opt/ramp/ramp_watchdog.sh && chmod +x /opt/ramp/ramp_watchdog.sh"
    restart_app_services
    sleep 5
    check_health
    log "Version deployed: $(ssh "$SERVER" "cat ${APP_PATH}/VERSION")"
}

deploy_marketing() {
    sync_marketing_code
    build_marketing_image
    restart_marketing
}

deploy_all() {
    sync_app_code
    sync_marketing_code
    log "Full rebuild of all images..."
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} build"
    log "Signaling watchdog: deploy in progress..."
    ssh "$SERVER" "touch /var/lib/ramp-watchdog/deploying"
    log "Restarting all services (except db, redis)..."
    ssh "$SERVER" "cd ${APP_PATH} && ${COMPOSE_CMD} up -d"
    sleep 5
    check_health
}

# =============================================================================
# Auto-detect mode: check what changed since last deploy
# =============================================================================

auto_detect_deploy() {
    info "Auto-detecting what needs deployment..."

    local deploy_app_flag=false
    local deploy_mkt_flag=false
    local deploy_nginx_flag=false

    # Check for changes using rsync dry-run
    local app_changes
    app_changes=$(rsync -avzn --delete "${RSYNC_EXCLUDES[@]}" \
        ./ "${SERVER}:${APP_PATH}/" 2>/dev/null | grep -c "^[^.]" || true)

    local mkt_changes
    mkt_changes=$(rsync -avzn --delete "${RSYNC_EXCLUDES[@]}" \
        ../marketing_site/ "${SERVER}:${MKT_PATH}/" 2>/dev/null | grep -c "^[^.]" || true)

    if [ "$app_changes" -gt 2 ]; then
        deploy_app_flag=true
        info "  → Main app: ${app_changes} files changed"
    else
        info "  → Main app: no changes"
    fi

    if [ "$mkt_changes" -gt 2 ]; then
        deploy_mkt_flag=true
        info "  → Marketing: ${mkt_changes} files changed"
    else
        info "  → Marketing: no changes"
    fi

    # Check nginx config specifically
    local nginx_diff
    nginx_diff=$(rsync -avzn ./nginx/ "${SERVER}:${APP_PATH}/nginx/" 2>/dev/null | grep -c "nginx.conf" || true)
    if [ "$nginx_diff" -gt 0 ]; then
        deploy_nginx_flag=true
        info "  → Nginx config: changed"
    fi

    echo ""

    # Execute deployments
    if [ "$deploy_app_flag" = true ]; then
        deploy_app
    fi

    if [ "$deploy_mkt_flag" = true ]; then
        deploy_marketing
    fi

    if [ "$deploy_nginx_flag" = true ]; then
        reload_nginx
    fi

    if [ "$deploy_app_flag" = false ] && [ "$deploy_mkt_flag" = false ] && [ "$deploy_nginx_flag" = false ]; then
        log "Nothing to deploy — server is up to date."
        show_status
    fi
}

# =============================================================================
# Main
# =============================================================================

case "${1:-auto}" in
    app)
        deploy_app
        ;;
    marketing|mkt)
        deploy_marketing
        ;;
    nginx)
        reload_nginx
        ;;
    all)
        deploy_all
        ;;
    status)
        show_status
        ;;
    auto)
        auto_detect_deploy
        ;;
    *)
        echo "Usage: ./deploy.sh [app|marketing|nginx|all|status|auto]"
        echo ""
        echo "  auto       — (default) detect changes, deploy only what's needed"
        echo "  app        — rebuild & restart main app + celery workers"
        echo "  marketing  — rebuild & restart marketing site"
        echo "  nginx      — reload nginx config (zero downtime)"
        echo "  all        — full rebuild everything"
        echo "  status     — show container status on server"
        exit 1
        ;;
esac
