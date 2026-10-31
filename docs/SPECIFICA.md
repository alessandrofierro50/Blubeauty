# Prompt per Claude Code — BluBeauty, gestionale SaaS multi-azienda in abbonamento

Agisci come un team senior (architetto software, sviluppatore full-stack, esperto di fiscalità italiana). Devi progettare e sviluppare **BluBeauty**, un **gestionale web in modalità SaaS**, che rivenderò in abbonamento a molte PMI italiane di settori diversi (commercio, alimentare, elettronica, artigianato, servizi). Il software è venduto **a pacchetti** (vedi sezione 2). Lavora per fasi, chiedimi conferma alla fine di ogni fase e mantieni sempre il progetto avviabile e testato.

---

## 0. Prima di scrivere codice

1. Proponimi lo **stack tecnologico** motivando la scelta. Preferenza indicativa: backend Node.js (NestJS) o Python (FastAPI/Django), database PostgreSQL, frontend React + TypeScript, avvio con Docker Compose, deploy su cloud con data center in UE.
2. Proponimi lo **schema del database** (diagramma ER testuale), la **strategia multi-tenant** (consiglio: database unico con `tenant_id` su ogni tabella e Row Level Security di PostgreSQL; valuta alternative) e la **struttura delle cartelle**.
3. Crea un file `CLAUDE.md` con convenzioni, comandi di avvio/test e stato di avanzamento delle fasi.
4. Elenca dubbi e scelte aperte e aspetta la mia risposta.

## 1. Architettura

- **Web app pura** (SPA responsive), installabile come **PWA** su PC, tablet e smartphone. Nessuna installazione richiesta per i moduli gestionali.
- **Agent locale leggero** (consiglio Tauri o un servizio Node/Go) installabile solo sulle postazioni di cassa e magazzino che usano periferiche. Il browser non può comunicare in modo affidabile con registratori telematici, stampanti di etichette e porte seriali/USB: l'agent fa da ponte (WebSocket/HTTP locale sicuro) tra la web app e le periferiche.
- Isolamento rigoroso dei dati tra aziende clienti: nessuna query deve poter leggere dati di un altro tenant (prevedi test automatici specifici).
- **Deploy iniziale su una mia VPS** già esistente (fase di test con pochi clienti), con migrazione successiva su un'infrastruttura dedicata. Quindi: tutto containerizzato con Docker Compose, reverse proxy con HTTPS automatico (es. Caddy o Traefik), configurazione solo tramite variabili d'ambiente, nessun riferimento fisso al server. Prepara uno script di installazione, uno di aggiornamento e una guida di migrazione verso un nuovo server. Backup automatici del database copiati **fuori dalla VPS** (es. object storage S3 compatibile), con prova di ripristino documentata. Monitoraggio minimo di stato del servizio e spazio disco con avviso via email.
- Conformità GDPR: hosting in UE, log degli accessi, esportazione e cancellazione dei dati di un tenant, backup giornalieri cifrati con possibilità di ripristino per singolo tenant.

---

## 2. Pannello Super Amministratore (gestione SaaS — area riservata a me)

Area separata, accessibile solo al mio account (con autenticazione a due fattori), da cui gestisco tutte le aziende clienti.

