#!/bin/bash
# =============================================================================
# Reddit SaaS — DigitalOcean Deployment Script
# =============================================================================
# Run this ON THE SERVER after copying the project:
#   ssh root@161.35.27.165
#   cd /app/reddit_saas
#   bash scripts/deploy_digitalocean.sh
#
# What it does:
#   1. Adds swap (4GB) for 2GB RAM droplet
#   2. Installs Docker + Docker Compose
#   3. Configures firewall (UFW)
#   4. Creates .env from .env.example if missing
#   5. Builds and starts all containers
#   6. Verifies health endpoint
# =============================================================================

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

info() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check we're running as root
if [ "$EUID" -ne 0 ]; then
    error "Run as root: sudo bash scripts/deploy_digitalocean.sh"
    exit 1
fi

echo ""
echo "============================================================"
echo "  Reddit SaaS — DigitalOcean Deployment"
echo "  Server: $(hostname) | $(curl -s ifconfig.me 2>/dev/null || echo 'unknown')"
echo "============================================================"
echo ""

# =============================================================================
# Step 1: Swap (for 2GB RAM droplets)
# =============================================================================
info "Step 1: Configuring swap..."

if [ -f /swapfile ]; then
    info "Swap already exists: $(swapon --show | tail -1)"
else
    TOTAL_RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
    if [ "$TOTAL_RAM_MB" -lt 3500 ]; then
        info "RAM is ${TOTAL_RAM_MB}MB — adding 4GB swap..."
        fallocate -l 4G /swapfile
        chmod 600 /swapfile
        mkswap /swapfile
        swapon /swapfile
        echo '/swapfile none swap sw 0 0' >> /etc/fstab
        # Optimize swap behavior
        echo 'vm.swappiness=10' >> /etc/sysctl.conf
        echo 'vm.vfs_cache_pressure=50' >> /etc/sysctl.conf
        sysctl -p > /dev/null 2>&1
        info "Swap configured: 4GB"
    else
        info "RAM is ${TOTAL_RAM_MB}MB — swap not needed"
    fi
fi

# =============================================================================
# Step 2: Install Docker
# =============================================================================
info "Step 2: Installing Docker..."

if command -v docker &> /dev/null; then
    info "Docker already installed: $(docker --version)"
else
    info "Installing Docker..."
    apt-get update -qq
    apt-get install -y -qq ca-certificates curl gnupg lsb-release

    # Add Docker GPG key
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    # Add Docker repo
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -qq
    apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Start and enable Docker
    systemctl start docker
    systemctl enable docker

    info "Docker installed: $(docker --version)"
fi

# Verify Docker Compose
if docker compose version &> /dev/null; then
    info "Docker Compose: $(docker compose version --short)"
else
    error "Docker Compose not available!"
    exit 1
fi

# =============================================================================
# Step 3: Firewall (UFW)
# =============================================================================
info "Step 3: Configuring firewall..."

if command -v ufw &> /dev/null; then
    ufw --force reset > /dev/null 2>&1
    ufw default deny incoming > /dev/null 2>&1
    ufw default allow outgoing > /dev/null 2>&1
    ufw allow 22/tcp > /dev/null 2>&1    # SSH
    ufw allow 80/tcp > /dev/null 2>&1    # HTTP
    ufw allow 443/tcp > /dev/null 2>&1   # HTTPS (future)
    ufw allow 8000/tcp > /dev/null 2>&1  # App (direct access)
    ufw --force enable > /dev/null 2>&1
    info "Firewall configured: SSH(22), HTTP(80), HTTPS(443), App(8000)"
else
    warn "UFW not found, skipping firewall setup"
fi

# =============================================================================
# Step 4: Environment file
# =============================================================================
info "Step 4: Checking .env file..."

if [ -f .env ]; then
    info ".env exists — keeping current configuration"
else
    if [ -f .env.example ]; then
        cp .env.example .env
        warn ".env created from .env.example — EDIT IT before running!"
        warn "At minimum, set:"
        warn "  - SECRET_KEY (generate: python3 -c \"import secrets; print(secrets.token_urlsafe(32))\")"
        warn "  - POSTGRES_PASSWORD"
        warn "  - REDIS_PASSWORD"
        warn "  - REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET"
        warn "  - LITELLM_API_KEY or GEMINI_API_KEY"
        warn ""
        warn "Edit now: nano .env"
        echo ""
        read -p "Press Enter after editing .env (or Ctrl+C to abort)..."
    else
        error "No .env or .env.example found!"
        exit 1
    fi
