# BluBeauty

Gestionale web in abbonamento per piccole e medie imprese italiane.

## Installazione sulla VPS

1. Nel pannello DNS del dominio crea un record **A** per `blubeauty.blucodeinformatica.it` → `217.76.158.224`.
2. Collegati alla VPS come root ed esegui:

```bash
git clone https://github.com/alessandrofierro50/blubeauty.git /opt/blubeauty
cd /opt/blubeauty
bash deploy/install.sh
```

Lo script installa Docker se manca, genera password casuali nel file `.env`, avvia tutto con HTTPS
automatico e pianifica il backup notturno. Alla fine mostra la password iniziale del super amministratore.

3. Apri `https://blubeauty.blucodeinformatica.it/admin` e accedi.

Per le email automatiche compila i dati SMTP nel file `.env` e riavvia con `docker compose up -d`.

## Aggiornare

```bash
cd /opt/blubeauty && bash deploy/update.sh
```

## Documentazione

- `docs/SPECIFICA.md` — requisiti completi
- `docs/ARCHITETTURA.md` — stack, database, multi-tenant
- `deploy/MIGRAZIONE.md` — spostamento su un nuovo server
- `CLAUDE.md` — note di sviluppo e stato delle fasi