### Aziende clienti (tenant)
- Creazione, modifica, sospensione e riattivazione di un'azienda cliente; creazione del primo utente amministratore dell'azienda con invio email di attivazione.
- Dati di fatturazione del cliente (per fatturargli l'abbonamento), referente, note interne.
- Possibilità di **accedere come** un utente del cliente per assistenza (impersonificazione tracciata nel log).

### Abbonamenti
- Per ogni azienda: **pacchetto** attivo, **data inizio (dal)** e **data fine (al)**, importo, periodicità (mensile, annuale, personalizzata), stato (prova, attivo, in scadenza, scaduto, sospeso).
- Rinnovo con un clic (proroga del periodo), cambio pacchetto (upgrade/downgrade) con storico di tutti i periodi.
- Limiti configurabili per pacchetto e per singola azienda: numero di utenti, numero di aziende/ragioni sociali, magazzini, postazioni cassa.
- **Comportamento alla scadenza** configurabile: periodo di tolleranza di N giorni, poi accesso in **sola lettura** (i dati restano consultabili ed esportabili, ma non si possono emettere documenti), poi sospensione. I dati non vanno mai cancellati automaticamente.
- Banner nell'app del cliente che avvisa della scadenza imminente.

### Email automatiche di scadenza
- Job pianificato giornaliero che invia email all'azienda cliente (e una copia a me) a **30, 15, 7, 1 giorni** dalla scadenza, il giorno della scadenza e alla fine del periodo di tolleranza. Intervalli modificabili dal pannello.
- Modelli email modificabili dal pannello con segnaposto (`{ragione_sociale}`, `{data_scadenza}`, `{pacchetto}`, `{giorni_rimanenti}`, `{link_rinnovo}`).
- Invio tramite provider SMTP/transazionale configurabile; registro delle email inviate con esito, per evitare doppi invii.
- Riepilogo settimanale per me: abbonamenti in scadenza nei prossimi 30 giorni, scaduti, nuovi clienti, ricavo ricorrente.
- Predisponi (senza attivarlo ora) l'integrazione con un sistema di pagamento online (es. Stripe) per il rinnovo automatico.

### Pacchetti e moduli
I pacchetti attivano i moduli tramite **feature flag** per tenant. Le voci di menu, le API e i report dei moduli non inclusi devono essere bloccati lato server, non solo nascosti nell'interfaccia. Mostra i moduli non inclusi come "disponibili nel pacchetto superiore".

| Pacchetto | Contenuto |
|---|---|
| **Base** | Anagrafiche (clienti, fornitori, articoli), acquisti e carico di magazzino, ciclo di vendita fino al documento finale, scadenzario, solleciti e liquidità, statistiche di base |
| **Plus** | Tutto il Base + vendita al banco (POS), registratore telematico, stampanti di etichette e ticket |
| **Pro** | Tutto il Plus + statistiche avanzate e report personalizzabili |

Dal pannello posso anche attivare un singolo modulo extra su una specifica azienda.

**Moduli extra a pagamento** (in nessun pacchetto, attivabili su qualsiasi pacchetto, con prezzo proprio): fatturazione elettronica, contabilità, marketing, e-commerce, tentata vendita. Senza il modulo fatturazione elettronica le fatture si emettono e si stampano normalmente, ma non si inviano né si ricevono tramite SDI (resta disponibile l'import manuale dei file XML d'acquisto).

### Fatturazione dei miei abbonamenti
- Gli abbonamenti BluBeauty dei clienti possono essere collegati a un contratto ricorrente nell'azienda del gestore (Blucode Informatica, registrata come un normale cliente di BluBeauty): alla scadenza del periodo il sistema genera la fattura del rinnovo e la invia allo SDI, oltre all'avviso di scadenza. Così uso BluBeauty stesso per fatturare e avere il promemoria di tutti gli abbonamenti aperti e in scadenza.

### Monitoraggio
- Dashboard con numero di clienti attivi, ricavo mensile ricorrente, utilizzo (documenti emessi, spazio occupato), errori e invii SDI falliti per tenant.

---

## 3. Requisiti trasversali dell'app cliente

- Più ragioni sociali e più magazzini per azienda (entro i limiti del pacchetto).
- **Punti vendita**: ogni azienda può avere più punti vendita (negozi, filiali), ciascuno con indirizzo, casse e utenti abilitati. Ogni punto vendita scarica da un magazzino: **magazzino proprio** oppure **magazzino comune** condiviso con altri punti vendita. Giacenze visibili per magazzino e in totale, trasferimenti tra magazzini con DDT di trasferimento, documenti e statistiche filtrabili per punto vendita; l'utente lavora sul punto vendita assegnato (o sceglie tra quelli autorizzati).
- Utenti, ruoli e permessi interni all'azienda (amministratore, amministrazione, vendite, magazzino, cassa).
- Log delle modifiche su documenti e anagrafiche.
- Numerazione documenti per tipo, anno e sezionale, senza buchi.
- **Layout di stampa unico** per tutti i documenti: logo dell'azienda caricato dall'utente, intestazione (ragione sociale, indirizzo, P.IVA, contatti), colore principale, piè di pagina (dati bancari, note legali, sito); lo stesso layout si applica a cataloghi, listini, preventivi, ordini, DDT, fatture, solleciti e report, con anteprima nelle impostazioni. Un layout per ogni ragione sociale.
- Nome del prodotto **BluBeauty**, usato in interfaccia, email, PDF e pagina di accesso. Proponi un'identità visiva coerente con il nome (palette basata sul blu, logo provvisorio semplice). Rendi nome, logo e colori configurabili da un unico file, così da poterli cambiare facilmente. Ogni azienda cliente può caricare il proprio logo per i documenti stampati.
- Interfaccia in italiano, responsive, ricerca rapida ovunque (codice, descrizione, barcode).
- Import/export CSV ed Excel; procedura guidata di primo avvio con import anagrafiche dal vecchio gestionale.
- Test automatici sulle logiche critiche (calcolo IVA, movimenti di magazzino, trasformazione documenti, isolamento tenant, blocco moduli non inclusi).

---

# PACCHETTO BASE

## 4. Anagrafiche articoli (modulo centrale — curalo molto)

Prevedi quanti più campi possibile, attivabili/nascondibili per settore tramite impostazioni:

- **Identificazione**: codice interno, codice fornitore, codici a barre multipli (EAN-13, EAN-8, UPC, Code128, QR), descrizione breve ed estesa, note, immagini e allegati.
- **Classificazione**: categoria, sottocategoria, famiglia, marca, linea, tag liberi, stagione.
- **Varianti**: taglia, colore, formato, con griglia varianti e giacenza per variante.
- **Unità di misura**: UM principale e secondarie con fattore di conversione (pezzo/confezione/cartone/pallet), peso netto/lordo, volume, dimensioni.
- **Prezzi**: costo ultimo, costo medio ponderato, listini multipli, prezzi a scaglioni, sconti a cascata, ricarico e margine calcolati.
- **Fiscale**: aliquota IVA, natura di esenzione (N1–N7), nomenclatura combinata per Intrastat, flag articolo/servizio.
- **Magazzino**: scorta minima e massima, punto di riordino, ubicazione, fornitore preferito e tempi di consegna, articolo gestito/non gestito a magazzino.
- **Lotti e scadenze** (alimentare, farmaceutico, cosmetico): lotto, data di produzione, data di scadenza, giacenza per lotto, logica **FEFO**, alert sui lotti in scadenza, tracciabilità lotto → fornitore → clienti.
- **Matricole / numeri di serie** (elettronica, macchinari): matricola univoca per pezzo, obbligo di indicarla in uscita, data di vendita, **scadenza garanzia** calcolata automaticamente, storico assistenza e resi.
- **Distinta base / kit** con scarico automatico dei componenti.
- **Inventario da smartphone o palmare** (stessa web app installata come PWA, nessuna app da scaricare): apro una sessione di inventario (magazzino, ubicazione o categoria), inquadro con la fotocamera il QR code o il codice a barre dell'articolo oppure lo cerco per nome o codice, inserisco la quantità contata (tastierino grande, +/−, lotto e scadenza o matricola quando richiesti), conferma con vibrazione e suono. Più operatori possono contare in parallelo; funziona anche con rete instabile (conteggi salvati sul telefono e inviati appena c'è connessione). Alla chiusura: riepilogo differenze tra contato e giacenza teorica, articoli non contati, approvazione e generazione automatica delle rettifiche di magazzino. Stampa delle etichette QR per gli articoli che ne sono privi.
- **Schermata di revisione inventario** (da computer): elenco degli articoli della sessione con giacenza teorica, quantità contata e differenza; i conteggi arrivati dagli smartphone si possono accettare o scartare uno per uno; le quantità si possono correggere o inserire a mano direttamente in tabella; si possono importare conteggi da Excel/CSV (es. da un palmare di terze parti). Solo i conteggi accettati generano le rettifiche alla chiusura. Durante l'inventario nessuna riga viene azzerata in automatico (l'inventario può essere interrotto e ripreso): le righe contate hanno il pallino verde, quelle non contate nessun pallino. Alla chiusura il sistema chiede esplicitamente se lasciare invariate le righe non contate (inventario parziale) o azzerarle (inventario concluso).
- **Varianti taglia e colore semplici da gestire**: griglia a matrice colori × taglie, usata ovunque servano quantità di un articolo con varianti — consultazione giacenze (con totali per riga e colonna e celle evidenziate sotto scorta), carichi e scarichi, trasferimenti, inventario e righe dei documenti. Si scrivono le quantità direttamente nelle celle invece di aggiungere una riga per ogni variante.
- **Campi personalizzati** aggiungibili dall'utente (testo, numero, data, lista) senza modificare il codice.
- **Schede tecniche e allegati**: a ogni articolo si associano documenti (PDF schede tecniche, certificazioni, manuali, schede di sicurezza, foto aggiuntive) e una descrizione estesa formattata. In preventivo (e negli altri documenti di vendita) per ogni riga si sceglie se stampare la descrizione estesa e quali schede tecniche allegare: il PDF del preventivo inviato per email include in automatico le schede scelte.
- **Storico articolo (ricerca acquisti e vendite)**: dalla scheda di un articolo, o da una ricerca dedicata, si vede da quali fornitori è stato acquistato e a quali clienti è stato venduto, con data, documento, quantità, prezzo unitario d'acquisto e di vendita, sconti e margine; filtri per periodo, fornitore, cliente, variante, lotto e matricola; totali e prezzo medio; esportazione Excel. Lo stesso storico è consultabile dalla scheda cliente (cosa ha comprato) e fornitore (cosa ci ha venduto).
- **Acquistato per cliente in un periodo**: scelto un cliente e un intervallo di date, elenco degli articoli acquistati raggruppati per articolo (quantità totale, numero di acquisti, importo, prezzo medio, ultimo acquisto), con dettaglio dei singoli documenti, confronto con lo stesso periodo dell'anno precedente ed esportazione Excel/PDF.

