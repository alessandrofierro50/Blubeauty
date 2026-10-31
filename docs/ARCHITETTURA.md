# BluBeauty — Architettura (Fase 0)

Stato: **confermata** (28/10/2026).

## 1. Stack tecnologico proposto

| Livello | Scelta | Motivo |
|---|---|---|
| Backend | **Python 3.13 + FastAPI** | Ottimo per XML FatturaPA (lxml, validazione XSD), firma .p7m (asn1crypto), statistiche e report (pandas). API veloci e documentate in automatico (OpenAPI). |
| ORM e migrazioni | SQLAlchemy 2 + Alembic | Maturo, supporta bene PostgreSQL e Row Level Security. |
| Database | **PostgreSQL 16** | Transazioni solide per magazzino e numerazioni, RLS per l'isolamento dei clienti, JSONB per i campi personalizzati. |
| Job e code | Redis + Celery (worker + beat) | Email di scadenza giornaliere, invii SDI, import XML in background, report programmati. |
| Frontend | **React + TypeScript + Vite**, TanStack Query, Mantine UI | Componenti pronti per gestionali (tabelle, form, date), tema blu facile, PWA con vite-plugin-pwa. |
| PDF | WeasyPrint (HTML → PDF) | Modelli documenti modificabili in HTML/CSS. |
| Email | SMTP o provider transazionale, via variabili d'ambiente | Cambio provider senza toccare il codice. |
| Agent locale (pacchetto Plus) | **Tauri** (Rust + interfaccia web) | Eseguibile leggero per Windows, con accesso a seriale/USB/rete per RT ed etichette. |
| Deploy | Docker Compose + **Caddy** (HTTPS automatico) | Gira identico sulla tua VPS e sul server futuro. |
| Test | pytest (backend), Vitest + Playwright (frontend) | |

## 2. Strategia multi-tenant

- **Database unico, schema unico**, colonna `tenant_id` su ogni tabella dei dati aziendali.
- **Row Level Security** di PostgreSQL: a ogni richiesta l'API imposta `SET LOCAL app.tenant_id = '<id>'` dentro la transazione; le policy filtrano automaticamente. Anche un errore nel codice non può mostrare dati di un altro cliente.
- L'utente applicativo del database **non** è proprietario delle tabelle (le policy valgono sempre). Il super amministratore usa un ruolo separato con permessi di bypass, solo per le tabelle di gestione SaaS.
- Test automatici dedicati: per ogni tabella, verificare che un tenant non legga né scriva righe di un altro.
- Alternativa scartata: un database per cliente (isolamento massimo ma migrazioni e backup molto più pesanti con molti clienti).

## 3. Schema del database (ER testuale)

### Area SaaS (gestita dal super amministratore, senza RLS di tenant)
```
tenants (id, ragione_sociale, piva, cf, email_referente, telefono, stato[attivo|sospeso],
         dati_fatturazione jsonb, note, creato_il)
plans (id, codice[BASE|PLUS|PRO], nome, prezzo_mese, prezzo_anno, limiti jsonb, moduli text[])
subscriptions (id, tenant_id→tenants, plan_id→plans, dal, al, importo, periodicita,
               stato[prova|attivo|in_scadenza|tolleranza|sola_lettura|sospeso], giorni_tolleranza,
               creato_il)                       -- storico: una riga per ogni periodo
tenant_modules (tenant_id, modulo, attivo)       -- moduli extra per singolo cliente
tenant_limits (tenant_id, max_utenti, max_ragioni_sociali, max_magazzini, max_casse)
email_templates (id, codice, oggetto, corpo_html)
reminder_rules (id, giorni_prima int)           -- 30, 15, 7, 1, 0, fine tolleranza
email_log (id, tenant_id, subscription_id, regola, destinatario, esito, inviata_il)
                                                  -- unico su (subscription_id, regola): niente doppi invii
super_admins (id, email, password_hash, totp_secret)
audit_log (id, tenant_id, utente_id, impersonato_da, entita, entita_id, azione, prima jsonb, dopo jsonb, il)
```

