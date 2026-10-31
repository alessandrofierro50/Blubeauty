# BluBeauty — note di progetto

Gestionale SaaS multi-azienda per PMI italiane, venduto in abbonamento a pacchetti (Base, Plus, Pro) più moduli extra a pagamento.
Specifica completa: `docs/SPECIFICA.md`. Architettura: `docs/ARCHITETTURA.md`.
Produzione: https://blubeauty.blucodeinformatica.it (VPS 217.76.158.224, installazione in `/opt/blubeauty`).

## Convenzioni
- Codice in inglese; interfaccia, messaggi e documentazione in italiano.
- Ogni tabella dei dati cliente ha `tenant_id` ed è in `TENANT_TABLES` (app/core/models.py) con policy RLS.
  L'app si collega col ruolo `blubeauty_app` (non proprietario), le migrazioni col ruolo `blubeauty_owner`.
- Per lavorare sui dati di un cliente: `set_tenant(db, tenant_id)` nella transazione (lo fa già `get_tenant_ctx`).
- Moduli non inclusi nel pacchetto: bloccati lato server con `Depends(require_module("..."))`.
- Sola lettura (abbonamento scaduto oltre la tolleranza): `get_tenant_ctx` blocca ogni metodo diverso da GET.
- Movimenti di magazzino e numerazioni sempre in transazione. Importi `Numeric`/`Decimal`, mai float.
- Dati demo dei documenti: si creano col ruolo `blubeauty_app` (seed_demo_documents), mai col proprietario,
  perché molte ricerche si affidano alla RLS e col proprietario vedrebbero tutte le aziende.
- Configurazione solo da variabili d'ambiente (`.env`, vedi `.env.example`).
- Migrazioni sempre esplicite (mai `create_all`): `alembic revision --autogenerate -m "..." --rev-id 00NN_nome`,
  controllare il file e aggiungere la policy RLS per le nuove tabelle cliente (i GRANT arrivano dai default privileges).

## Comandi
- Sviluppo backend: `cd backend && alembic upgrade head && python -m app.seed --demo && uvicorn app.main:app --reload`
- Sviluppo frontend: `cd frontend && npm install && npm run dev` (proxy /api verso :8000)
- Test backend: `cd backend && python -m pytest -q` (usa il database `blubeauty_test`) · agent: `cd agent && python -m pytest -q`
- Produzione: `docker compose up -d --build` · aggiornamento `bash deploy/update.sh` · backup `bash deploy/backup.sh`

## Accessi demo (SEED_DEMO=1)
- abbigliamento@demo.blubeauty.it — Moda Bella Boutique, pacchetto PLUS, scade tra 25 giorni
- panetteria@demo.blubeauty.it — Panificio Il Forno Antico, BASE mensile, scade tra 7 giorni
- ferramenta@demo.blubeauty.it — Ferramenta Rossi, PRO annuale (con fatturazione elettronica e tentata vendita)
- agente@demo.blubeauty.it (agente, furgone F1) e magazzino@demo.blubeauty.it (magazzino) — Ferramenta Rossi
- Password di tutti: `Demo2026!`

## Stato delle fasi
- [x] Fase 0 — architettura
- [x] Fase 1 — multi-tenant con RLS, accesso utenti, pannello super admin (aziende, abbonamenti dal/al,
      rinnovo, cambio pacchetto, moduli extra, limiti, impersonificazione, log), email di scadenza, riepilogo settimanale,
      deploy Docker + Caddy. Allineato allo standard comune (progetto_blucode_informatica/comune/abbonamenti.md):
      avvisi 30/15/7/3/1/0 + fine tolleranza («da domani sola lettura») + sospensione, prova 3/1/0 + «prova_scaduta»
      (unici per periodo e regola in `email_log`; recupera solo il più vicino); prova finita = subito sospesa (402
      `prova_scaduta`), sospesi e sola lettura possono sempre /api/auth/me, /api/auth/password, /api/app/status e
      /api/app/abbonamento (pagina «Abbonamento» del cliente: piano, stato, uso/limiti, storico, contatti).
      Tolleranza, sola lettura e giorni di avviso della prova predefiniti in `saas_settings` (Impostazioni › Avvisi).
      Pannello: Converti prova (POST /tenants/{id}/convert-trial), modifica periodo, export aziende CSV/Excel.
      BluCode Console (app/saas/console.py): GET /api/console/riepilogo (CONSOLE_API_KEY) e
      POST /api/console/super-admin/credenziali (+ CONSOLE_ADMIN_KEY): le sessioni del super admin si invalidano
      con `super_admins.token_version` (claim "ver" del JWT, anche nelle impersonificazioni).
      Email ai clienti da info@blucodeinformatica.it «BluBeauty · BluCode Informatica»; copie a ADMIN_NOTIFY_EMAIL.
