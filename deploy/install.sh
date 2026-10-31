#!/usr/bin/env bash
# Prima installazione di BluBeauty su una VPS Ubuntu/Debian.
# Uso (da root):  git clone https://github.com/alessandrofierro50/blubeauty.git /opt/blubeauty && cd /opt/blubeauty && bash deploy/install.sh
#
# Due casi:
#  - server libero: Caddy di BluBeauty prende le porte 80/443 e fa da solo il certificato HTTPS;
#  - server con nginx già attivo (altre applicazioni): BluBeauty resta su una porta locale libera (da 8090 in su), nginx gli passa il dominio
#    e certbot fa il certificato. Le altre applicazioni e il firewall non vengono toccati.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo ">> Installo Docker..."
  curl -fsSL https://get.docker.com | sh
fi

setvar() {  # imposta (o aggiunge) una variabile nel .env
  if grep -q "^$1=" .env; then sed -i "s|^$1=.*|$1=$2|" .env; else echo "$1=$2" >> .env; fi
}

if [ ! -f .env ]; then
  echo ">> Creo il file .env con password casuali"
  cp .env.example .env
  rnd() { openssl rand -base64 36 | tr -dc 'A-Za-z0-9' | head -c "${1:-32}"; }
  setvar DB_OWNER_PASSWORD "$(rnd)"
  setvar DB_APP_PASSWORD "$(rnd)"
  setvar SECRET_KEY "$(rnd 64)"
  ADMIN_PW=$(rnd 16)
  setvar SUPERADMIN_PASSWORD "${ADMIN_PW}"
  echo
  echo "   Password iniziale del super amministratore: ${ADMIN_PW}"
  echo "   (salvala: la trovi anche in .env). Compila ora i dati SMTP in .env se li hai."
  echo
fi

# Poca memoria: un processo per l'API e uno per i lavori in background
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
if [ "${MEM_MB}" -lt 3000 ]; then
  echo ">> Memoria ${MEM_MB} MB: imposto API_WORKERS=1 e CELERY_CONCURRENCY=1"
  setvar API_WORKERS 1
  setvar CELERY_CONCURRENCY 1
fi

DOMAIN=$(grep '^SITE_DOMAIN=' .env | cut -d= -f2)
EMAIL=$(grep '^ACME_EMAIL=' .env | cut -d= -f2)
# porta locale libera per BluBeauty (sul server possono girare altre applicazioni)
PORT=$(grep '^HTTP_BIND=' .env | sed 's/.*://' || true)
if [ -z "${PORT}" ]; then
  PORT=8090
  while ss -tln | grep -q ":${PORT}\s"; do PORT=$((PORT + 1)); done
fi

if ss -tlnp 2>/dev/null | grep -E ':(80|443)\s' | grep -q nginx; then
  echo ">> nginx è già attivo sulle porte 80/443: BluBeauty si mette dietro nginx (porta locale ${PORT}, libera)"
  setvar CADDY_SITE ":80"
  setvar HTTP_BIND "127.0.0.1:${PORT}"
  setvar HTTPS_BIND "127.0.0.1:$((PORT + 363))"
  CONF="/etc/nginx/sites-available/${DOMAIN}"
  if [ ! -f "${CONF}" ]; then
    cat > "${CONF}" <<NGINX
# BluBeauty — generato da deploy/install.sh
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        # l'agent dei negozi resta in attesa dei lavori fino a ~30 secondi
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
NGINX
    ln -sf "${CONF}" "/etc/nginx/sites-enabled/${DOMAIN}"
  fi
  nginx -t
  systemctl reload nginx
  if ! command -v certbot >/dev/null 2>&1; then
    echo ">> Installo certbot"
    apt-get update -qq && apt-get install -y -qq certbot python3-certbot-nginx
  fi
  certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m "${EMAIL}" --redirect || \
    echo "ATTENZIONE: certificato non ottenuto; controlla che ${DOMAIN} punti a questo server e rilancia: certbot --nginx -d ${DOMAIN}" >&2
else
  # Server dedicato: firewall con solo SSH e web
  if command -v ufw >/dev/null 2>&1; then
    ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443 >/dev/null
    ufw --force enable >/dev/null || true
  fi
fi

echo ">> Avvio dei servizi (la prima volta può richiedere 5-10 minuti)"
docker compose up -d --build

# Backup giornaliero alle 3:23
CRON="23 3 * * * cd $(pwd) && bash deploy/backup.sh >> /var/log/blubeauty-backup.log 2>&1"
( crontab -l 2>/dev/null | grep -v 'deploy/backup.sh'; echo "$CRON" ) | crontab -

echo
echo ">> Fatto. Tra un minuto BluBeauty sarà su https://${DOMAIN}"
echo "   Pannello amministratore: https://${DOMAIN}/admin"