### Prezzi personalizzati e promozioni
- **Prezzi netti per cliente** (listino personalizzato): per ogni cliente posso fissare il prezzo netto di singoli articoli (o varianti), anche a scaglioni di quantità e con validità dal/al. Gestione da una sezione dedicata (cliente → elenco articoli con prezzo netto) e dalla scheda articolo; copia dei prezzi da un cliente a un altro; aggiornamento massivo in percentuale.
- **Promozioni**: nome, periodo dal/al, articoli interessati (tutti, una o più categorie, articoli scelti), clienti interessati (tutti, una o più categorie di clienti, clienti scelti), tipo di prezzo (prezzo fisso, sconto % o sconto in euro), quantità minima; attivazione/disattivazione; elenco promozioni attive, future e scadute.
- **Categorie clienti** (es. dettaglio, ingrosso, ristorazione, enti) assegnabili in anagrafica.
- **Regola di calcolo del prezzo** in vendita: 1) prezzo netto del cliente valido alla data; 2) altrimenti il prezzo migliore tra listino del cliente (scaglioni e sconti) e promozioni attive per quel cliente e articolo; 3) sconti del cliente sul listino. Il riquadro di vendita mostra da dove arriva il prezzo (es. "Promo Natale 2026").

### Cataloghi e listini stampabili
- Costruttore di **cataloghi e listini prezzi**: scelgo categorie e articoli selezionando o deselezionando (albero categorie con caselle, ricerca, esclusione di singoli articoli), il listino o il cliente di cui mostrare i prezzi (anche con prezzi netti e promozioni), con o senza IVA, con o senza prezzi.
- Impaginazione a scelta: griglia con immagini (catalogo) oppure elenco compatto (listino); titolo, logo e dati dell'azienda, data di validità, note finali; raggruppamento per categoria.
- I cataloghi si salvano e si rigenerano aggiornati quando cambiano prezzi o articoli; esportazione PDF ed Excel e invio per email al cliente.

