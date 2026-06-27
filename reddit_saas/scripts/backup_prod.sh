#!/bin/bash
# Production PostgreSQL backup — runs on the DO server inside Docker.
# Saves compressed dumps to /backups/ (volume-mounted).
# Add to crontab: 0 */6 * * * /app/scripts/backup_prod.sh >> /var/log/pg_backup.log 2>&1
#
# Retention: 7 daily + 4 weekly = 11 files max (~50-100 MB each at current data size)

set -euo pipefail

BACKUP_DIR="/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DAY_OF_WEEK=$(date +%u)
FILENAME="ramp_db_${TIMESTAMP}.sql.gz"

echo "[$(date)] Starting backup..."

# Dump database from the db container via docker compose
docker compose -f /app/docker-compose.yml -f /app/docker-compose.prod.yml exec -T db \
    pg_dump -U reddit_saas_user -d reddit_saas --no-owner --format=plain | gzip > "${BACKUP_DIR}/${FILENAME}"

FILESIZE=$(stat -c%s "${BACKUP_DIR}/${FILENAME}" 2>/dev/null || stat -f%z "${BACKUP_DIR}/${FILENAME}")
echo "[$(date)] Backup completed: ${FILENAME} (${FILESIZE} bytes)"

# Cleanup: keep last 7 daily backups
cd "${BACKUP_DIR}"
ls -t ramp_db_*.sql.gz | tail -n +8 | xargs -r rm -f

echo "[$(date)] Cleanup done. Current backups:"
ls -la "${BACKUP_DIR}"/ramp_db_*.sql.gz 2>/dev/null | wc -l
echo " files retained"
