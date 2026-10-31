# BluBeauty — note di progetto

Gestionale SaaS multi-azienda per **parrucchieri, barber e centri estetici**, venduto in abbonamento.
Nato il 2026-10-31 come derivato di **BluGest** (come BluVitis): multi-tenant con RLS, pannello del super amministratore,
abbonamenti standard, prova dal sito, Console, pagamenti, cassa POS, **BluBeauty Agent** per registratore telematico e
stampanti termiche, fatturazione elettronica FatturaPA/Aruba. Il prototipo Next.js iniziale è nel ramo `prototipo-nextjs`.
Produzione prevista: https://blubeauty.blucodeinformatica.it (VPS 217.76.158.224, installazione in `/opt/blubeauty`).
Specifica di BluBeauty: `docs/BLUBEAUTY.md`. Base comune (scritta per BluGest): `docs/SPECIFICA.md`, `docs/ARCHITETTURA.md`.
WhatsApp Business: `docs/WHATSAPP.md`. Identità visiva: `docs/BRAND.md`.

## Cosa si vende (pacchetti PROVVISORI del 2026-10-31, da confermare dal titolare)
- **AGENDA** — 19 €/mese (190 €/anno): moduli `agenda`, `anagrafiche`, `statistiche_base`. Agenda con tempi di posa,
  prenotazione online da smartphone con disdetta, conferme/promemoria/disdette WhatsApp, schede clienti.
- **SALONE** — 39 €/mese (390 €/anno): + `marketing`, `pos`, `periferiche`, `magazzino`, `acquisti`, `vendite`, `scadenzario`.
  Cassa con registratore telematico e termica (BluBeauty Agent), prodotti, fatture, marketing WhatsApp.
- Modulo extra: `fatturapa`. Prova dal sito: pacchetto `SALONE`, 7 giorni. Sezionale fatture abbonamenti `BB`.
- Moduli ereditati e **non venduti** (codice presente): tentata vendita (router smontato in `app/main.py`, rotte tolte dal
  frontend), statistiche avanzate, contabilità, e-commerce. Restano in `logic.MODULES`; menu e pannello mostrano solo
  `logic.CATALOG_MODULES`. La fatturazione dei DDT di fine mese NON riguarda BluBeauty (decisione comune del 2026-10-31):
  le voci DDT/contratti sono tolte dal menu.

## Modulo Agenda (`backend/app/agenda/`, frontend `src/pages/agenda/` e `src/pages/prenota/`)
- `service.py` è l'unico punto che scrive operatori, servizi, appuntamenti, schede clienti e pagine di prenotazione.
- Cliente dell'appuntamento = `parties` (anagrafica comune) + `agenda_client_profiles` (consensi GDPR, compleanno, punti).
- Disponibilità (`available_slots`): orari del salone o personali dell'operatore, appuntamenti attivi, risorse (cabine:
  ne serve UNA libera per tutta la durata) e **tempo di posa**: da `processing_start_min` per `processing_min` minuti
  l'operatore è libero, la risorsa no. Gli item copiano i tempi del servizio al momento della prenotazione.
- Prenotazione pubblica `GET/POST /api/prenota/<slug>…` (`public_router.py`): `booking_pages` è tabella di SISTEMA senza RLS
  (slug → azienda), poi `set_tenant`; serve abbonamento con accesso pieno e modulo agenda; limiti per IP; campo trappola
  `website`; il cliente si riconosce dal cellulare normalizzato (+39…). Link personale `/prenota/<slug>/a/<public_token>`
  (token casuale lungo): disdetta dal cliente solo fino a `cancel_hours` ore prima (409 dopo).
- Incasso `POST /api/agenda/appuntamenti/{id}/incassa`: costruisce le righe (servizi con reparto dei servizi, prodotti
  dal catalogo di cassa) e chiama `app.pos.service.create_sale` → scontrino SCO con documento commerciale sul
  registratore tramite l'agent (`periferiche.fiscalize`), oppure `invoice=true` → fattura FTI già incassata (poi invio SDI
  con `fatturapa`). `client_uuid` = uuid5 dell'appuntamento: un doppio clic non fa due scontrini. Lo sconto si ripartisce
  sui prezzi dei servizi (`apply_discount`). Punti fedeltà = euro interi pagati.

