# Collegare WhatsApp Business

BluBeauty invia i messaggi con la **WhatsApp Business Platform (Cloud API) di Meta**. Finché il salone non collega il suo
numero, i messaggi restano in **modalità di prova**: si registrano e si vedono nelle conversazioni, ma non partono.

## Cosa serve al salone
1. Un account **Meta Business** (business.facebook.com) e un numero di telefono non già usato con l'app WhatsApp
   (oppure migrato dall'app WhatsApp Business).
2. In **developers.facebook.com** un'app di tipo *Business* con il prodotto **WhatsApp**: si ottengono il
   **Phone number ID** e un **token di accesso** permanente (utente di sistema con permesso `whatsapp_business_messaging`).
3. In BluBeauty: *Agenda › Orari e prenotazione online › WhatsApp* → «WhatsApp Business», Phone number ID e token.
   Il token si salva cifrato e non si rilegge più.

## Modelli dei messaggi (importante)
Meta permette il **testo libero** solo entro 24 ore dall'ultimo messaggio del cliente. Conferme, promemoria, auguri e
campagne partono di solito fuori da quella finestra, quindi vanno registrati come **modelli** nel WhatsApp Manager:
- *Utility*: conferma, promemoria, disdetta (gratuiti o quasi entro la finestra di servizio);
- *Marketing*: grazie + recensione, richiamo, compleanno, clienti persi, campagne (a pagamento per conversazione).

Questa versione invia testo libero (`type: text`): va bene per le prove e per le risposte entro 24 ore. Prima dell'uso
reale in salone: registrare i modelli con gli stessi testi e passare all'invio `type: template` (da fare in
`app/marketing/service.py::_deliver`).

## Costi
Le conversazioni WhatsApp sono a pagamento secondo il listino Meta per l'Italia (categorie utility e marketing):
il costo è del salone sul suo account Meta, separato dall'abbonamento BluBeauty.