Anagrafiche **clienti** e **fornitori** con dati fiscali completi, codice destinatario SDI, PEC, split payment, esenzioni, condizioni di pagamento, listino e sconti, destinazioni multiple, fido. Tabelle di supporto: pagamenti, vettori, causali, aliquote IVA.

## 5. Acquisti e carico merce

1. **Inserimento manuale** di DDT o fattura d'acquisto.
2. **Import da fattura elettronica** XML FatturaPA (anche .p7m e .zip multipli): riconoscimento del fornitore, abbinamento righe-articoli tramite codice fornitore/barcode con memoria degli abbinamenti, creazione dei nuovi articoli, aggiornamento costi e listini in base al ricarico, inserimento lotti/scadenze e matricole.
3. **Abbinamento DDT di carico → fattura fornitore differita** senza doppio carico.
4. Ordini a fornitore e proposta di riordino automatica.

## 6. Ciclo di vendita

1. **Preventivo**: nessun effetto sul magazzino; stati bozza/inviato/approvato/rifiutato/scaduto; PDF e invio email.
2. **Ordine cliente**: all'approvazione il preventivo diventa ordine con un clic e **impegna le quantità**. Mostra giacenza fisica, impegnata, ordinata e disponibile. Evasione parziale e residui.
3. **Consegna**: l'ordine diventa **DDT** (scarica il magazzino, resta da fatturare) oppure **fattura immediata**. Lotti proposti in FEFO, matricole obbligatorie dove previste.
4. **Fatturazione differita**: raccolta, **per ogni cliente, di tutti i DDT non fatturati** nel periodo scelto, con anteprima e generazione delle fatture riepilogative.
5. Note di credito, resi con rientro di lotti/matricole, scadenzario incassi e pagamenti.
6. **Fido cliente**: ogni cliente ha una linea di fido (importo massimo di esposizione = fatture non pagate + DDT e ordini non ancora fatturati). Al superamento compare un messaggio e, se il cliente è impostato su "blocca", non si possono emettere altri documenti di vendita per lui (sbloccabile solo da un amministratore, con traccia nel log); con "avvisa" si può proseguire dopo conferma.
7. **Vendita di abbonamenti / canoni ricorrenti**: contratti con cliente, articoli o servizi, prezzo, periodicità (mensile, bimestrale, trimestrale, semestrale, annuale), data di inizio, eventuale data di fine o rinnovo tacito, fatturazione anticipata o posticipata. A ogni scadenza di periodo il sistema genera in automatico la nuova fattura (in bozza da controllare o già emessa e inviata allo SDI, a scelta), con la descrizione del periodo di competenza (es. "Canone dal 01/11/2026 al 30/11/2026"); adeguamento ISTAT o aumento percentuale programmabile; elenco contratti in scadenza e avviso al cliente prima del rinnovo.

Ogni documento mantiene il collegamento con quello da cui deriva.

**Riquadro informativo sulla riga di vendita**: quando si seleziona un articolo in un preventivo, ordine, DDT, fattura o al banco, compare subito un riquadro con: costo ultimo, costo medio ponderato e (se diverso) costo dell'ultimo acquisto dal fornitore preferito; prezzo di listino del cliente (con scaglioni e sconti); **ultimo prezzo praticato a quel cliente** per quell'articolo (data e documento) e gli ultimi 3-5 prezzi praticati; margine e ricarico calcolati in tempo reale sul prezzo che si sta inserendo, con avviso se si vende sotto costo; giacenza disponibile. I costi sono visibili solo ai ruoli autorizzati (non alla cassa).

## 6-bis. Scadenzario attivo e passivo, solleciti e liquidità

- Le scadenze nascono in automatico da fatture di vendita (attive) e d'acquisto, anche importate da XML (passive), secondo le rate del pagamento; possibilità di aggiungerne a mano (affitti, F24, rate, stipendi).
- Ogni scadenza: soggetto, documento, data, importo, modalità di pagamento, stato (aperta, parzialmente pagata, pagata, insoluta), incassi/pagamenti parziali con data e conto (cassa/banca).
- **Schermata unica** con tutte le scadenze attive e passive, aperte e chiuse, filtrabili per periodo, soggetto, stato, modalità, banca; totali in testa (da incassare, da pagare, scaduto, saldo).
- **Fotografia della liquidità a una data**: scelgo un giorno (anche passato) e vedo la situazione "congelata" a quella data — cosa era aperto, scaduto, incassato e pagato — più la previsione dei flussi per settimana e per mese (entrate, uscite, saldo progressivo con il saldo iniziale di cassa e banche). La fotografia si può salvare ed esportare in PDF/Excel per confronti nel tempo.
- **Solleciti di pagamento** ai clienti in ritardo: email con modelli a più livelli (cortese, secondo avviso, diffida), elenco delle fatture scadute e totale, invio singolo o massivo, invio automatico programmabile (es. 7 e 30 giorni dopo la scadenza), registro dei solleciti inviati per cliente; predisposizione per SMS/WhatsApp. Blocco o avviso in vendita per clienti insolventi o oltre il fido.
- Con il modulo Contabilità attivo, incassi e pagamenti generano le registrazioni e chiudono le partite.

## 7. Fatturazione elettronica (modulo extra a pagamento)