## Modulo Marketing (`backend/app/marketing/`, frontend `src/pages/marketing/`)
- `service.py` è l'unico punto che scrive `messages`, `automations`, `campaigns`. Invio WhatsApp: modalità `simulato`
  (registra senza inviare) o `cloud_api` (WhatsApp Business Cloud API di Meta, token cifrato con SECRET_KEY; `_transport`
  httpx nei test). Fuori dalla finestra di 24 ore Meta richiede modelli approvati: vedi `docs/WHATSAPP.md`.
- Automatici: conferma, promemoria (job orario al minuto 11), disdetta → pacchetto AGENDA; grazie + recensione (all'incasso),
  richiamo (giorni del servizio), compleanno, clienti persi (job alle 9:37) → modulo `marketing`. Niente doppioni:
  indice unico `messages(tenant_id, dedupe_key)`. Campagne e automatici di marketing SOLO a chi ha il consenso marketing.
- Migrazione `0024_agenda_marketing` (RLS su tutte le tabelle cliente). Test: `tests/test_agenda.py`.

## Turni e assenze (`/agenda/turni`, `Shifts.tsx`; migrazione `0026_turni`)
- Orario effettivo di un operatore in un giorno = `service.day_plan`: chiusura del salone (`agenda_absences` senza
  operatore) > ferie/malattia > «orario diverso» > orario settimanale (personale o del salone, con **settimane alterne**:
  `agenda_staff.working_hours_b` + `alt_week_a`), meno i **permessi** (ore di assenza). Lo usano disponibilità,
  prenotazione (anche online), spostamenti e agenda (`GET /api/agenda/orari`, ore non lavorate in grigio).
- `GET /api/agenda/turni?dal=&giorni=` griglia; `POST/PUT/DELETE /api/agenda/turni/assenze` (solo amministratore, scritte
  da `service.save_absence`): la risposta elenca gli appuntamenti già presi da spostare (`absence_conflicts`), con
  «Avvisa» su WhatsApp (wa.me) e «Apri» in agenda. Test: `tests/test_turni.py`.

## Fidelity, ricevuta non fiscale, modalità semplice
- Raccolta punti (`app/marketing/loyalty.py`, unico punto che scrive `loyalty_*` e il saldo copiato in
  `agenda_client_profiles.loyalty_points`): saldo = somma di `loyalty_moves`; accrediti con `dedupe_key` (indice unico parziale);
  premio riscattato in `agenda.service.checkout` (`reward_id`) come sconto ripartito sui servizi; «porta un'amica» con
  `agenda_client_profiles.referred_by_party_id`; tessere con contatore bloccato in `loyalty_settings`. Migrazione `0025_fidelity`.
- Ricevuta NON fiscale: `app/agenda/receipt.py` (formato neutro dell'agent) → `print.text` sulla termica o `rt.nonfiscal` sul
  registratore. Custom: **come BluOrderScan e il gestionale macellerie** (repository `Ordini-scan`, `backend/rt_custom.py`
  `build_nonfiscal` e `ponte/sof_bridge.py`): directIO `4001` dato `10`, una `4003` `1`+lunghezza+testo per riga, `4004`,
  una richiesta per comando, `resetPrinter` se un comando è rifiutato; righe ASCII da 32 caratteri (rotolo 57 mm, opzione
  `width`), senza intestazione (`rt_skip`: la stampa il registratore), in fondo «NON VALIDO COME DOC. COMMERCIALE».
  Epson: printerNonFiscal di fpmate, non ancora collaudato.
- Cassa (`/cassa`): «Copia cortesia» (F1, nella barra in alto, dopo la vendita e in «Scontrini») = copia NON fiscale
  dell'ultimo scontrino sul registratore: `POST /api/pos/scontrini/{id}/stampa` con `where: registratore` → `rt.nonfiscal`
  da `periferiche.service.text_receipt` (intestazione `rt_skip`, riga `rt_only` «NON VALIDO COME DOC. COMMERCIALE»).
- Barra in alto: `<HeaderAction>` (components.tsx) mette il pulsante principale di una pagina accanto al pacchetto
  (es. «Conferma 09:30» nel nuovo appuntamento).
- Frontend: modalità semplice predefinita (`localStorage blubeauty_semplice`) in `AppLayout`; pagine `src/pages/salone/`
  (Oggi, nuovo appuntamento a passi, incasso semplice `Pay.tsx`, stampe 80 mm e tessera `Prints.tsx`).
- Ricerca sul marketing dei concorrenti: `docs/MARKETING-CONCORRENTI.md`.

## Periferiche, fattura elettronica, super admin, Console (ereditati da BluGest, identici)
- BluBeauty Agent: `agent/blubeauty_agent.py` (driver epson_rt, custom_rt, ESC/POS, simulatori); coda `device_jobs`;
  un lavoro "inviato" non si rimanda da solo. **Custom RT = formato collaudato di BluOrderScan** sul KUBE II-F (un XML,
  unitPrice = importo di riga, IdVat letto dal registratore o `vat_ids`, subtotale, contante ricevuto, IdCmd, reset se
  rifiutato, verifica `lastIdCmd` se la risposta si perde, Z senza IdCmd + 20 s + reset; codici in `agent/rt_errors.py`).
  **Termica**: opzione `charset` (pc858 Epson con €, pc850/pc437 per le compatibili che al n. 19 stampano «piΩ», ascii);
  la stampa di prova ha la riga degli accenti. Dettagli in `docs/BLUBEAUTY.md`. DA FARE: prova con registratori veri.
- FatturaPA: `app/fatturapa/` (XML FPR12 validato sull'XSD 1.2.2, client Aruba, callback). DA FARE: prova Aruba reale.
- Pannello super admin `/admin` (aziende, periodi, rinnovo, conversione prova, moduli extra, impersonificazione, log,
  export), avvisi 30/15/7/3/1/0, Console `GET /api/console/riepilogo` e credenziali (§7–§8 di `comune/abbonamenti.md`),
  pagamenti online (`docs/PAGAMENTI.md`). Dettagli nel `CLAUDE.md` di BluGest: valgono identici qui.

## Convenzioni
- Codice in inglese; interfaccia, messaggi e documentazione in italiano. Palette e caratteri BluCode (`comune/brand.md`).
- Ogni tabella dei dati cliente ha `tenant_id` ed è in `TENANT_TABLES` (app/core/models.py) con policy RLS.
  L'app si collega col ruolo `blubeauty_app` (non proprietario), le migrazioni col ruolo `blubeauty_owner`.
- Moduli non inclusi nel pacchetto: bloccati lato server con `Depends(require_module("..."))`.
- Sola lettura (abbonamento scaduto oltre la tolleranza): `get_tenant_ctx` blocca ogni metodo diverso da GET.
- Importi `Numeric`/`Decimal`, mai float. Orari salvati con fuso, calcolati in Europe/Rome.
- Dati demo: si creano col ruolo `blubeauty_app` (seed_demo_documents), mai col proprietario.
- Migrazioni sempre esplicite: `alembic revision --autogenerate -m "..." --rev-id 00NN_nome` + policy RLS a mano.
- I test ereditati usano i pacchetti BluGest BASE/PLUS/PRO definiti SOLO in `tests/conftest.py` (`LEGACY_PLANS`).

## Comandi
- Sviluppo backend: `cd backend && alembic upgrade head && python -m app.seed --demo && uvicorn app.main:app --reload`
- Sviluppo frontend: `cd frontend && npm install && npm run dev` (proxy /api verso :8000)
- Test backend: `cd backend && python -m pytest -q` (database `blubeauty_test`) · agent: `cd agent && python -m pytest -q`
- Produzione: `docker compose up -d --build` · aggiornamento `bash deploy/update.sh` · backup `bash deploy/backup.sh`.
  Sulla VPS 80/443 sono già occupati: `HTTP_BIND` su una porta locale e proxy da nginx (come BluVitis).

## Accessi demo (SEED_DEMO=1)
- salone@demo.blubeauty.it — Aurora Hair & Beauty, SALONE annuale + fattura elettronica; prenotazione `/prenota/aurora`
- barber@demo.blubeauty.it — Barber Shop Il Baffo, AGENDA mensile, scade tra 7 giorni; `/prenota/il-baffo`
- Password: `Demo2026!`

## Stato
- [x] 2026-10-31 — fork di BluGest, pacchetti AGENDA/SALONE, moduli agenda e marketing (migrazione 0024, RLS), prenotazione
      online pubblica, incasso con registratore/fattura, interfaccia, logo e palette BluCode, demo, test (`test_agenda.py`).
- [x] 2026-10-31 — raccolta punti e tessere, ricevuta non fiscale (termica 80 mm / registratore), modalità semplice.
- [ ] Prezzi definitivi dei pacchetti (decisione del titolare) e pagina del sito (`content.py`).
- [ ] WhatsApp Business: numero del salone, modelli approvati da Meta per promemoria/marketing (`docs/WHATSAPP.md`).
- [ ] Collaudo con registratore telematico vero (Epson/Custom) e stampante termica in un salone pilota.
- [ ] Casella `blubeauty@blucodeinformatica.it` da creare su Aruba; installazione sulla VPS (DNS, nginx, certbot).
- [ ] Da valutare: pacchetti a sedute e gift card, firma su tablet dei consensi, agenda settimanale e trascinamento.

## Progetto BluCode — leggere prima di lavorare
Questo repository è BluBeauty, una parte del progetto BluCode Informatica. La memoria condivisa del progetto è il repository **`alessandrofierro50/Progetto_blucode_informatica`** (parte: `blubeauty`).
- **All'inizio di ogni sessione** leggi in quel repository `README.md`, la cartella `comune/`, `blubeauty/STATO.md` e l'ultimo file in `blubeauty/sessioni/`. Se non è collegato alla sessione, collegalo (o chiedi di farlo) prima di iniziare.
- **Standard comuni da rispettare:** nomi e colori (`comune/brand.md`), prova gratuita dal sito (`comune/prova-gratuita.md`), abbonamenti, scadenze, avvisi e collegamento con la console (`comune/abbonamenti.md`), pagamenti online e fatture degli abbonamenti (`comune/pagamenti.md`), password provvisorie sempre da cambiare al primo accesso. La fatturazione dei DDT di fine mese (`comune/fatturazione-ddt.md`) esclude BluBeauty.
- **Email:** ai clienti sempre da `info@blucodeinformatica.it` con nome «BluBeauty · BluCode Informatica»; le comunicazioni a BluCode (nuove prove, copie degli avvisi, riepilogo settimanale) vanno a `blubeauty@blucodeinformatica.it` (`ADMIN_NOTIFY_EMAIL`, casella da creare).
- **Coerenza col sito:** se cambi funzioni, prezzi, nome o stato del prodotto, segnala che va aggiornata la sua pagina (`content.py` in `sito_blucodeinformatica.it`) e annotalo in `comune/da-allineare.md`. Le decisioni che toccano più parti vanno in `comune/decisioni.md`.
- **A fine sessione**, o quando l'utente dice «salva la sessione»: nel repository di progetto scrivi `blubeauty/sessioni/AAAA-MM-GG.md` (modello `_modelli/sessione.md`; se esiste già aggiungi una sezione), aggiorna `blubeauty/STATO.md` e, se lo stato cambia, la tabella del `README.md`; poi commit e push su `main` di quel repository.
