# BluBeauty — funzioni

> Aggiornato al 2026-10-31. Base tecnica e funzioni comuni: `SPECIFICA.md` e `ARCHITETTURA.md` (BluGest).

## Pacchetti (prezzi provvisori)

| Pacchetto | Prezzo | Cosa comprende |
|---|---|---|
| **Agenda** | 19 €/mese · 190 €/anno | Agenda, prenotazione online da smartphone, conferme/promemoria/disdette WhatsApp, schede clienti, statistiche di base |
| **Salone** | 39 €/mese · 390 €/anno | Agenda + cassa con registratore telematico e stampante termica, prodotti e magazzino, acquisti, fatture, scadenzario, marketing WhatsApp |
| Extra | da listino | Fattura elettronica con invio allo SDI (Aruba) |

Prova gratuita dal sito: 7 giorni sul pacchetto Salone.

## Modalità semplice (predefinita)
Pensata per chi usa poco il computer: menu con sei voci grandi (Oggi, Nuovo appuntamento, Agenda, Clienti, Messaggi e punti,
Cassa), parole semplici, opzioni avanzate nascoste. La schermata **Oggi** mostra gli appuntamenti del giorno come schede grandi
con i pulsanti «È arrivata», «Incassa» e «Ricevuta». Il **nuovo appuntamento** è a passi: Per chi? → Cosa? → Con chi? → Quando?
L'**incasso** è un tocco su Contanti / Carta / Bancomat (la cassa si apre da sola se è chiusa); il premio fedeltà disponibile è
proposto in evidenza. L'interruttore «Mostra tutte le funzioni» riporta al gestionale completo.

## Agenda
- Una colonna per operatore, giorno per giorno; orari del salone e turni personali (più fasce al giorno).
- **Tempi di posa**: durante la posa del colore l'operatore è libero e può servire un altro cliente; in agenda la posa è a righe e gli appuntamenti sovrapposti si affiancano.
- **Cabine e macchinari**: un servizio (es. pressoterapia, laser) si prenota solo se una cabina è libera per tutta la durata.
- Nuovo appuntamento sugli orari davvero liberi; più servizi in sequenza; spostamento con nuovo controllo.
- Stati: prenotato → confermato → in salone → concluso → pagato; disdetto, non presentato.

## Prenotazione online (smartphone)
- Pagina pubblica `/prenota/<nome-salone>` in stile app, installabile sulla schermata Home: servizio → operatore (o «prima disponibile») → giorno e orario → nome, cellulare, consensi → conferma.
- Il cliente si riconosce dal cellulare (niente doppioni in anagrafica). Conferma su WhatsApp con link personale.
- Dal link personale il cliente vede l'appuntamento e **lo disdice da solo** fino a N ore prima (24 predefinite).
- Anticipo minimo, giorni prenotabili e servizi/operatori prenotabili online si scelgono dalle impostazioni. Link e QR code per Instagram, Google, WhatsApp e vetrina.

## Clienti
- Consensi privacy e marketing con data, compleanno, note, punti fedeltà (1 punto per euro pagato).
- Schede tecniche: formula colore, trattamento, anamnesi, consenso informato (firmato).
- Storico appuntamenti e conversazione WhatsApp. Dati di fatturazione nell'anagrafica comune.

## Cassa e fisco
- Dall'appuntamento: «Cliente arrivato», poi **Incassa**: servizi già inseriti, prodotti venduti dal catalogo, sconto, metodo di pagamento.
- **Scontrino**: documento commerciale emesso dal registratore telematico (Epson o Custom) tramite BluBeauty Agent sul computer della cassa; senza internet la cassa usa l'agent locale.
- **Fattura**: fattura già incassata; con il modulo extra si invia allo SDI tramite Aruba (XML FatturaPA validato).
- Aperture e chiusure di cassa, chiusura Z, ricevuta di cortesia sulla stampante termica: come la vendita al banco di BluGest.

## Raccolta punti e tessere fedeltà (pacchetto Salone)
- Punti per ogni euro pagato (regola modificabile), premi a soglia: sconto in euro, sconto in percentuale, servizio omaggio.
- Il premio si usa in cassa con un tocco; i punti si scalano e si accumulano sul pagato.
- Tessera con numero progressivo e codice a barre, stampabile in formato carta di credito; si ritrova col lettore.
- «Porta un'amica»: chi presenta una nuova cliente riceve punti alla sua prima visita pagata.
- Punti di benvenuto alla consegna della tessera, correzioni manuali con motivo, storico dei movimenti.
- Messaggio WhatsApp automatico quando la cliente raggiunge un premio.

