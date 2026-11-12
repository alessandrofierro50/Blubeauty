"""Video di aiuto: il pulsante «Guarda il video» delle schermate apre il tutorial della pagina.

Gli indirizzi dei video (YouTube non in elenco, Vimeo o un file .mp4 sul server) si inseriscono dal pannello del super
amministratore (Impostazioni › Video di aiuto) e sono salvati in `saas_settings` sotto la chiave `help_videos`:
valgono per tutte le aziende. Un video senza indirizzo appare come «in preparazione». Progetto: documento Drive
«BluBeauty – Video di aiuto nelle schermate» (prima serie di otto video)."""

from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.models import SaasSetting

SETTINGS_KEY = "help_videos"

# chiave → (titolo del video, schermata dove compare il pulsante)
VIDEOS: dict[str, tuple[str, str]] = {
    "agenda": ("Agenda appuntamenti", "Agenda"),
    "scheda_cliente": ("Scheda cliente: come si carica un cliente e quali campi compilare", "Clienti e scheda cliente"),
    "servizi": ("Servizi e listini", "Servizi, operatori e cabine"),
    "cassa": ("Cassa e scontrino", "Cassa"),
    "prenotazione_whatsapp": ("Prenotazione dal link WhatsApp", "Impostazioni del salone"),
    "articoli": ("Inserimento articoli, con codice a barre e listini", "Articoli e scheda articolo"),
    "chiusura_conto": ("Chiusura del conto con vendita al banco", "Incasso dell'appuntamento"),
    "buoni_abbonamenti": ("Gestione di abbonamenti e buoni", "Buoni e pacchetti"),
}


def _stored(db: Session) -> dict:
    row = db.get(SaasSetting, SETTINGS_KEY)
    return dict(row.value) if row and isinstance(row.value, dict) else {}


def help_videos(db: Session) -> list[dict]:
    urls = _stored(db)
    return [{"key": k, "title": t, "screen": s, "url": urls.get(k) or None} for k, (t, s) in VIDEOS.items()]


def clean_url(url: str | None) -> str | None:
    """Solo indirizzi http(s) (il video si apre in una finestra dentro BluBeauty)."""
    url = (url or "").strip()
    if not url:
        return None
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError(f"Indirizzo del video non valido: {url}")
    return url


def save_help_videos(db: Session, urls: dict[str, str | None]) -> list[dict]:
    cur = _stored(db)
    for k, v in urls.items():
        if k not in VIDEOS:
            continue
        v = clean_url(v)
        if v:
            cur[k] = v
        else:
            cur.pop(k, None)
    row = db.get(SaasSetting, SETTINGS_KEY)
    if row is None:
        db.add(SaasSetting(key=SETTINGS_KEY, value=cur))
    else:
        row.value = cur
    db.flush()
    return help_videos(db)
