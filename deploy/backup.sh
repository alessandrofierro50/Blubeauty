#!/usr/bin/env bash
# Backup del database: copia locale (ultimi 14 giorni) + copia fuori dalla VPS se BACKUP_REMOTE è impostato.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
FILE="backups/blubeauty-$(date +%Y%m%d-%H%M).sql.gz"
docker compose exec -T db pg_dump -U blubeauty_owner -d blubeauty --no-owner | gzip > "$FILE"
echo "$(date) backup creato: $FILE ($(du -h "$FILE" | cut -f1))"
# Immagini e allegati caricati
MEDIA="backups/blubeauty-media-$(date +%Y%m%d-%H%M).tar.gz"
docker compose exec -T api tar czf - -C /data media > "$MEDIA" && echo "media: $MEDIA"
find backups -name 'blubeauty-*.gz' -mtime +14 -delete

REMOTE=$(grep '^BACKUP_REMOTE=' .env | cut -d= -f2- || true)
if [ -n "${REMOTE}" ]; then
  if command -v rclone >/dev/null 2>&1; then
    rclone copy "$FILE" "$REMOTE" && rclone copy "$MEDIA" "$REMOTE" && echo "copiato su $REMOTE"
  else
    echo "ATTENZIONE: BACKUP_REMOTE impostato ma rclone non è installato" >&2
  fi
fi
