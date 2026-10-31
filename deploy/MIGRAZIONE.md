# Spostare BluBeauty su un nuovo server

1. **Sul nuovo server**: clona il repository in `/opt/blubeauty` e copia il file `.env` dal vecchio server
   (contiene password e chiave segreta: senza la stessa `SECRET_KEY` gli utenti dovranno rifare l'accesso).
2. Avvia solo il database: `docker compose up -d db`.
3. **Sul vecchio server**: `bash deploy/backup.sh` e copia il file creato in `backups/` sul nuovo server
   (es. `scp backups/blubeauty-*.sql.gz root@NUOVO_IP:/opt/blubeauty/backups/`).
4. **Sul nuovo server**: `bash deploy/restore.sh backups/<file>` e poi `docker compose up -d --build`.
5. Aggiorna il record DNS del dominio con il nuovo IP. Caddy ottiene da solo il nuovo certificato HTTPS.
6. Verifica l'accesso, poi spegni il vecchio server.

Prova di ripristino consigliata: almeno una volta al mese ripristina l'ultimo backup su un server di prova.
