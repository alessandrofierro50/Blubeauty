# BluBeauty — funzioni

> Aggiornato al 2026-10-31. Base tecnica e funzioni comuni: `SPECIFICA.md` e `ARCHITETTURA.md` (BluGest).

## Pacchetti (prezzi provvisori)

| Pacchetto | Prezzo | Cosa comprende |
|---|---|---|
| **Agenda** | 19 €/mese · 190 €/anno | Agenda, prenotazione online da smartphone, conferme/promemoria/disdette WhatsApp, schede clienti, statistiche di base |
| **Salone** | 39 €/mese · 390 €/anno | Agenda + cassa con registratore telematico e stampante termica, prodotti e magazzino, acquisti, fatture, scadenzario, marketing WhatsApp |
| Extra | da listino | Fattura elettronica con invio allo SDI (Aruba) |

Prova gratuita dal sito: 7 giorni sul pacchetto Salone.

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

## Marketing WhatsApp
- Automatici, ognuno con interruttore e testo modificabile: conferma, promemoria (24 ore prima), disdetta, grazie + richiesta di recensione Google, richiamo dopo N giorni dal servizio (es. ritocco colore), auguri di compleanno, clienti persi.
- Campagne a segmenti (tutti, inattivi da 60 giorni, compleanno del mese, nuovi clienti) con anteprima sul telefono, personalizzate col nome e con il link di prenotazione. Solo ai clienti con consenso marketing.
- Ogni automatico parte una sola volta per cliente e occasione.
- Modalità di prova (simulata) finché non si collega il numero WhatsApp Business del salone (`WHATSAPP.md`).
