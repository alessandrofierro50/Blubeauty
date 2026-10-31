# BluBeauty

Il gestionale in abbonamento per **parrucchieri, barber e centri estetici** — BluCode Informatica.

Agenda con tempi di posa · prenotazione online da smartphone con disdetta autonoma · conferme e promemoria WhatsApp ·
schede clienti e schede tecniche · cassa con registratore telematico e stampante termica · fattura elettronica ·
marketing WhatsApp (automatici e campagne) · prodotti e magazzino.

Costruito sulla base di **BluGest** (FastAPI + PostgreSQL con Row Level Security + React/Mantine): pannello del super
amministratore, abbonamenti standard BluCode, Console, prova gratuita dal sito e pagamenti online sono gli stessi.

## Installazione sulla VPS

1. Nel pannello DNS crea un record **A** per `blubeauty.blucodeinformatica.it` → `217.76.158.224`.
2. Sulla VPS, come root:

```bash
git clone https://github.com/alessandrofierro50/blubeauty.git /opt/blubeauty
cd /opt/blubeauty
bash deploy/install.sh
```

Lo script installa Docker se manca, genera le password nel file `.env`, avvia tutto e pianifica il backup notturno.
Se sul server c'è già nginx sulle porte 80/443 (come per gli altri prodotti BluCode), BluBeauty resta su una porta locale
(`HTTP_BIND`) e nginx gli passa il dominio. Alla fine mostra la password iniziale del super amministratore.

3. Apri `https://blubeauty.blucodeinformatica.it/admin` e accedi.

## Aggiornare

```bash
cd /opt/blubeauty && bash deploy/update.sh
```

## Documentazione

- `docs/BLUBEAUTY.md` — funzioni di BluBeauty (agenda, prenotazione online, cassa, marketing)
- `docs/WHATSAPP.md` — collegare il numero WhatsApp Business del salone
- `docs/BRAND.md` — logo e colori
- `docs/SPECIFICA.md`, `docs/ARCHITETTURA.md` — base comune (scritte per BluGest)
- `docs/PAGAMENTI.md` — pagamenti online degli abbonamenti
- `CLAUDE.md` — note di sviluppo e stato