**Collegamento ad Aruba** (API Fatturazione Elettronica v2): di norma tramite l'utenza Premium della piattaforma, con ogni azienda cliente aggiunta come cedente (multicedente) nel pannello Aruba; in alternativa l'azienda inserisce le proprie credenziali Aruba. Callback di Aruba verso `https://<dominio>/api/fatturapa/callback/{createInvoice|createNotification|updateInvoiceStatus|updateUsage}` con api-key; in più un controllo periodico di riserva. Codice destinatario Aruba per ricevere: KRRH6B9.


- XML secondo le specifiche FatturaPA vigenti (verifica la versione aggiornata): TD01, TD02, TD04, TD05, TD24, TD25 e altri principali.
- Nature IVA, split payment, reverse charge, ritenuta d'acconto, cassa previdenziale, bollo virtuale, esigibilità IVA.
- Validazione prima dell'invio.
- Invio/ricezione tramite **Aruba Fatturazione Elettronica** (API REST di Aruba, consulta la documentazione ufficiale aggiornata per autenticazione, endpoint e gestione multi-azienda da rivenditore). Implementa l'integrazione dietro un'interfaccia astratta, così da poter aggiungere altri intermediari in futuro. Le credenziali Aruba vanno salvate cifrate, per singolo tenant. Gestione ricevute e stati (consegnata, scartata, mancata consegna) con aggiornamento automatico; ambiente di test separato da quello di produzione.
- Ricezione automatica delle fatture passive verso il modulo acquisti.
- Visualizzazione leggibile, PDF di cortesia, esportazione per conservazione sostitutiva e commercialista.

## 8. Statistiche di base

Fatturato per periodo, vendite per cliente e articolo, giacenze e valore di magazzino, lotti in scadenza, scadenzario.

### Impostazione di Business Intelligence (vale per tutte le statistiche, Base e Pro)
- **Modello a stella**: per ogni area un *fatto* (vendite = righe fatturate; poi acquisti, movimenti di magazzino, scadenze, vendite al banco) collegato a *dimensioni* condivise (tempo, cliente, articolo, categoria, marca, magazzino, documento, canale, agente).
- **Modello semantico unico**: misure definite una volta sola (fatturato, quantità, fatture, clienti, fattura media, prezzo medio; nel Pro costo, margine, margine %) e usate da tutte le schermate, dagli export e dai report: gli stessi numeri ovunque.
- **Gerarchie e drill-down**: tempo (anno → trimestre → mese → giorno), prodotto (categoria → sottocategoria → articolo), cliente (provincia → cliente → documento); **drill-through** fino alle righe dei documenti.
- **Filtri incrociati**: cliccando un elemento di un grafico tutta la dashboard si filtra; i filtri attivi sono sempre visibili e rimovibili.
- **Time intelligence**: confronto con l'anno precedente o con il periodo precedente, variazione %, periodi rapidi (mese, trimestre, anno, 12 mesi).
- **KPI** in testa con valore, confronto e tendenza; export Excel di ogni analisi.
- Sicurezza: ogni interrogazione passa dalla RLS (ogni azienda vede solo i suoi dati) e accetta solo dimensioni e misure del modello.
- **Base**: dashboard pronte, fino a 2 dimensioni per analisi. **Pro**: margini, fino a 4 dimensioni, tabelle pivot e report builder sullo stesso modello, analisi ABC, report salvati e programmati, altri fatti (acquisti, magazzino, scadenzario, banco).

---

# PACCHETTO PLUS

## 9. Vendita al banco (POS)

- Schermata touch-friendly, lettura barcode, ricerca rapida, tasti preferiti.
- Pagamenti in contanti con resto, carte, misti, buoni.
- Scarico immediato del magazzino (con lotto/matricola se richiesti).
- **Documento commerciale** tramite registratore telematico, oppure fattura al volo.
- Resi e annulli, apertura/chiusura cassa, chiusura giornaliera.
- Funzionamento tollerante a brevi cadute di rete (coda locale e sincronizzazione).

Stato (fase 3a): fatti cassa a tutto schermo, tasti rapidi e reparti, pagamenti misti con resto, fattura al banco, resi da scontrino
o senza, annullo, aperture/chiusure con quadratura, coda offline, codici bilancia, ricevuta di cortesia.
Fase 3b: promozioni di cassa (prendi N paghi M anche misti, N-esimo pezzo scontato, sconto a soglia di spesa; il meno caro
del gruppo, un pezzo in una sola promozione, la soglia sul totale già scontato), display cliente su secondo schermo, statistiche
del banco per fascia oraria, giorno, reparto, cassiere e cassa. Restano per dopo: carte fedeltà (modulo Marketing), vuoti a rendere
e buoni sconto, promozioni di cassa riservate a categorie di clienti. Lo scontrino fiscale
(documento commerciale) arriva col registratore telematico nella fase 3c; nelle statistiche il canale «Vendita al banco» è già separato.

