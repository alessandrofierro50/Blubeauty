#!/bin/sh
# Backup giornaliero del database (da mettere in crontab sul VPS):
#   0 3 * * * /opt/blubeauty/deploy/backup-db.sh
set -eu
cd "$(dirname "$0")/.."
mkdir -p backups
docker compose exec -T db pg_dump -U blubeauty blubeauty | gzip > "backups/blubeauty-$(date +%F).sql.gz"
find backups -name 'blubeauty-*.sql.gz' -mtime +30 -delete