- [x] Fase 2 — pacchetto Base, a passi:
  - [x] 2a anagrafiche: tabelle (IVA, pagamenti, UM, categorie, marche, listini, campi personalizzati),
        articoli (varianti, barcode, UM secondarie, scaglioni e sconti, fornitori, kit, lotti/matricole),
        clienti/fornitori (validazione P.IVA/CF/SDI, destinazioni, fido con blocco/avviso), import/export CSV,
        immagini articoli, prezzi netti per cliente, promozioni, categorie clienti, motore prezzi
        (app/anagrafiche/price_engine.py: usarlo in vendite e POS), cataloghi/listini stampabili
  - [x] 2b magazzino: movimenti, giacenze per magazzino/variante/lotto, FEFO, matricole e garanzia,
        inventario da smartphone con fotocamera (QR/barcode), rettifiche; punti vendita con magazzino
        proprio o comune, trasferimenti tra magazzini (app/magazzino/service.py: unico punto che scrive
        movimenti e giacenze; usarlo da acquisti, vendite e POS). Anche: allegati/schede tecniche articoli,
        dati azienda con logo e layout di stampa unico (frontend: PrintHeader/PrintFooter in CompanySettings.tsx)
  - [x] 2c acquisti: ordini fornitore (evasione parziale), DDT/fatture/note di credito manuali, fattura da DDT,
        import XML/p7m/zip con abbinamento righe ricordato per fornitore, aggiornamento costi, proposta di riordino
        (app/documenti/: modelli Document/DocumentLine comuni anche alle vendite; service.py numerazioni e totali)
  - [x] 2d vendite: preventivo → ordine (impegno) → DDT/fattura, fatturazione differita, note di credito;
        riquadro prezzi sulla riga (costi, listino, ultimo prezzo al cliente, margine), controllo fido,
        contratti/canoni ricorrenti con fattura automatica (job Celery 6:13), storico articolo e acquistato per cliente,
        stampa con intestazione unica e schede tecniche (app/documenti/vendite_service.py: conferma, annullo, fido, canoni).
        Fatture immediate, differite e note di credito hanno un'unica numerazione ("FT") in ordine di data.
        `Document.settled` (incassata) è provvisorio: dalla 2e lo aggiorna lo scadenzario (anche per il fido).
  - [x] 2e scadenzario (modulo `scadenzario`, nel Base): scadenze automatiche da FTI/FTD/NC/FTF/NCF (rate del pagamento,
        o DatiPagamento dell'XML; ritenuta e split payment esclusi), manuali anche ripetute, incassi/pagamenti parziali
        su conti cassa/banca, insoluti; fotografia della liquidità a una data (anche passata) con previsione
        settimanale/mensile, salvabile ed esportabile in Excel; solleciti a 3 livelli (email, WhatsApp via wa.me),
        automatici col job Celery 9:23; blocco/avviso in vendita per insolventi. Il fido usa le rate aperte.
        app/scadenzario/service.py è l'unico punto che scrive scadenze e pagamenti (`backfill` crea quelle mancanti).
  - [x] 2f fatturazione elettronica (modulo extra `fatturapa`, NON nei pacchetti; l'import manuale XML resta nel Base):
        app/fatturapa/xml_builder.py genera FPR12/FPA12 (TD01, TD24 con DatiDDT, TD04 con fatture collegate) e valida
        sull'XSD ufficiale 1.2.2 in app/fatturapa/xsd (offline); aruba.py client API v2 (token in Redis: 1 login/min per IP);
        service.py invio, verifica dryRun, stati, notifiche, fatture ricevute; callback /api/fatturapa/callback/<metodo>
        con header Authorization = ARUBA_CALLBACK_KEY, azienda ricavata da `einvoice_routes` (tabella di sistema senza RLS).
        Credenziali: utenza Premium della piattaforma (ARUBA_*) o account proprio dell'azienda (cifrato con SECRET_KEY).
        Job Celery ogni 20 min (stati + fatture ricevute). DA FARE: prova reale nell'ambiente demo Aruba con credenziali vere.
  - [x] 2g statistiche di base (app/statistiche/router.py): fatturato per periodo e mese con confronto anno precedente,
        clienti, articoli e categorie, DDT da fatturare, acquisti; magazzino (valore al costo medio, sotto scorta,
        negativi, lotti in scadenza); Excel; numeri principali in Home. Fatturato = FTI + FTD − NC, imponibile.
        Impostazione BI (SPECIFICA §8): fatto vendite = vista `bi_sales` (security_invoker, RLS) e modello semantico
        in app/bi/cube.py (dimensioni, gerarchie, misure; filtri, confronto temporale, drill-through). Nuove analisi e il
        report builder del Pro si costruiscono SOLO su questo modello (nuovi fatti = nuove viste bi_*).
- [x] Fase 3 — pacchetto Plus: POS, agent locale, periferiche
  - [x] 3a vendita al banco (modulo `pos`): casse con magazzino/listino/conti e tasti rapidi, reparti, modalità negozio (touch)
        e supermercato (tastiera, `3*codice`, F2–F12, reparti in centesimi); codici bilancia EAN-13 a peso/prezzo (AppSetting "pos");
        scontrini "SCO" e resi "RSO" = Document con `prices_vat_included` (IVA scorporata per aliquota), `client_uuid` idempotente
        per la coda offline del browser; pagamenti misti in `pos_payments` (resto solo sul contante) che entrano nel saldo dei conti;
        fattura al banco = FTI già incassata; aperture/chiusure con fondo, prelievi/versamenti, X e Z, quadratura del contante.
        app/pos/service.py è l'unico punto che scrive scontrini e sessioni; frontend a tutto schermo su /cassa (fuori da AppLayout).
        Ricevuta di cortesia 80 mm via window.print: lo scontrino fiscale vero arriva dal registratore nella 3c.
  - [x] 3b promozioni di cassa e statistiche del banco: `Promotion.mechanic` = prezzo (come prima, vale ovunque) | nxm (prendi N
        paghi M) | nesimo (N-esimo pezzo scontato %) | soglia (spesa minima → sconto % o €); solo per tutti i clienti e solo al banco.
        Motore in app/pos/promos.py e gemello in frontend/src/pages/pos/promos.ts: casi condivisi in
        backend/tests/fixtures/pos_promos.json (`npm run check:promos`, eseguito anche da pytest). Il server ricalcola sempre e fa fede:
        righe di sconto negative per aliquota (price_source "Promo cassa"), quelle mandate dal client si ignorano.
        Display cliente /cassa/:id/display (BroadcastChannel, stesso computer). Vista bi_sales (0016) con reparto, cassa, cassiere,
        ora di vendita (Europe/Rome) e is_promo; dimensioni reparto/cassa/cassiere/fascia_oraria e misura sconti_promo;
        Statistiche › Vendita al banco.
  - [x] 3c periferiche (modulo `periferiche`): BluBeauty Agent in agent/blubeauty_agent.py (solo libreria standard; test:
        `cd agent && python -m pytest -q`) sul computer del negozio. Abbinamento con codice (tabella di sistema `agent_keys`,
        solo impronte SHA-256), poi l'agent chiede i lavori al server (long-poll /api/agent/lavori, connessione in uscita).
        Driver: epson_rt (XML fpmate.cgi), custom_rt (XML /xml/printer.htm), simulatori, ESC/POS e ZPL in rete o su Windows,
        bilancia seriale. Lavori in `device_jobs` (app/periferiche/service.py è l'unico punto che li crea e registra gli esiti:
        documento commerciale in Document.fiscal["rt"], Z nell'apertura di cassa). Un lavoro "inviato" non si rimanda da solo
        (niente doppi scontrini). Senza internet la cassa stampa tramite il servizio locale dell'agent (127.0.0.1:8765,
        chiave locale + origine consentita) e manda l'esito con lo scontrino in coda (`rt_result`). Etichette: modelli in mm
        (app/periferiche/labels.py → ZPL; stessa grafica in HTML per l'editor, i fogli A4 e le termiche installate sul computer,
        una pagina per etichetta; la scelta della stampante resta nel browser). RCH Print!F non ancora supportato:
        serve il manuale del protocollo (area riservata RCH). DA FARE: prova con registratori veri prima dell'uso in negozio.
- [x] Fase 4 — pacchetto Pro (modulo `statistiche_avanzate`; ruoli amministratore/amministrazione/contabilita, `is_pro`):
      motore BI generico app/bi/engine.py (Cube/Dimension/Measure/Query: execute, detail, values, to_excel, confronto, pivot);
      cubi in app/bi/cube.py (vendite = bi_sales, anche nel Base) e app/bi/facts.py (acquisti, scadenze, ordini, magazzino:
      viste bi_* della 0018, security_invoker) con registro `CUBES`; periodi relativi in periods.py. Report salvati e dashboard
      (`saved_reports`, `dashboards`, RLS) in models.py/reports.py, invio programmato via email con Excel (job Celery 7:41);
      analisi ABC, magazzino (costo medio/ultimo/FIFO, rotazione, copertura, fermi), clienti inattivi, garanzie in analyses.py.
      Demo per i PRO in app/bi/demo.py. Frontend: pages/statistiche/ReportView (KPI, pivot, grafici), ReportBuilder, Dashboards, Analyses.
- [ ] Fase 5 — modulo extra Contabilità: esercizi, piano dei conti, registrazioni automatiche, prima nota,
      IVA, bilancio con rappresentazione grafica semplificata (vedi SPECIFICA §12)
- [ ] Modulo extra Marketing: fidelity card e raccolta punti, campagne email/SMS/WhatsApp con consenso GDPR
- [ ] Modulo extra E-commerce: negozio online configurabile in autonomia, sincronizzato con il gestionale (SPECIFICA §13)
- [x] Modulo extra Tentata vendita (modulo `tentata_vendita`, app/tentata/): furgone = magazzino dedicato (`vans`, sezionale
      documenti es. 12/A1, sconto massimo, agente), giro clienti abituale per giorno (`van_route_stops`), giro del giorno
      (`van_trips`: preparazione → in_corso → rientro → chiuso) con proposta di carico (ordini da consegnare + media dei giri) e
      carico = trasferimento. Pacchetto offline (/giri/{id}/pacchetto: clienti con fido/scadenze/ordini, merce a bordo, prezzi
      per cliente dal motore prezzi, niente costi). App agente /giro (fuori da AppLayout): DDT/FTI/ORC/NC con firma su canvas
      (PNG in media, `Document.delivery`), GPS, incasso sul posto (`van_collections` → scadenzario), coda locale con
      `client_uuid` idempotente, invio email con PDF (reportlab, app/tentata/pdf.py) o WhatsApp con link firmato
      /api/tentata/pdf/{token}. Rientro: l'agente dichiara km, contanti/assegni e firma, stampa la merce rimasta sul mezzo;
      il magazziniere conta (alla cieca se `blind_count`: le righe che non tornano arrivano col 409 `differenze_da_motivare`),
      ogni differenza ha un motivo → rettifica sul furgone, poi il rimanente rientra o resta; l'atteso = giacenza del furgone
      riallineata fino alla chiusura. app/tentata/service.py è l'unico punto che scrive furgoni, giri, documenti dell'agente,
      incassi e rientri. bi_sales (0019) ha canale "furgone", furgone e agente (anche per le FTD nate dai DDT dell'agente).
      Demo: Ferramenta Rossi con agente@demo.blubeauty.it (agente) e magazzino@demo.blubeauty.it (magazzino).
      DA FARE: scontrino per i privati con registratore portatile, stampante Bluetooth, provvigioni.
- [x] Accessi: password provvisoria alla creazione dell'azienda (vista e modificabile dal super admin, generata da
      app/auth/passwords.py, email «credenziali_accesso»), `User.must_change_password` → cambio obbligatorio al primo accesso
      (ForcedChange in AppLayout; lato server `get_tenant_ctx` risponde 403 `cambio_password` a tutto tranne me/password/status),
      per ogni password provvisoria: creazione azienda, super admin (rigenera) e amministratore dell'azienda
      (POST /api/app/users/{id}/password); recupero «password dimenticata» per utenti e super admin
      (link 1 h, solo SHA-256 nel DB, funzione SECURITY DEFINER `auth_find_reset`); cambio password e verifica in due passaggi
      del super admin in Impostazioni › Il mio account. Limiti di tentativi (Redis, `RATE_LIMITS=0` nei test).
      Prova gratuita dal sito: POST /api/public/prova (app/saas/public_router.py) crea l'azienda in prova (TRIAL_PLAN,
      TRIAL_DAYS=7 come sul sito, TRIAL_EXTRA_MODULES) e manda le credenziali solo per email; campo trappola, tempo minimo,
      CORS per WEBSITE_URL. Contratto comune a tutti i software (progetto_blucode_informatica/comune/prova-gratuita.md):
      `terms` + `terms_version` obbligatori (= TERMS_VERSION), accettazione salvata su `tenants.terms_*` (0021);
      l'email delle credenziali cita i termini (TERMS_URL?v=) e allega il PDF scaricato da TERMS_PDF_URL (10 s; se non
      arriva parte col solo link). Pagina /blubeauty/prova/ nel repository sito_blucodeinformatica.it, ripiego /prova in BluBeauty.
