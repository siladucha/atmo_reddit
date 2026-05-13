#!/bin/bash
# =============================================================================
# Push project to DigitalOcean server
# =============================================================================
# Run this FROM YOUR MAC:
#   cd reddit_saas
#   bash scripts/push_to_server.sh
# =============================================================================

set -e

SERVER="root@161.35.27.165"
REMOTE_DIR="/app/reddit_saas"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

echo ""
echo "============================================================"
echo "  Pushing reddit_saas to $SERVER:$REMOTE_DIR"
echo "============================================================"
echo ""

# Check SSH connectivity
info "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes $SERVER "echo ok" &>/dev/null; then
    echo -e "${RED}[ERROR]${NC} Cannot connect to $SERVER"
    echo "  Make sure your SSH key is added: ssh-copy-id $SERVER"
    exit 1
fi
info "SSH connection OK"

# Create remote directory
info "Creating remote directory..."
ssh $SERVER "mkdir -p $REMOTE_DIR"

# Sync project (excluding unnecessary files)
info "Syncing files..."
rsync -avz --progress \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='.hypothesis/' \
    --exclude='.pytest_cache/' \
    --exclude='.git/' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='logs/' \
    --exclude='.env' \
    --exclude='docker-compose.override.yml' \
    --exclude='*.egg-info/' \
    --exclude='.claude/' \
    --exclude='.kiro/' \
    --exclude='.vscode/' \
    ./ $SERVER:$REMOTE_DIR/

info "Files synced successfully"

# Check if .env exists on server
if ssh $SERVER "test -f $REMOTE_DIR/.env"; then
    info ".env already exists on server (not overwritten)"
else
    warn ".env not found on server — copying .env.example"
    scp .env.example $SERVER:$REMOTE_DIR/.env
    warn "⚠️  EDIT .env on server before starting!"
    warn "   ssh $SERVER"
    warn "   nano $REMOTE_DIR/.env"
fi

echo ""
echo "============================================================"
echo "  ✅ Push complete!"
echo ""
echo "  Next steps:"
echo "    1. ssh $SERVER"
echo "    2. cd $REMOTE_DIR"
echo "    3. nano .env              # Edit production settings"
echo "    4. bash scripts/deploy_digitalocean.sh"
echo "============================================================"
echo ""
