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

## Modelli dei messaggi: approvazione da BluBeauty
Meta permette il **testo libero** solo entro 24 ore dall'ultimo messaggio del cliente; per scrivere per primi servono
**modelli approvati**. BluBeauty li gestisce da solo (`app/marketing/wa_templates.py`, migrazione `0029_whatsapp_modelli`):
- **Impostazioni del salone › WhatsApp**: oltre a Phone number ID e token serve il **WABA ID** (account WhatsApp Business).
- **Messaggi e punti › Chiedi l'approvazione** (`POST /api/marketing/modelli/invia`): ogni automatico attivo diventa un modello
  `bb_<tipo>_v<versione>` (lingua `it`, categoria UTILITY per agenda/buoni/pacchetti, MARKETING per il resto) con i segnaposto
  `{nome}`… convertiti in `{{1}}`… e i valori d'esempio. Se il testo finisce o inizia con una variabile si aggiunge «A presto!» /
  «Ciao!» (Meta lo rifiuterebbe).
- **Aggiorna stato** (`POST /api/marketing/modelli/aggiorna`, anche ogni ora col job dei promemoria): approvato, in
  approvazione, rifiutato con motivo. Testo modificato → «Testo cambiato», nuova versione da inviare.
- Invio: modello approvato e testo invariato → `type: template` con i parametri in ordine (senza a capo); altrimenti testo libero.
- **Campagne**: con WhatsApp Business restano in bozza finché il loro modello non è approvato, poi «Invia»
  (`POST /api/marketing/campagne/{id}/invia`).
- Le **risposte** delle clienti non arrivano ancora in BluBeauty (manca il webhook di Meta): da fare.

## Guida per il salone
PDF passo passo (SIM, account Meta, numero, token permanente con utente di sistema, pagamento, approvazione, costi, problemi):
`frontend/public/guide/BluBeauty-Guida-WhatsApp.pdf`, generato da `docs/guida/guida_whatsapp_pdf.py`; collegato dal riquadro
WhatsApp delle impostazioni.

## Costi
Meta non chiede canone: si paga ogni messaggio inviato con un modello (listino Italia di ottobre 2026: utility circa 0,025 €,
marketing circa 0,066 €; risposte entro 24 ore gratis), sulla carta del salone, separato dall'abbonamento BluBeauty.
Esempio: 300 appuntamenti al mese ≈ 25 € al mese.