### Area cliente (tutte con tenant_id + RLS)
```
companies (ragioni sociali: id, tenant_id, denominazione, piva, cf, regime_fiscale, indirizzo,
           pec, logo, credenziali_sdi_cifrate)
users (id, tenant_id, email, password_hash, nome, attivo)
roles / user_roles / permissions
warehouses (id, company_id, codice, descrizione)
settings (tenant_id, chiave, valore jsonb)      -- campi articolo visibili per settore, ecc.

-- Tabelle di supporto
vat_rates (codice, aliquota, natura, descrizione)
payment_terms (codice, descrizione, rate jsonb)
carriers, causali_magazzino, units_of_measure

-- Anagrafiche
customers / suppliers (id, codice, ragione_sociale, piva, cf, codice_sdi, pec, split_payment,
           esenzione, payment_term_id, listino_id, sconti, fido, campi_custom jsonb)
addresses (soggetto_id, tipo[sede|destinazione], ...)
items (id, codice, descrizione, descrizione_estesa, categoria_id, marca_id, famiglia, linea,
       um_principale, peso_netto, peso_lordo, volume, dimensioni, vat_rate_id, natura,
       nomenclatura_combinata, tipo[articolo|servizio], gestito_magazzino,
       gestione_lotti bool, gestione_matricole bool, mesi_garanzia,
       scorta_min, scorta_max, punto_riordino, fornitore_preferito_id, lead_time_giorni,
       costo_ultimo, costo_medio, campi_custom jsonb, tag text[])
item_barcodes (item_id, variante_id, tipo, codice)
item_uom (item_id, um, fattore)
item_variants (id, item_id, taglia, colore, formato, codice)
item_suppliers (item_id, supplier_id, codice_fornitore, ultimo_costo)   -- memoria abbinamenti import XML
item_bom (item_id, componente_id, quantita)
price_lists / price_list_items (listino_id, item_id, prezzo, da_quantita)
categories, brands, custom_field_defs (entita, nome, tipo, opzioni)

-- Magazzino
lots (id, item_id, lotto, data_produzione, scadenza)
serials (id, item_id, matricola, stato, data_vendita, scadenza_garanzia, customer_id)
stock_movements (id, warehouse_id, item_id, variante_id, lot_id, serial_id, quantita(+/-),
                 costo, causale, documento_riga_id, il)
stock_balances (warehouse_id, item_id, variante_id, lot_id, fisica, impegnata, ordinata)
                 -- aggiornata in transazione con i movimenti; disponibile = fisica - impegnata

-- Documenti (tabella unica per tutti i tipi, ciclo attivo e passivo)
document_types (codice[PRV|ORC|DDT|FTI|FTD|NC|ORF|DDTF|FTF], effetto_magazzino, effetto_impegno)
numbering (company_id, tipo, anno, sezionale, ultimo_numero)   -- SELECT ... FOR UPDATE: nessun buco
documents (id, company_id, tipo, numero, sezionale, data, soggetto_id, stato,
           totali, pagamento, vettore, destinazione, origine_id, sdi_stato, sdi_id, xml_path)
document_lines (id, document_id, item_id, variante_id, descrizione, quantita, um, prezzo,
                sconti, vat_rate_id, lot_id, serial_id, origine_riga_id, qta_evasa)
document_links (da_documento_id, a_documento_id)               -- tracciabilità preventivo→ordine→DDT→fattura
payments_schedule (document_id, scadenza, importo, pagato)
sdi_messages (document_id, tipo, contenuto, ricevuto_il)
```

## 4. Struttura delle cartelle

```
blubeauty/
├── CLAUDE.md
├── docker-compose.yml          # db, redis, api, worker, beat, web, caddy
├── .env.example
├── deploy/                     # Caddyfile, install.sh, update.sh, backup.sh, MIGRAZIONE.md
├── docs/                       # SPECIFICA.md, ARCHITETTURA.md
├── backend/
│   ├── app/
│   │   ├── core/               # config, db, sicurezza, tenant context, feature flag
│   │   ├── saas/               # super admin: tenant, piani, abbonamenti, email scadenza
│   │   ├── auth/               # login, 2FA, ruoli
│   │   ├── anagrafiche/        # clienti, fornitori, articoli
│   │   ├── magazzino/          # movimenti, giacenze, lotti, matricole
│   │   ├── documenti/          # ciclo attivo e passivo, numerazioni, trasformazioni
│   │   ├── fatturapa/          # XML, validazione, import, provider SDI (Aruba)
│   │   ├── pos/                # pacchetto Plus
│   │   ├── statistiche/        # base + avanzate (Pro)
│   │   └── tasks/              # job Celery
│   ├── alembic/
│   └── tests/
├── frontend/
│   └── src/ (app cliente + area super admin, separate per rotte)
└── agent/                      # Tauri, pacchetto Plus
```

## 5. Branding
Nome, logo, colori e testi del prodotto in `frontend/src/brand.ts` e `backend/app/core/brand.py`, alimentati da variabili d'ambiente. Palette allineata al sito BluCode Informatica: blu primario #2340a8 (scuro #1a3185), inchiostro/titoli #0b2147, testo #1b2b45, grigio #4a5b75, accento azzurro #6ec1e4, accento giallo #ffc83d, sfondo #f4f7fa, bordi #c8d6e6.

## 6. Domande aperte (vedi messaggio all'utente)
1. Repository Git (GitHub) per il codice e per il deploy sulla VPS.
2. Caratteristiche della VPS (RAM, sistema operativo) e dominio da usare.
3. Primo settore di clienti di prova.
4. Prezzi indicativi dei pacchetti (servono solo come dati iniziali, modificabili dal pannello).