- [x] Pagamenti online degli abbonamenti (app/pagamenti/, contratto comune progetto_blucode_informatica/comune/pagamenti.md,
      guida docs/PAGAMENTI.md): carta con Stripe Checkout (anche Google Pay e Apple Pay, `payment_method_types` non limitato),
      PayPal (ordine e cattura lato server, Orders v2) e bonifico, mensile o annuale, con «Rinnova ora» nel banner, nella pagina
      «Abbonamento» e nelle email di scadenza (`{link_rinnovo}` = /pagamento). Stripe e PayPal via httpx (`providers._transport`
      nei test). Dati di fatturazione obbligatori su `tenants.billing_data` (P.IVA con controllo, CF, codice destinatario o PEC;
      privati 0000000; PA codice ufficio a 6). Importi sempre dal listino; checkout 10/ora per azienda e IP; impersonificazione no.
      Conferma idempotente (FOR UPDATE) da webhook firmato (Stripe HMAC 5 min, PayPal verify-webhook-signature; eventi in
      `payment_events`) o «Conferma bonifico» del super admin: nuovo periodo (dalla fine del corrente, da oggi se scaduto/prova),
      riattivazione, numero `N/BG` da `invoice_counters` (UPSERT nella transazione: per anno, senza buchi), XML FatturaPA RF19
      (N2.2, bollo virtuale oltre 77,47 € con riga «Rimborso imposta di bollo» se BOLLO_A_CARICO=cliente, FPA12 per la PA,
      MP08/MP05) validato sull'XSD, proforma PDF; dopo il commit email al cliente e XML a ADMIN_NOTIFY_EMAIL.
      **Bonifico: prima della conferma nessun documento.** FATTURE_INVIO=sdi invia con ArubaClient (spento di default).
      `payments` ha RLS; `payment_routes` (indice per webhook, pannello e console), `payment_events`, `invoice_counters` sono
      di sistema. app/pagamenti/service.py è l'unico punto che scrive pagamenti, fatture e periodi nati da un pagamento.
      Console §7: `incassato` = pagamenti «pagato» alla data del pagamento (i periodi manuali restano alla data di inizio).
      Migrazione 0023_pagamenti. DA FARE: account Stripe e PayPal Business, chiavi e webhook nel .env, prova in test/sandbox.