### Modalità supermercato / alimentari (cassa veloce)
Schermata dedicata, attivabile per postazione, pensata per chi passa molti articoli al minuto:
- uso completo da tastiera e scanner, senza mouse: il cursore resta sempre sul campo codice; moltiplicatore quantità (es. `3*` poi lettura), storno ultima riga, subtotale, tasti funzione configurabili;
- **codici a peso/prezzo variabile** delle bilance (EAN che iniziano con 2: codice articolo + peso o prezzo incorporato) e collegamento diretto alla bilancia di cassa per frutta e verdura sfusa; tastiera rapida con immagini e codici PLU per i prodotti senza codice;
- **reparti** (ortofrutta, macelleria, panetteria…) per le vendite a importo libero; vuoti a rendere e buoni sconto;
- **carte fedeltà** con raccolta punti e sconti riservati, promozioni automatiche alla cassa (3x2, secondo pezzo al 50%, sconti a soglia di spesa) oltre a quelle a periodo già previste;
- display cliente con riga in corso e totale, cassetto, POS bancario integrato, pagamenti misti e buoni pasto;
- più casse in contemporanea con chiusura per cassiere, prelievi e versamenti, funzionamento senza rete con invio successivo;
- scarico di magazzino in tempo reale (con lotto FEFO per i freschi) e statistiche per reparto, fascia oraria e cassiere.

### MODULO EXTRA MARKETING — fidelity card e comunicazioni ai clienti (venduto separatamente)
- **Raccolta punti**: tessere fedeltà (codice a barre/QR stampabile o tessera virtuale sul telefono del cliente), regole punti configurabili (es. 1 punto ogni euro, punti doppi su articoli o periodi), soglie premio (buono sconto o articolo omaggio), saldo punti visibile in cassa e sullo scontrino, storico movimenti, scadenza punti a fine campagna; utilizzabile sia al banco sia in fattura.
- **Campagne di comunicazione** via **email, SMS e WhatsApp** per informare sulle promozioni in corso: scelta dei destinatari (tutti, categorie di clienti, titolari di fidelity, clienti che hanno acquistato certi articoli o categorie), modello del messaggio con segnaposto (nome, punti, scadenza promo), anteprima, invio immediato o programmato, statistiche di invio.
- **Consenso privacy (GDPR)**: si contattano solo i clienti che hanno dato il consenso marketing per quel canale, con data e origine del consenso; link di disiscrizione automatico.
- Invio tramite provider configurabili (SMTP per le email, provider SMS italiano, WhatsApp Business API), con il costo dei messaggi a carico del cliente del gestionale.

## 10. Periferiche (tramite agent locale)

