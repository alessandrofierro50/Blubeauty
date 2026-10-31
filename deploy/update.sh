#!/usr/bin/env bash
# Aggiornamento all'ultima versione: backup, scarica il codice, ricostruisce e riavvia.
set -euo pipefail
cd "$(dirname "$0")/.."
bash deploy/backup.sh
git pull --ff-only
docker compose up -d --build
docker image prune -f >/dev/null
echo ">> Aggiornamento completato. Le migrazioni del database sono applicate all'avvio."
