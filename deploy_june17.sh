#!/bin/bash
set -e

echo "=== RAMP Deploy — June 17, 2026 ==="
echo "=== Step 1: Database Backup ==="

ssh root@161.35.27.165 "cd /app && docker compose exec -T db pg_dump -U reddit_saas_user -d reddit_saas --no-owner --format=custom -f /tmp/backup_pre_deploy_june17.custom && echo 'Backup OK: $(du -h /tmp/backup_pre_deploy_june17.custom | cut -f1)'"

echo ""
echo "=== Step 2: Rsync Code to Server ==="

cd /Volumes/2SSD/Projects/ReddirSaaS/reddit_saas
rsync -avz --exclude='.venv/' --exclude='__pycache__/' --exclude='.hypothesis/' \
  --exclude='.git/' --exclude='*.pyc' --exclude='.DS_Store' --exclude='logs/' \
  --exclude='.env' --exclude='.claude/' --exclude='.kiro/' --exclude='.vscode/' \
  --exclude='tests/' --delete \
  ./ root@161.35.27.165:/app/

echo ""
echo "=== Step 3: Rebuild & Restart Docker ==="

ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml build && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d"

echo ""
echo "=== Step 4: Wait for containers to start ==="
sleep 10

echo ""
echo "=== Step 5: Run Alembic Migration ==="

ssh root@161.35.27.165 "cd /app && docker compose exec -T app alembic upgrade head 2>&1 || echo 'Migration note: entrypoint may have already applied it'"

echo ""
echo "=== Step 6: Health Check ==="

ssh root@161.35.27.165 "curl -s http://localhost/health | python3 -m json.tool"

echo ""
echo "=== Step 7: Verify Trial Page ==="

ssh root@161.35.27.165 "curl -s -o /dev/null -w '%{http_code}' http://localhost/onboard/trial"

echo ""
echo "=== Step 8: Check Logs (last 20 lines) ==="

ssh root@161.35.27.165 "cd /app && docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=20 app 2>&1 | tail -20"

echo ""
echo "=== DEPLOY COMPLETE ==="
echo "Trial URL: http://161.35.27.165/onboard/trial"
echo "Portal:    http://161.35.27.165/login"
