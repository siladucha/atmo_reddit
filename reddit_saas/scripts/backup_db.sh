#!/bin/bash
# PostgreSQL backup script for reddit_saas
# Runs pg_dump inside the Docker container and saves to host
#
# Usage:
#   ./scripts/backup_db.sh              # manual backup
#   Automated via cron (see setup below)
#
# Retention: keeps last 48 hourly + 30 daily + 12 weekly backups

set -euo pipefail

# Configuration
CONTAINER_NAME="reddit_saas-db-1"
DB_USER="reddit_saas_user"
DB_NAME="reddit_saas"
BACKUP_DIR="/Volumes/2SSD/Projects/ReddirSaaS/reddit_saas/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="reddit_saas_${TIMESTAMP}.sql.gz"

# Retention settings
HOURLY_KEEP=48
DAILY_KEEP=30
WEEKLY_KEEP=12

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Ensure backup directory exists
mkdir -p "${BACKUP_DIR}/hourly"
mkdir -p "${BACKUP_DIR}/daily"
mkdir -p "${BACKUP_DIR}/weekly"

echo -e "${YELLOW}[$(date)] Starting backup...${NC}"

# Check container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo -e "${RED}ERROR: Container ${CONTAINER_NAME} is not running!${NC}"
    exit 1
fi

# Run pg_dump inside container, compress on host
docker exec "${CONTAINER_NAME}" pg_dump -U "${DB_USER}" -d "${DB_NAME}" \
    --format=plain --no-owner --no-acl \
    | gzip > "${BACKUP_DIR}/hourly/${BACKUP_FILE}"

# Verify backup is not empty (minimum 1KB)
BACKUP_SIZE=$(stat -f%z "${BACKUP_DIR}/hourly/${BACKUP_FILE}" 2>/dev/null || stat --printf="%s" "${BACKUP_DIR}/hourly/${BACKUP_FILE}" 2>/dev/null)
if [ "${BACKUP_SIZE}" -lt 1024 ]; then
    echo -e "${RED}ERROR: Backup file is suspiciously small (${BACKUP_SIZE} bytes). Aborting.${NC}"
    rm -f "${BACKUP_DIR}/hourly/${BACKUP_FILE}"
    exit 1
fi

echo -e "${GREEN}[$(date)] Backup created: hourly/${BACKUP_FILE} ($(echo "scale=1; ${BACKUP_SIZE}/1024" | bc)KB)${NC}"

# Daily rotation: copy latest hourly to daily at midnight
HOUR=$(date +"%H")
if [ "${HOUR}" = "00" ]; then
    cp "${BACKUP_DIR}/hourly/${BACKUP_FILE}" "${BACKUP_DIR}/daily/${BACKUP_FILE}"
    echo -e "${GREEN}  → Daily copy saved${NC}"
fi

# Weekly rotation: copy on Sundays at midnight
DAY_OF_WEEK=$(date +"%u")  # 7 = Sunday
if [ "${HOUR}" = "00" ] && [ "${DAY_OF_WEEK}" = "7" ]; then
    cp "${BACKUP_DIR}/hourly/${BACKUP_FILE}" "${BACKUP_DIR}/weekly/${BACKUP_FILE}"
    echo -e "${GREEN}  → Weekly copy saved${NC}"
fi

# Cleanup: remove old backups beyond retention
cleanup_old() {
    local dir=$1
    local keep=$2
    local count=$(ls -1 "${dir}"/*.sql.gz 2>/dev/null | wc -l)
    if [ "${count}" -gt "${keep}" ]; then
        local to_delete=$((count - keep))
        ls -1t "${dir}"/*.sql.gz | tail -n "${to_delete}" | xargs rm -f
        echo -e "${YELLOW}  Cleaned ${to_delete} old backups from $(basename ${dir})${NC}"
    fi
}

cleanup_old "${BACKUP_DIR}/hourly" ${HOURLY_KEEP}
cleanup_old "${BACKUP_DIR}/daily" ${DAILY_KEEP}
cleanup_old "${BACKUP_DIR}/weekly" ${WEEKLY_KEEP}

echo -e "${GREEN}[$(date)] Backup complete.${NC}"
