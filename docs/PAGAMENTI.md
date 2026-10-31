# Pagamenti online degli abbonamenti

Rinnovo dell'abbonamento pagato dal cliente con **carta** (Stripe Checkout, con Google Pay e Apple Pay), **PayPal** o **bonifico**.
A pagamento confermato BluBeauty crea il nuovo periodo, numera la fattura `N/BG`, genera l'XML FatturaPA e la proforma PDF e li manda per email.

Contratto comune a tutti i software: `progetto_blucode_informatica/comune/pagamenti.md`. BluBeauty è il modello di riferimento:
gli altri software copiano endpoint, stati, regole fiscali e variabili `.env`.

## 1. Come funziona

```
cliente: /abbonamento o banner «Rinnova ora» o link nelle email di scadenza
   └─► /pagamento: dati di fatturazione → piano + mensile/annuale + metodo
         ├─ carta    → POST checkout → sessione Stripe Checkout → pagina di Stripe → /pagamento/esito
         │                           webhook checkout.session.completed (firmato) ─┐
         ├─ PayPal   → POST checkout → ordine PayPal (lato server) → approvazione    │
         │             → /api/pagamenti/paypal/ritorno: cattura lato server          │
         │                           webhook PAYMENT.CAPTURE.COMPLETED (verificato) ─┤
         └─ bonifico → istruzioni (intestatario, IBAN, importo, causale BLUCODE BG …) │
                       super admin: Pagamenti › «Conferma bonifico» ─────────────────┤
                                                                                      ▼
                     conferma (idempotente, una transazione): nuovo periodo, azienda riattivata,
                     numero N/BG, XML validato sull'XSD, proforma PDF
                     poi, dopo il commit: proforma al cliente, XML + riepilogo a ADMIN_NOTIFY_EMAIL,
                     con FATTURE_INVIO=sdi invio allo SDI tramite Aruba
```

- **Bonifico:** prima della conferma del super admin non esiste nulla (niente numero, XML, PDF, email, periodo). Il cliente
  vede solo le istruzioni. Nel frattempo valgono tolleranza e sola lettura dello standard.
- **Nuovo periodo:** dalla fine del periodo in corso (anche se sospeso a mano), da oggi se è già scaduto (tolleranza, sola
  lettura, sospeso) o se l'azienda è in prova (la prova si chiude a ieri e resta nello storico).
- **Importi:** sempre dal listino del pannello (Impostazioni › Pacchetti). Il browser manda solo piano, periodicità e metodo.
  Se il gestore comunica un importo diverso, il pagamento non si conferma e il pannello lo segnala.
- **Chi è sospeso o in sola lettura** può comunque aprire la pagina e pagare (`/api/app/pagamenti/*` è sempre permesso).
- Solo l'**amministratore** dell'azienda paga; dall'impersonificazione (assistenza) il checkout è bloccato.

## 2. Regole fiscali (decise dal titolare il 2026-10-29)