- **Registratore telematico (RT)**: protocolli più diffusi (es. Epson Fiscal Print/XML, Custom, XON-XOFF); documento commerciale, chiusura giornaliera, letture, gestione errori e stato carta; modalità simulazione per i test.
- **Stampanti di etichette termiche**: ZPL (Zebra), TSPL/EPL (TSC, Godex e simili); editor di modelli con campi (descrizione, prezzo, barcode, lotto, scadenza, matricola); stampa da anagrafica, da carico merce (un'etichetta per pezzo) e massiva.
- **Stampanti ticket ESC/POS** e **scanner barcode** (tastiera e seriale).
- Pagina di configurazione e test delle periferiche per postazione.

---

# PACCHETTO PRO


Stato (fase 3c): BluBeauty Agent (Python, nessuna dipendenza obbligatoria) abbinato con un codice, connessione solo in uscita
verso il gestionale; registratori Epson FP-81 II RT / FP-90III e Custom RT in rete (documento commerciale, reso e annullo
con riferimento al documento d'origine, codice lotteria, chiusura giornaliera Z alla chiusura di cassa), stampanti termiche
ESC/POS (ricevuta di cortesia), stampanti di etichette ZPL con editor dei modelli (anche stampa su fogli A4), bilancia
seriale letta dalla cassa; senza internet la cassa stampa il documento commerciale tramite l'agent sul suo computer.
Ancora da fare: RCH Print!F (serve il manuale del protocollo), driver Windows per stampanti non ESC/POS, prove sul campo.

## 11. Statistiche avanzate e personalizzabili

Dashboard e report filtrabili per periodo, cliente, agente, categoria, articolo, magazzino, con confronto anno precedente ed export Excel/PDF:

- Fatturato e andamento; vendite per articolo, categoria, marca, cliente, zona, agente, canale (banco vs. fattura).
- **Margine e marginalità** per articolo, cliente e documento.
- Analisi ABC / Pareto di articoli e clienti.
- Articoli fermi, indice di rotazione, giorni di copertura; valore di magazzino (costo medio, ultimo, FIFO).
- Matricole in garanzia, lotti in scadenza.
- Conversione preventivi → ordini, ordini inevasi, tempi di evasione.
- Clienti inattivi, frequenza e scontrino medio.
- Insoluti e crediti per cliente; analisi acquisti e andamento costi per fornitore.
- **Report builder**: l'utente sceglie dimensioni, misure, filtri e tipo di grafico, salva il report e lo può programmare per l'invio automatico via email.
- Dashboard personalizzabile con widget trascinabili.

Stato (fase 4): fatti cinque cubi sul motore BI unico (vendite, acquisti, scadenze/crediti, preventivi e ordini, movimenti di
magazzino) con periodi relativi, confronto anno/periodo precedente, filtri, tabella pivot righe × colonne e drill-through;
report builder con salvataggio, condivisione, Excel (anche pivot), PDF dalla stampa e invio programmato via email (giornaliero,
settimanale, mensile); dashboard con riquadri dai report, trascinabili e larghi 1–4 colonne; analisi ABC di articoli, clienti e
fornitori; magazzino con valore al costo medio, ultimo costo e FIFO, rotazione, copertura, articoli fermi; clienti attivi, a rischio
e inattivi con frequenza e scontrino medio; matricole in garanzia. La dimensione «agente» delle vendite arriverà con il modulo
Tentata vendita (oggi c'è il venditore su preventivi e ordini); la «zona» è la provincia/città del cliente.

---

# MODULO EXTRA E-COMMERCE (venduto separatamente a pagamento)

## 13. Negozio online collegato al gestionale, configurabile in autonomia

- **Procedura guidata in pochi passaggi** che il cliente completa da solo: nome e dominio del negozio (sottodominio gratuito tipo `nomenegozio.blubeauty.it` o dominio proprio), logo e colori, scelta di un tema grafico, categorie e articoli da pubblicare, metodi di pagamento e spedizione, pagine legali. Il negozio è online alla fine della procedura.
- **Aspetto grafico**: temi pronti e moderni, ottimizzati per smartphone; personalizzazione con editor visuale a blocchi (banner, vetrina prodotti, categorie in evidenza, testi, immagini) senza scrivere codice; anteprima prima di pubblicare.
- **Giacenze in tempo reale**: il negozio legge la disponibilità direttamente dal magazzino del gestionale (magazzino scelto o somma di più magazzini/punti vendita), al netto delle quantità già impegnate; ogni vendita al banco, DDT o fattura aggiorna subito la disponibilità online e viceversa, così non si vende ciò che non c'è. Indicazione al cliente: disponibile, ultimi pezzi, esaurito, disponibile in un determinato negozio.
- **Catalogo sincronizzato con il gestionale**: articoli, varianti, immagini, prezzi (listino web dedicato), promozioni e giacenze disponibili arrivano in automatico; si sceglie quali categorie/articoli pubblicare (come nei cataloghi) e si possono aggiungere descrizioni e foto specifiche per il web; articoli esauriti nascosti o in "disponibile su ordinazione".
- **Ordini**: l'ordine online diventa un ordine cliente nel gestionale (impegna il magazzino), poi DDT/fattura o scontrino; il cliente web viene creato in anagrafica; email automatiche di conferma, spedizione e consegna; ritiro in negozio con scelta del punto vendita.
- **Pagamenti** con carta, PayPal, bonifico, contrassegno (Stripe/PayPal/Nexi configurabili); **spedizioni** con tariffe per peso/zona/importo e spedizione gratuita sopra soglia; codici sconto.
- Area cliente (ordini, fatture, indirizzi, punti fedeltà se attivo il modulo Marketing), carrello abbandonato con promemoria, SEO di base (URL leggibili, titoli, mappa del sito), cookie banner e privacy GDPR.
- Statistiche del negozio online integrate in quelle del gestionale (vendite per canale).

# MODULO CONTABILITÀ (modulo extra a pagamento, attivabile su qualsiasi pacchetto dal pannello super amministratore)

## 12. Contabilità generale collegata alla gestione

- **Esercizi contabili**: un esercizio per anno (anche non solare), stati aperto / in chiusura / chiuso; registrazioni sempre attribuite all'esercizio della data di registrazione; esercizio chiuso non modificabile. Chiusura e riapertura automatiche dei conti patrimoniali (scritture di chiusura, risultato d'esercizio, riapertura al 1° giorno del nuovo esercizio).
- **Piano dei conti** a tre livelli: **mastro → conto → sottoconto**, con natura (attività, passività, costi, ricavi, ordine) e collocazione nel bilancio (voci dello schema civilistico art. 2424-2425 c.c.). Piano dei conti standard precaricato per PMI, modificabile.
- **Partitari**: ogni cliente e fornitore ha il proprio sottoconto (crediti v/clienti, debiti v/fornitori), creato in automatico dall'anagrafica.
- **Collegamento con la gestione**: fatture di vendita, note di credito, fatture d'acquisto e corrispettivi del banco generano la registrazione in prima nota con causale contabile; conto di ricavo/costo proposto dall'articolo o dalla categoria, modificabile; IVA sui conti IVA vendite/acquisti. Incassi e pagamenti dallo scadenzario chiudono le partite.
- **Imputazione dei costi**: le fatture d'acquisto importate (XML) vengono imputate ai conti di costo, con memoria dell'ultimo conto usato per fornitore/articolo; possibilità di ripartire una riga su più conti; centri di costo facoltativi.
- **Prima nota** manuale con causali (giroconti, stipendi, F24, ammortamenti, ratei e risconti), controllo dare = avere obbligatorio.
- **Registri IVA** vendite, acquisti e corrispettivi; liquidazione IVA mensile o trimestrale; dati per le comunicazioni periodiche (LIPE).
- **Scadenzario** clienti/fornitori collegato alle partite contabili.
- **Report**: libro giornale, mastrini, bilancio di verifica, **bilancio d'esercizio** (stato patrimoniale e conto economico, anche riclassificati), confronto con l'esercizio precedente; esportazione PDF/Excel e per il commercialista.
- **Rappresentazione grafica semplificata e intuitiva** del bilancio, pensata per chi non è esperto:
  - stato patrimoniale come due colonne affiancate a blocchi proporzionali (impieghi: immobilizzazioni, crediti, magazzino, liquidità — fonti: patrimonio netto, debiti a lungo, debiti a breve), con indicatori semplici (liquidità, indebitamento, solidità) e semaforo verde/giallo/rosso;
  - conto economico come grafico "a cascata" dai ricavi all'utile (ricavi → costi merci → servizi → personale → ammortamenti → oneri → imposte → utile), con margini evidenziati;
  - andamento mensile di ricavi, costi e risultato, confronto con l'esercizio precedente;
  - ogni blocco è cliccabile e scende fino ai mastri, ai conti e alle singole registrazioni;
  - frasi di commento automatiche in italiano semplice (es. "I costi del personale sono cresciuti dell'8% rispetto all'anno scorso").
- Ruolo utente dedicato "contabilità".

---

# MODULO EXTRA TENTATA VENDITA (venduto separatamente a pagamento, attivabile su qualsiasi pacchetto)

## 14. Agenti con furgone: carico, giro clienti, consegna firmata, rientro e quadratura

- **Furgone = magazzino**: ogni agente ha un magazzino "furgone" (tipo mezzo, targa). La mattina si fa il **carico** dal magazzino centrale con un trasferimento (anche proposto dagli ordini da consegnare e dalla media venduta nei giri precedenti); la merce viaggia con il DDT di trasferimento/documento di accompagnamento.
- **Giro del giorno**: elenco dei clienti da visitare (per giorno della settimana, zona o ordini da consegnare), con indirizzo, navigazione sulla mappa, note, fido residuo, documenti aperti e scaduti da incassare.
- **App per tablet e smartphone** (stessa web app, pagine ottimizzate per il touch), utilizzabile **anche senza rete**: anagrafiche, prezzi, giacenze del furgone e documenti del giro scaricati sul dispositivo; le vendite si salvano in locale e si inviano appena torna la copertura (come il conteggio d'inventario), senza doppioni.
- **Documenti emessi dall'agente**: DDT (fatturazione differita in ufficio), fattura immediata, ordine da evadere in seguito, reso dal cliente e ritiro merce invenduta/scaduta; scontrino/ricevuta per i privati con registratore telematico portatile (quando saranno pronte le periferiche). Numerazione con **sezionale per agente** (es. 125/A3) così i dispositivi offline non si sovrappongono.
- **Prezzi e controlli**: motore prezzi del gestionale (listino del cliente, prezzi netti, promozioni); sconti massimi consentiti all'agente; controllo del fido (blocco o avviso) anche offline, con i dati scaricati a inizio giro; lotti in FEFO e matricole dal furgone.
- **Firma del cliente sul tablet** alla consegna: il cliente firma con il dito nello spazio sul documento, con nome di chi ritira, data, ora e posizione GPS facoltativa; la firma viene salvata con il documento e stampata su di esso (anche come prova di consegna).
- **Invio del documento firmato** subito dal dispositivo: **email** con il PDF firmato in allegato, oppure **WhatsApp** con il link sicuro al PDF (messaggio precompilato verso il numero del cliente); invio registrato nel documento. Stampa facoltativa su stampante portatile Bluetooth.
- **Incassi sul posto**: contanti, assegno, POS, con ricevuta di incasso firmata; l'incasso chiude la scadenza nello scadenzario (fase 2e) e va nel riepilogo cassa dell'agente.
- **Rientro e quadratura** a fine giro: merce caricata − venduta + resi = merce che deve rientrare; l'agente conta il furgone (anche con la fotocamera), le differenze vengono evidenziate e confermate dall'ufficio; il rimanente torna in magazzino centrale o resta sul furgone per il giorno dopo. Quadratura di cassa: incassi per tipo da versare.
- **Ufficio**: posizione dei giri in tempo reale (documenti arrivati), riepilogo giornaliero per agente (venduto, incassato, resi, km/visite), statistiche per agente/zona/cliente, provvigioni facoltative.
- Ruolo utente dedicato **"agente"**: vede solo i propri giri, il proprio furgone e i propri clienti; non vede i costi.

Stato: fatti furgoni con sezionale e sconto massimo, giro clienti per giorno, proposta di carico e carico, app dell'agente
senza rete (DDT, fattura, ordine, reso con firma, posizione, incassi, invio email/WhatsApp del PDF firmato), rientro con
stampa della merce rimasta sul mezzo, conta del magazziniere alla cieca con differenze motivate e firme di entrambi,
quadratura di cassa, riepilogo del giorno per agente, statistiche per agente e furgone. Da fare: scontrino per i privati
con registratore portatile, stampa Bluetooth, km/visite in statistica, provvigioni.

---

## Ordine di sviluppo

1. Struttura, multi-tenant, autenticazione, ruoli, **pannello super amministratore con abbonamenti, feature flag ed email di scadenza**.
2. Pacchetto Base: anagrafiche → magazzino, lotti, matricole → acquisti e import XML → ciclo di vendita → statistiche di base; subito dopo il modulo extra fatturazione elettronica.
3. Pacchetto Plus: POS → agent locale e periferiche.
4. Pacchetto Pro: statistiche avanzate e report builder.
5. Contabilità: esercizi e piano dei conti → registrazioni automatiche da documenti → prima nota e IVA → bilancio. (Le anagrafiche e i documenti delle fasi precedenti prevedono già i campi di collegamento ai conti.)
6. Modulo extra Tentata vendita: dopo lo scadenzario (gli incassi dell'agente chiudono le scadenze).

Alla fine di ogni fase: popola il database con due o tre aziende di esempio su pacchetti diversi, esegui i test, aggiorna `CLAUDE.md` e riassumimi cosa è stato fatto e cosa resta.
