# BluBeauty — Specifica funzionale e roadmap

> Versione 0.1 · 31/10/2026 · Blu Code Informatica

## 1. Visione

BluBeauty è un gestionale cloud per **parrucchieri, barber e centri estetici** italiani.
Il posizionamento si basa su tre cose:

1. **Fisco italiano senza attriti**: RT / documento commerciale, fattura elettronica SDI, Lotteria degli scontrini.
2. **WhatsApp come canale nativo** per promemoria, conferme e marketing.
3. **Esperienza moderna** (cloud, tablet in reception, smartphone per titolare e operatori) e **migrazione semplice** da altri gestionali.

Concorrenti di riferimento: Treatwell Connect (ex Uala), Fresha, Phorest, Wegest, Passepartout Beauty, Zenoti (enterprise).

## 2. Utenti e ruoli

| Ruolo | Cosa può fare |
|---|---|
| **Titolare** (OWNER) | Tutto, inclusi report economici, impostazioni, utenti |
| **Responsabile** (MANAGER) | Gestione di una sede: agenda, personale, magazzino, report di sede |
| **Reception** (RECEPTION) | Agenda, clienti, cassa |
| **Operatore** (OPERATOR) | Propria agenda, schede tecniche dei clienti in carico |
| **Cliente finale** | Prenotazione online, area personale (fase 2) |

## 3. Architettura

- **Multi-tenant**: un database, ogni record legato a un'`Organization` (il salone cliente). Un'organizzazione può avere più `Location` (sedi).
- **Next.js 16** full-stack: pagine server-rendered + Server Actions. API REST/route handler solo dove servono integrazioni esterne (webhook POS, WhatsApp, app mobile).
- **PostgreSQL** con Prisma; denaro in `Decimal(10,2)`; orari salvati in UTC e mostrati in `Europe/Rome`.
- **Deploy**: Docker Compose su VPS (app + Postgres + Caddy), backup notturno.

### Modello dati (sintesi)

```
Organization ─┬─ Location ─┬─ Resource (cabina, postazione, macchinario)
              │            └─ StaffMember
              ├─ User ── Membership (ruolo)
              ├─ ServiceCategory ── Service (durata, fasi di posa, risorse richieste)
              │                       └─ StaffService (chi lo esegue, prezzo/durata personalizzati)
              ├─ Client ─┬─ TechnicalCard (formula colore, trattamento, anamnesi, consenso)
              │          └─ ClientPackage (sedute totali/usate)
              ├─ Appointment ── AppointmentItem (servizio + operatore + risorsa + orari)
              ├─ PackageTemplate
              ├─ Product (rivendita / uso interno, scorte)
              └─ Sale ─┬─ SaleLine (servizio, prodotto, pacchetto, gift card + operatore)
                       └─ Payment (contanti, carta, Satispay, pacchetto…)
```

Lo schema completo è in `prisma/schema.prisma`.

## 4. Moduli

Legenda stato: ✅ fatto nello scaffold · 🔜 MVP · 🕒 fase successiva

### 4.1 Agenda
- ✅ Vista giornaliera per operatore, navigazione tra giorni
- ✅ Visualizzazione del **tempo di posa** e affiancamento degli appuntamenti sovrapposti
- 🔜 Creazione/modifica appuntamento (cliente, più servizi, operatore, risorsa) con controllo conflitti su operatore **e** risorsa
- 🔜 Drag & drop, ridimensionamento, cambio stato (arrivato, concluso, no-show)
- 🔜 Vista settimanale, vista per cabina/risorsa
- 🔜 Orari di apertura, turni e assenze degli operatori
- 🕒 Lista d'attesa automatica, appuntamenti ricorrenti

### 4.2 Clienti (CRM)
- ✅ Elenco con ricerca, inserimento rapido, consensi privacy/marketing (GDPR)
- ✅ Scheda cliente: schede tecniche, pacchetti residui, storico
- 🔜 Modifica anagrafica, nuove schede tecniche (formula colore, trattamento)
- 🔜 Anamnesi e **consenso informato con firma su tablet**
- 🔜 Foto prima/dopo
- 🕒 Importazione da CSV/Excel e da altri gestionali; unione duplicati

