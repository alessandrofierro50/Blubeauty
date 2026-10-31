#!/bin/sh
# Crea il ruolo con cui gira l'applicazione: NON è proprietario delle tabelle,
# quindi la Row Level Security si applica sempre.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE blubeauty_app LOGIN PASSWORD '${APP_DB_PASSWORD}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO blubeauty_app;
SQL
