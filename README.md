# BluBeauty

Il gestionale cloud per **parrucchieri, barber e centri estetici** — by *Blu Code Informatica*.

Produzione: https://blubeauty.blucodeinformatica.it

## Stack

| Livello | Tecnologia |
|---|---|
| Web app + API | Next.js 16 (App Router, Server Actions, Cache Components) · React 19 · TypeScript |
| UI | Tailwind CSS 4 |
| Database | PostgreSQL 16 · Prisma 7 (driver adapter `pg`) |
| Autenticazione | Sessione cifrata in cookie (iron-session) · password bcrypt |
| Deploy | Docker Compose su VPS · Caddy (HTTPS automatico) |

## Avvio in locale

Requisiti: Node 22+, PostgreSQL 16 (oppure `docker compose up db`).

```bash
cp .env.example .env          # imposta DATABASE_URL e SESSION_PASSWORD
npm install
npm run db:migrate            # crea le tabelle
npm run db:seed               # dati demo
npm run dev                   # http://localhost:3000
```

Login demo: `demo@blubeauty.it` / `demo1234`

### Script utili

| Comando | Cosa fa |
|---|---|
| `npm run dev` | server di sviluppo |
| `npm run build` | genera Prisma Client e build di produzione |
| `npm run typecheck` / `npm run lint` | controlli statici |
| `npm run db:migrate` | crea/applica una migrazione in sviluppo |
| `npm run db:deploy` | applica le migrazioni in produzione |
| `npm run db:studio` | interfaccia web sul database |

## Deploy su VPS

1. DNS: record `A` di `blubeauty.blucodeinformatica.it` → IP del VPS.
2. Sul server (Docker installato):
   ```bash
   git clone git@github.com:<org>/blubeauty.git /opt/blubeauty && cd /opt/blubeauty
   cp .env.example .env   # password vere! openssl rand -base64 32
   docker compose up -d --build
   ```
3. Caddy ottiene da solo il certificato HTTPS. Le migrazioni girano a ogni avvio (servizio `migrate`).
4. Backup notturno: `deploy/backup-db.sh` in crontab.

## Struttura

```
prisma/              schema dati, migrazioni, seed demo
src/app/             pagine (App Router)
  (app)/             area riservata: dashboard, agenda, clienti, servizi
  login/             accesso
src/lib/             db, sessione, auth (Data Access Layer), formattazione
src/components/      componenti UI condivisi (logo, navigazione)
public/brand/        proposte di logo (SVG)
docs/                specifica funzionale e roadmap
deploy/              Caddyfile, script di backup
```

## Regole di sviluppo

- **Multi-tenant**: ogni query deve filtrare per `organizationId` preso da `getCurrentUser()` (`src/lib/auth.ts`). Mai fidarsi di ID arrivati dal client senza questo filtro.
- Ogni Server Action verifica l'utente all'inizio.
- Next.js 16 con *Cache Components*: i componenti che leggono sessione/DB stanno dentro un `<Suspense>`. Prima di usare API di Next consultare `node_modules/next/dist/docs/`.
- Orari: il server gira con `TZ=Europe/Rome`.

Documentazione funzionale: [docs/SPECIFICA.md](docs/SPECIFICA.md)
