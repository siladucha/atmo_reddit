#!/bin/bash
# Deploy June 23, 2026 — Dashboard Redesign
# Run from: /Volumes/2SSD/Projects/ReddirSaaS
#
# Changes deployed:
# - Partner dashboard → Business Cockpit (MRR, client health, trial funnel)
# - Owner dashboard → Alert bar (system alerts aggregation)
# - Trial portal → Guided onboarding experience
# - Client Manager → Redirect to portal (no more separate admin view)
# - New services: business_metrics.py, alert_aggregation.py

set -e

echo "=== RAMP Deploy — June 23 (Dashboard Redesign) ==="

# Step 1: rsync code to server
echo "→ Syncing code to server..."
cd reddit_saas
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ root@161.35.27.165:/app/

# Step 2: Rebuild Docker image (code is COPY'd into image, not volume-mounted)
echo "→ Rebuilding Docker image..."
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build --no-cache app"

# Step 3: Restart app + celery (new image)
echo "→ Restarting services..."
ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d app celery celery-beat"

# Step 4: Wait for health
echo "→ Waiting for health check..."
sleep 8
ssh root@161.35.27.165 "curl -s http://localhost:8000/health"

echo ""
echo "=== Deploy complete ==="
echo "Verify: https://gorampit.com/admin/ (login as partner)"