## Ricevuta non fiscale
- Prima dell'incasso vale come promemoria/preconto, dopo come ricevuta: servizi, prodotti, totale, numero dello scontrino
  fiscale, punti e premio più vicino, tessera (codice a barre), prossimo appuntamento, QR per prenotare dal telefono.
- Si stampa sulla **stampante termica da 80 mm** (ESC/POS, tramite BluBeauty Agent), sul **registratore telematico come
  documento non fiscale** o dal computer (pagina 80 mm). Sul registratore Custom si usa lo stesso metodo di BluOrderScan e del
  gestionale macellerie (comandi 4001/4003/4004, già usati sul KUBE II): testo semplice da 32 caratteri, intestazione stampata
  dal registratore, senza la dicitura «non valido come documento commerciale» (tolta dal titolare il 2026-11-01).
  Su Epson il documento non fiscale è da collaudare.

## Registratore Custom e stampante termica: esperienza di BluOrderScan
Il primo scontrino reale su un Custom KUBE II-F è uscito in BluOrderScan dopo diverse prove; BluBeauty Agent
(`agent/blubeauty_agent.py`, classe `CustomRT`) usa esattamente lo stesso formato:
- POST `http://<IP>/xml/printer.htm`, `Content-Type: text/plain`, utente e password Basic o Digest; connessione ritentata
  3 volte (subito dopo una stampa il registratore rifiuta connessioni per qualche secondo); attesa della risposta 120 s.
- Scontrino = un solo XML: `printRecItem` con `unitPrice` = importo della **riga** (quantità × prezzo, sconto già dentro) e
  `IdVat`; la quantità in un `printRecMessage` («2 x 15,00 EUR»), lo sconto in «Sconto 3,00 EUR»; `printRecSubtotal`;
  `printRecTotal` per pagamento con il **contante ricevuto** per ultimo (il resto lo calcola il registratore);
  `printRecMessage` «Rif. SCO n/anno»; `endFiscalReceiptCut` con **IdCmd** univoco. Descrizioni ASCII, max 22 caratteri.
  Gli sconti di documento (promozioni, premi fedeltà) si tolgono dalle righe della stessa aliquota: niente comandi di sconto.
- Indice IVA: scritto nel dispositivo (`vat_ids`) o **letto dal registratore** (`getVatRate` 1…10); un'aliquota che non c'è
  blocca l'invio prima di stampare. Codici di pagamento: contanti 1, carta 2 (opzione `payments`).
- Rifiutato → `resetPrinter` (altrimenti il documento rimasto aperto blocca tutto) e messaggio col codice del manuale
  (`agent/rt_errors.py`). Risposta persa → si chiede `lastIdCmd` dopo 2, 4, 8 s: se coincide l'esito si registra, se
  `fpStatus` è 000 il documento non è uscito; **mai una ristampa alla cieca**.
- Chiusura Z come l'esempio del manuale (`<printZReport description="">`, **senza IdCmd**: con l'IdCmd il KUBE rifiutava
  tutto dopo la prima chiusura), attesa fino a 300 s, poi 20 s di pausa e `resetPrinter` (il KUBE apre da solo il
  promemoria «VISITA TECNICA»). Annullo come BluOrderScan; il reso (`beginRtDocRefund`) è ancora da collaudare.
- **Accenti sulla termica da 80 mm**: opzione «Tabella dei caratteri» della stampante. PC858 (ESC t 19) per le Epson
  originali (accenti ed €); molte compatibili al numero 19 hanno un'altra tabella (es. greca: «più» stampato «piΩ») e vanno
  messe su **PC850** (o PC437): accenti sì, € scritto «EUR». «Senza accenti» stampa «piu'». La stampa di prova riporta
  «àèéìòù ÀÈÉ €» per scegliere quella giusta.

## Marketing WhatsApp
- Automatici, ognuno con interruttore e testo modificabile: conferma, promemoria (24 ore prima), disdetta, grazie + richiesta di recensione Google, richiamo dopo N giorni dal servizio (es. ritocco colore), auguri di compleanno, clienti persi.
- Campagne a segmenti (tutti, inattivi da 60 giorni, compleanno del mese, nuovi clienti) con anteprima sul telefono, personalizzate col nome e con il link di prenotazione. Solo ai clienti con consenso marketing.
- Ogni automatico parte una sola volta per cliente e occasione.
- Modalità di prova (simulata) finché non si collega il numero WhatsApp Business del salone (`WHATSAPP.md`).