fi

# Validate critical env vars
source .env 2>/dev/null || true

MISSING_VARS=""
[ -z "$DATABASE_URL" ] && MISSING_VARS="$MISSING_VARS DATABASE_URL"
[ -z "$REDIS_URL" ] && MISSING_VARS="$MISSING_VARS REDIS_URL"
[ -z "$SECRET_KEY" ] && MISSING_VARS="$MISSING_VARS SECRET_KEY"

if [ -n "$MISSING_VARS" ]; then
    warn "Missing env vars (may be set in docker-compose):$MISSING_VARS"
fi

# =============================================================================
# Step 5: Fix DATABASE_URL for Docker networking
# =============================================================================
info "Step 5: Checking Docker networking in .env..."

# In Docker Compose, services reference each other by service name, not localhost
if grep -q "localhost" .env 2>/dev/null; then
    # Check if DATABASE_URL points to localhost (needs to be 'db' for Docker)
    if grep -q "DATABASE_URL.*localhost" .env; then
        warn "DATABASE_URL uses 'localhost' — Docker containers need service name 'db'"
        warn "Fixing: localhost → db in DATABASE_URL"
        sed -i 's|DATABASE_URL=postgresql://\([^@]*\)@localhost:|DATABASE_URL=postgresql://\1@db:|' .env
    fi
    # Check REDIS_URL
    if grep -q "REDIS_URL.*localhost" .env; then
        warn "REDIS_URL uses 'localhost' — fixing to 'redis'"
        sed -i 's|REDIS_URL=redis://localhost:|REDIS_URL=redis://redis:|' .env
        sed -i 's|REDIS_URL=redis://:.*@localhost:|REDIS_URL=redis://:${REDIS_PASSWORD}@redis:|' .env
    fi
fi

# Ensure REDIS_URL includes password for Docker Redis
if grep -q "REDIS_URL=redis://redis:" .env 2>/dev/null; then
    # No password in URL — add it
    REDIS_PASS=$(grep "^REDIS_PASSWORD=" .env | cut -d= -f2)
    if [ -n "$REDIS_PASS" ] && [ "$REDIS_PASS" != "change-me-in-production" ]; then
        sed -i "s|REDIS_URL=redis://redis:|REDIS_URL=redis://:${REDIS_PASS}@redis:|" .env
        info "Added Redis password to REDIS_URL"
    fi
fi

info "Docker networking configured"

# =============================================================================
# Step 6: Build and start containers
# =============================================================================
info "Step 6: Building Docker images..."

# Use production overrides (memory limits, reduced concurrency for 2GB RAM)
COMPOSE_CMD="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$COMPOSE_CMD build --quiet

info "Starting containers..."
$COMPOSE_CMD up -d

# Wait for health
info "Waiting for services to start (30s for migrations + seed)..."
sleep 30

# =============================================================================
# Step 7: Verify deployment
# =============================================================================
info "Step 7: Verifying deployment..."

echo ""
echo "── Container Status ──"
$COMPOSE_CMD ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""

# Health check
echo "── Health Check ──"
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health 2>/dev/null || echo "000")

if [ "$HEALTH_RESPONSE" = "200" ]; then
    info "✅ Health check PASSED (HTTP 200)"
    curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || true
elif [ "$HEALTH_RESPONSE" = "503" ]; then
    warn "⚠️  Health check returned 503 (degraded) — some services may still be starting"
    curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || true
else
    error "❌ Health check FAILED (HTTP $HEALTH_RESPONSE)"
    echo ""
    echo "── App Logs (last 30 lines) ──"
    docker compose logs --tail=30 app
fi

echo ""
echo "============================================================"
echo "  Deployment Summary"
echo "============================================================"
echo ""
echo "  🌐 App URL:     http://161.35.27.165:8000"
echo "  🔧 Admin:       http://161.35.27.165:8000/admin"
echo "  ❤️  Health:      http://161.35.27.165:8000/health"
echo ""
echo "  📋 Useful commands:"
echo "     docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"
echo "     docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f app"
echo "     docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"
echo "     docker compose -f docker-compose.yml -f docker-compose.prod.yml restart app"
echo "     docker compose -f docker-compose.yml -f docker-compose.prod.yml down"
echo "     docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"
echo ""
echo "  💡 Tip: Add alias to ~/.bashrc:"
echo "     alias dc='docker compose -f docker-compose.yml -f docker-compose.prod.yml'"
echo "     Then use: dc logs -f, dc ps, dc restart app"
echo ""
echo "============================================================"
