#!/bin/sh
# Nightly PostgreSQL backup. Add to cron:  0 2 * * * /opt/tax/deploy/backup.sh
# Copy the backups OFF the server too (another machine / cloud storage).
set -e
cd "$(dirname "$0")/.."
mkdir -p backups
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip > "backups/tax-$(date +%Y%m%d-%H%M).sql.gz"
find backups -name 'tax-*.sql.gz' -mtime +30 -delete