| Voce | Valore |
|---|---|
| Regime | forfettario `RF19`: ogni riga `AliquotaIVA 0.00`, `Natura N2.2`, dicitura di legge in `Causale` |
| Bollo | virtuale 2,00 € se l'imponibile supera 77,47 €; `BOLLO_A_CARICO=cliente` aggiunge la riga «Rimborso imposta di bollo» (N2.2) |
| Documento | `TD01`; `FPR12` per aziende e privati, `FPA12` per la PA (codice univoco ufficio di 6 caratteri) |
| Numerazione | `N/BG`, progressivo per anno solare, senza buchi (contatore `invoice_counters` nella transazione della conferma) |
| Pagamento | `MP08` carta e PayPal, `MP05` bonifico (con l'IBAN di BluCode) |
| Trasmittente | invio manuale: la P.IVA di BluCode; `FATTURE_INVIO=sdi`: Aruba (`01879020517`) |

Una fattura emessa non si cancella: si corregge con una nota di credito (TD04), per ora a mano.

## 3. Variabili `.env`

Tutte in `.env.example`. Le chiavi vanno **solo nel `.env` del server**, mai nel repository né in chat.

| Variabile | Note |
|---|---|
| `PAGAMENTI_METODI` | `carta,paypal,bonifico`. Un metodo compare solo se è elencato e ha le sue chiavi |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | senza entrambe la carta non compare |
| `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_MODE` | `sandbox` o `live` |
| `BONIFICO_INTESTATARIO`, `BONIFICO_IBAN` | anche da Impostazioni › Pagamenti; senza IBAN il bonifico non compare |
| `CEDENTE_*`, `REGIME_FISCALE` | dati di BluCode in fattura. Se mancano, il pagamento si conferma ma l'XML no: correggere e «Reinvia» |
| `BOLLO_A_CARICO` | `cliente` (predefinito) o `cedente` |
| `FATTURE_SEZIONALE` | `BG` |
| `FATTURE_INVIO` | `manuale` (predefinito) o `sdi` |
| `PUBLIC_URL` | in Docker è `https://SITE_DOMAIN`: serve per gli indirizzi di ritorno e dei webhook |

## 4. Stripe

1. Dashboard Stripe › **Sviluppatori › Chiavi API**: copia la chiave segreta (`sk_test_…` in modalità test) in `STRIPE_SECRET_KEY`.
   Meglio una **chiave con restrizioni** con permesso di scrittura solo su *Checkout Sessions*.
2. **Sviluppatori › Webhook › Aggiungi endpoint**: `https://blubeauty.blucodeinformatica.it/api/pagamenti/webhook/stripe`, eventi
   `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `checkout.session.async_payment_failed`,
   `checkout.session.expired`. Copia il **segreto di firma** (`whsec_…`) in `STRIPE_WEBHOOK_SECRET`.
3. **Impostazioni › Metodi di pagamento**: attiva Carte, **Google Pay** e **Apple Pay** (BluBeauty non limita
   `payment_method_types`, quindi Checkout mostra quelli attivi). Per Apple Pay il dominio è quello di Stripe Checkout: non serve
   verificare il dominio di BluBeauty.
4. **Impostazioni › Branding**: logo e colore `#2340a8`, nome «BluCode Informatica».

Firma dei webhook: `Stripe-Signature: t=…,v1=…`, HMAC SHA-256 di `"<t>.<corpo>"` con il segreto, tolleranza 5 minuti; gli eventi
già elaborati (`payment_events`) non si rielaborano. Prova in locale con la Stripe CLI:
`stripe listen --forward-to localhost:8000/api/pagamenti/webhook/stripe` (usa il `whsec_` che stampa) e carta di prova `4242 4242 4242 4242`.

## 5. PayPal

1. [developer.paypal.com](https://developer.paypal.com) › **Apps & Credentials** (prima *Sandbox*, poi *Live*) › crea un'app del conto
   Business: `PAYPAL_CLIENT_ID` e `PAYPAL_SECRET`.
2. Nell'app › **Webhooks › Add Webhook**: `https://blubeauty.blucodeinformatica.it/api/pagamenti/webhook/paypal`, eventi
   `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`, `CHECKOUT.ORDER.APPROVED`. Copia il **Webhook ID** in `PAYPAL_WEBHOOK_ID`.
3. `PAYPAL_MODE=sandbox` per le prove (conti di prova in *Sandbox › Accounts*), `live` in produzione.

L'ordine (`intent CAPTURE`, importo dal server) si crea lato server; al ritorno del cliente BluBeauty cattura l'ordine; la conferma
arriva dal webhook `PAYMENT.CAPTURE.COMPLETED`, verificato chiedendo a PayPal `/v1/notifications/verify-webhook-signature`.
Se il cliente chiude il browser prima del ritorno, la cattura parte dall'evento `CHECKOUT.ORDER.APPROVED`.

## 6. Bonifico

Il cliente vede intestatario, IBAN, importo e causale unica `BLUCODE BG <8 caratteri dell'id>`. Quando l'accredito arriva:
**Pannello › Pagamenti** (filtro «In attesa») › apri il pagamento › **Conferma bonifico**. «Annulla pagamento in attesa» lo chiude
senza documenti. Una nuova richiesta di bonifico con piano o periodicità diversi sostituisce quella in attesa.

## 7. Pannello del super amministratore

- **Pagamenti:** filtri per stato e metodo, ricerca (azienda, causale, fattura), export CSV; nel dettaglio: dati di fatturazione
  al momento del pagamento, periodo creato, fattura, esito email e SDI, download di XML e proforma, **Reinvia** (al cliente e/o a
  BluCode; se l'XML mancava lo rigenera con lo stesso numero).
- **Impostazioni › Pagamenti:** metodi attivi, IBAN e intestatario, bollo, stato delle chiavi, dati del cedente, indirizzi dei webhook.
- **Console (§7):** `incassato` = canoni dei pagamenti «pagato» alla data del pagamento (senza il rimborso del bollo); i periodi
  inseriti a mano dal pannello restano contati alla data di inizio.

## 8. Dati e sicurezza

- `payments` (dati del cliente, RLS): importi, metodo, stato, riferimenti del gestore, copia dei dati di fatturazione, periodo creato,
  fattura (numero, anno, sezionale, XML, PDF, stato SDI), email.
- Tabelle di sistema senza RLS: `payment_routes` (indice per webhook, pannello e console), `payment_events` (eventi già visti),
  `invoice_counters` (numerazione).
- Nessun dato della carta passa da BluBeauty. Checkout limitato a 10 tentativi l'ora per azienda e per IP. I webhook di un gestore
  senza chiavi rispondono 404. Le chiavi non escono mai dalle API (il pannello mostra solo se sono impostate).
- Codice: `backend/app/pagamenti/` — `service.py` è l'**unico punto che scrive** pagamenti, numeri di fattura e periodi nati da un
  pagamento; `providers.py` (Stripe/PayPal via httpx), `invoice.py` (importi, numerazione, XML), `pdf.py` (proforma),
  `billing.py` (validazione dei dati), `router.py` (API). Test: `backend/tests/test_pagamenti.py`.

## 9. Checklist per andare in produzione

1. Account **Stripe** e conto **PayPal Business** intestati a BluCode e collegati all'IBAN aziendale (verifica dell'identità completata).
2. Prova completa in modalità test/sandbox su un'azienda di prova: carta, PayPal, bonifico confermato e annullato; controlla le email
   e carica un XML di prova sul portale (o validalo con un controllo online) prima della prima fattura vera.
3. Nel `.env` del server: `CEDENTE_*`, `BONIFICO_IBAN`, chiavi **live** di Stripe e PayPal, `PAYPAL_MODE=live`, i due segreti dei
   webhook di produzione. Poi `bash deploy/update.sh` (esegue la migrazione `0023_pagamenti`).
4. Pannello › Impostazioni › Pagamenti: tutti i metodi «attivo», nessun avviso sul cedente, indirizzi dei webhook uguali a quelli
   registrati in Stripe e PayPal.
5. Prezzi del listino (Impostazioni › Pacchetti) definitivi, mensili e annuali.
6. Primo pagamento vero di importo basso, poi rimborso dalla dashboard del gestore e nota di credito a mano.
7. `FATTURE_INVIO=sdi` solo quando BluCode è cedente abilitato sull'utenza Aruba (`ARUBA_*`): fino ad allora l'XML si carica a mano.
8. Sul sito: pulsante «Acquista» → prova gratuita, e termini di utilizzo §4 aggiornati (PR #4 del sito).
