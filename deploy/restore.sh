#!/usr/bin/env bash
# Ripristino da un backup.  Uso: bash deploy/restore.sh backups/blubeauty-AAAAMMGG-HHMM.sql.gz
set -euo pipefail
cd "$(dirname "$0")/.."
FILE="${1:?Indica il file di backup}"
read -r -p "Il database attuale verrà SOSTITUITO con $FILE. Continuare? (si/no) " ok
[ "$ok" = "si" ] || exit 1
docker compose stop api worker beat
docker compose exec -T db psql -U blubeauty_owner -d postgres -c "DROP DATABASE blubeauty WITH (FORCE);" -c "CREATE DATABASE blubeauty OWNER blubeauty_owner;"
docker compose exec -T db psql -U blubeauty_owner -d blubeauty -c "GRANT CONNECT ON DATABASE blubeauty TO blubeauty_app;"
gunzip -c "$FILE" | docker compose exec -T db psql -q -U blubeauty_owner -d blubeauty
docker compose start api worker beat
echo ">> Ripristino completato."