- Moduli extra (`fatturapa`, `contabilita`, `marketing`, `ecommerce`, `tentata_vendita`; elenco in `logic.EXTRA_MODULES`) non sono in nessun pacchetto: si attivano per cliente dal pannello.

## Progetto BluCode — leggere prima di lavorare
Questo repository è BluBeauty, una parte del progetto BluCode Informatica. La memoria condivisa del progetto è il repository **`alessandrofierro50/Progetto_blucode_informatica`** (parte: `blubeauty`).
- **All'inizio di ogni sessione** leggi in quel repository `README.md`, la cartella `comune/`, `blubeauty/STATO.md` e l'ultimo file in `blubeauty/sessioni/`. Se non è collegato alla sessione, collegalo (o chiedi di farlo) prima di iniziare.
- **Standard comuni da rispettare:** nomi e colori (`comune/brand.md`), prova gratuita dal sito (`comune/prova-gratuita.md`), abbonamenti, scadenze, avvisi e collegamento con la console (`comune/abbonamenti.md`), pagamenti online e fatture degli abbonamenti (`comune/pagamenti.md`), fatturazione dei DDT di fine mese (`comune/fatturazione-ddt.md`, in BluBeauty: pagina /vendite/fatturazione-ddt, GET /api/vendite/fatturazione-ddt), password provvisorie sempre da cambiare al primo accesso.
- **Email:** ai clienti sempre da `info@blucodeinformatica.it` con nome «BluBeauty · BluCode Informatica»; le comunicazioni a BluCode (nuove prove, copie degli avvisi, riepilogo settimanale) vanno a `blubeauty@blucodeinformatica.it` (`ADMIN_NOTIFY_EMAIL`).
- **Coerenza col sito:** se cambi funzioni, prezzi, nome o stato del prodotto, segnala che va aggiornata la sua pagina (`content.py` in `sito_blucodeinformatica.it`) e annotalo in `comune/da-allineare.md`. Le decisioni che toccano più parti vanno in `comune/decisioni.md`.
- **A fine sessione**, o quando l'utente dice «salva la sessione»: nel repository di progetto scrivi `blubeauty/sessioni/AAAA-MM-GG.md` (modello `_modelli/sessione.md`; se esiste già aggiungi una sezione), aggiorna `blubeauty/STATO.md` e, se lo stato cambia, la tabella del `README.md`; poi commit e push su `main` di quel repository.