### 4.3 Servizi e listino
- ✅ Elenco per categoria con durata, posa, operatori, risorse
- 🔜 Gestione listino (CRUD), fasi di posa, abilitazione alla prenotazione online

### 4.4 Cassa e fisco
- 🔜 Conto dall'appuntamento, vendita al banco, sconti, pagamenti multipli
- 🔜 Pacchetti a sedute (vendita e scalo automatico), gift card
- 🔜 Chiusura cassa giornaliera
- 🔜 **Integrazione RT** (protocollo XML dei registratori telematici, es. Epson/Custom/RCH) per il documento commerciale
- 🕒 Fattura elettronica via intermediario SDI (API: es. Aruba, Fatture in Cloud, OpenAPI)
- 🕒 POS integrato (SumUp, Nexi, Satispay)

### 4.5 Prenotazione online
- 🔜 Pagina pubblica `/prenota/[slug]` con scelta servizio → operatore → orario
- 🔜 Calcolo disponibilità (orari, turni, appuntamenti, risorse, tempi di posa)
- 🔜 Promemoria e conferma via **WhatsApp Business API** / SMS / email
- 🕒 Caparra o carta a garanzia contro i no-show (Stripe)
- 🕒 Reserve with Google, link per Instagram/Facebook

### 4.6 Magazzino
- 🕒 Prodotti rivendita / uso interno, scorte minime, ordini fornitori, inventario, barcode
- 🕒 Scarico automatico dei consumi per servizio

### 4.7 Personale
- 🕒 Turni, ferie, provvigioni su servizi/prodotti, obiettivi

### 4.8 Marketing e fidelizzazione
- 🕒 Fidelity a punti, campagne automatiche (compleanno, richiamo colore, clienti persi)
- 🕒 Richiesta recensioni Google dopo la visita

### 4.9 Statistiche
- ✅ Dashboard del giorno (appuntamenti, incasso previsto)
- 🕒 Incassi per periodo/operatore/servizio, occupazione agenda, scontrino medio, tasso di ritorno

### 4.10 Multi-sede e AI
- 🕒 Report consolidati, trasferimenti di magazzino
- 🕒 Receptionist AI su WhatsApp/telefono, suggerimenti di riempimento agenda

## 5. Requisiti non funzionali

- **Sicurezza**: isolamento dei dati per organizzazione in ogni query; sessioni cifrate; password bcrypt; HTTPS obbligatorio.
- **GDPR**: dati in UE, registro consensi, esportazione e cancellazione dei dati del cliente, log degli accessi alle schede sanitarie (anamnesi).
- **Affidabilità**: backup giornalieri con retention di 30 giorni; la cassa deve tollerare brevi cali di rete (PWA offline: fase successiva).
- **Usabilità**: ottimizzato per tablet in reception; interfaccia in italiano.

## 6. Roadmap

| Fase | Contenuto | Obiettivo |
|---|---|---|
| **0 — Scaffold** ✅ | Progetto, schema dati, login, dashboard, agenda (lettura), clienti, servizi, Docker | Base tecnica |
| **1 — MVP gestionale** | Agenda completa (CRUD, drag & drop, conflitti), anagrafiche complete, listino, impostazioni sede, utenti e ruoli | Primo salone pilota |
| **2 — Cassa** | Conto, pagamenti, pacchetti, gift card, chiusura cassa, RT | Uso quotidiano completo |
| **3 — Prenotazione online + WhatsApp** | Pagina pubblica, disponibilità, promemoria, no-show | Differenziazione |
| **4 — Magazzino, personale, marketing, report** | Moduli gestionali avanzati | Versione commerciale |
| **5 — Fatturazione SDI, POS, multi-sede, AI** | Integrazioni | Catene e crescita |

## 7. Decisioni aperte

- Logo definitivo (proposte in `public/brand/`).
- Fornitore WhatsApp Business API (Meta Cloud API diretta o BSP italiano).
- Modelli di RT da supportare per primi (in base ai saloni pilota).
- Modello di prezzo (abbonamento per sede / per operatore).
