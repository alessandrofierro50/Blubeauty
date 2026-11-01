"""Messaggi ai clienti: invio (WhatsApp Business Cloud API o modalità simulata), automatici e campagne.

È l'unico punto che scrive `messages`, `automations` e `campaigns`.

WhatsApp Business Cloud API (Meta): i messaggi che partono dall'azienda fuori dalla finestra di 24 ore dall'ultimo
messaggio del cliente devono usare un *modello approvato* da Meta. In questa versione si invia testo libero
(`type: text`): va bene nella finestra di 24 ore e per i test; prima dell'uso reale i testi degli automatici vanno
registrati come modelli nel WhatsApp Manager (vedi docs/WHATSAPP.md). Senza credenziali l'azienda resta in
modalità «simulato»: i messaggi si registrano e si vedono nella conversazione, ma non partono.
"""

import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Party
from app.marketing.models import Automation, Campaign, MarketingSettings, Message

log = logging.getLogger(__name__)
TZ = ZoneInfo("Europe/Rome")
GRAPH_URL = "https://graph.facebook.com/v21.0"
_transport: httpx.BaseTransport | None = None  # nei test: httpx.MockTransport

# Automatici dell'agenda (pacchetto AGENDA) e del marketing (pacchetto SALONE)
AGENDA_KINDS = ["conferma", "promemoria", "disdetta"]
MARKETING_KINDS = ["grazie", "richiamo", "compleanno", "clienti_persi", "premio"]
# Buoni regalo e pacchetti (modulo pos, pacchetto SALONE): messaggi di servizio, non di marketing (niente consenso marketing)
PREPAID_KINDS = ["buono_ricevuto", "buono_saldo", "pacchetto_acquistato", "pacchetto_seduta", "prepagato_scadenza"]

KIND_LABEL = {
    "conferma": "Conferma prenotazione",
    "promemoria": "Promemoria",
    "disdetta": "Conferma disdetta",
    "grazie": "Grazie + recensione",
    "richiamo": "Richiamo (es. ritocco colore)",
    "compleanno": "Auguri di compleanno",
    "clienti_persi": "Clienti persi",
    "premio": "Premio fedeltà raggiunto",
    "buono_ricevuto": "Buono regalo ricevuto",
    "buono_saldo": "Buono regalo usato (credito residuo)",
    "pacchetto_acquistato": "Pacchetto o abbonamento acquistato",
    "pacchetto_seduta": "Seduta scalata dal pacchetto",
    "prepagato_scadenza": "Buono o pacchetto in scadenza",
    "campagna": "Campagna",
}

# Segnaposto: {nome} {salone} {data} {ora} {servizio} {link} {recensione}
DEFAULT_AUTOMATIONS = {
    "conferma": (None, "Ciao {nome}! ✨ Il tuo appuntamento da {salone} è confermato per {data} alle {ora} ({servizio}).\n"
                       "Per vederlo o disdirlo: {link}"),
    "promemoria": (24, "Ciao {nome}, ti ricordiamo l'appuntamento di domani alle {ora} da {salone} ({servizio}). "
                       "Ti aspettiamo! 💙\nNon puoi venire? Disdici qui: {link}"),
    "disdetta": (None, "Ciao {nome}, il tuo appuntamento del {data} alle {ora} è stato disdetto. "
                       "Prenota di nuovo quando vuoi: {link}"),
    "grazie": (None, "Grazie {nome} per essere passata da {salone}! 🌸 Se ti sei trovata bene, ci lasci una recensione? "
                     "Ci aiuta tantissimo: {recensione}"),
    "richiamo": (35, "Ciao {nome}, sono passate {giorni} settimane dal tuo ultimo {servizio} 🎨 È il momento giusto per il "
                     "ritocco! Prenota in un tap: {link}"),
    "compleanno": (None, "Tanti auguri {nome}! 🎂 Per il tuo compleanno hai il 20% di sconto su un trattamento a scelta "
                         "questo mese. Prenota: {link}"),
    "premio": (None, "Complimenti {nome}! 🎁 Hai {punti} punti fedeltà da {salone}: alla prossima visita puoi avere «{premio}». "
                     "Prenota qui: {link}"),
    "buono_ricevuto": (None, "Ciao {nome}! 🎁 Hai ricevuto un buono regalo da {salone} di {importo}. Codice {codice}{scadenza}.\n"
                             "Eccolo qui: {buono}\nPrenota quando vuoi: {link}"),
    "buono_saldo": (None, "Ciao {nome}, hai usato {usato} del tuo buono regalo {codice}: ti restano {residuo}{scadenza}. "
                          "Lo trovi qui: {buono}"),
    "pacchetto_acquistato": (None, "Grazie {nome}! 📦 Il tuo pacchetto «{pacchetto}» da {salone} è attivo: {sedute}{scadenza}. "
                                   "Prenota la prima seduta: {link}"),
    "pacchetto_seduta": (None, "Ciao {nome}, abbiamo scalato la seduta {seduta} di {totale} del pacchetto «{pacchetto}»: "
                               "te ne restano {restano}{scadenza}. Prenota la prossima: {link}"),
    "prepagato_scadenza": (30, "Ciao {nome}, {cosa} da {salone} scade il {data}: {resta}. Prenota in tempo per non perderlo: {link}"),
    "clienti_persi": (60, "Ciao {nome}, ci manchi! 💙 Torna a trovarci entro fine mese: per te una sorpresa con qualsiasi "
                          "servizio. Prenota: {link}"),
}

SEGMENTS = {
    "tutti": "Tutti i clienti con consenso",
    "inattivi_60": "Clienti che non vengono da 60+ giorni",
    "compleanno_mese": "Compleanno questo mese",
    "nuovi_30": "Nuovi clienti degli ultimi 30 giorni",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_phone(phone: str | None) -> str | None:
    """Numero in formato internazionale (+39…), oppure None se non è un cellulare plausibile."""
    if not phone:
        return None
    p = re.sub(r"[^\d+]", "", phone)
    if p.startswith("00"):
        p = "+" + p[2:]
    if not p.startswith("+"):
        p = "+39" + p
    return p if 10 <= len(p) <= 16 else None


def fill(template: str, values: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), m.group(0))), template)


def settings(db: Session, tenant_id) -> MarketingSettings:
    s = db.get(MarketingSettings, tenant_id)
    if s is None:
        s = MarketingSettings(tenant_id=tenant_id)
        db.add(s)
        db.flush()
    return s


def ensure_automations(db: Session, tenant_id) -> list[Automation]:
    have = {a.kind: a for a in db.scalars(select(Automation))}
    for kind, (offset, template) in DEFAULT_AUTOMATIONS.items():
        if kind not in have:
            have[kind] = Automation(tenant_id=tenant_id, kind=kind, offset=offset, template=template,
                                    enabled=kind != "clienti_persi")
            db.add(have[kind])
    db.flush()
    order = list(DEFAULT_AUTOMATIONS)
    return sorted(have.values(), key=lambda a: order.index(a.kind) if a.kind in order else 99)


def automation(db: Session, tenant_id, kind: str) -> Automation:
    a = db.scalar(select(Automation).where(Automation.kind == kind))
    return a or next(x for x in ensure_automations(db, tenant_id) if x.kind == kind)


# ---------------------------------------------------------------------------------------------------------- invio
def _deliver(db: Session, tenant_id, channel: str, to: str, body: str) -> tuple[str, str | None, str | None]:
    """(stato, id del provider, errore)."""
    if channel != "whatsapp":
        return "simulato", None, None
    s = settings(db, tenant_id)
    if s.whatsapp_mode != "cloud_api" or not s.whatsapp_phone_id or not s.whatsapp_token_enc:
        return "simulato", f"sim_{uuid.uuid4().hex[:12]}", None
    from app.fatturapa.service import decrypt
    token = decrypt(s.whatsapp_token_enc)
    try:
        with httpx.Client(timeout=20, transport=_transport) as c:
            r = c.post(f"{GRAPH_URL}/{s.whatsapp_phone_id}/messages",
                       headers={"Authorization": f"Bearer {token}"},
                       json={"messaging_product": "whatsapp", "to": to.lstrip("+"), "type": "text",
                             "text": {"preview_url": True, "body": body}})
        if r.status_code >= 400:
            err = r.json().get("error", {}).get("message") if r.headers.get("content-type", "").startswith("application/json") else r.text
            return "errore", None, (err or f"HTTP {r.status_code}")[:500]
        return "inviato", (r.json().get("messages") or [{}])[0].get("id"), None
    except httpx.HTTPError as exc:
        return "errore", None, str(exc)[:500]


def send(db: Session, tenant_id, *, kind: str, party: Party | None, body: str, to: str | None = None,
         channel: str = "whatsapp", appointment_id=None, campaign_id=None, dedupe_key: str | None = None) -> Message | None:
    """Registra e invia un messaggio. Con `dedupe_key` già usata non manda nulla (automatici una volta sola)."""
    to = normalize_phone(to or (party.mobile or party.phone if party else None))
    if not to:
        return None
    if dedupe_key and db.scalar(select(Message.id).where(Message.dedupe_key == dedupe_key)):
        return None
    status, provider_id, error = _deliver(db, tenant_id, channel, to, body)
    m = Message(tenant_id=tenant_id, party_id=party.id if party else None, appointment_id=appointment_id,
                campaign_id=campaign_id, channel=channel, kind=kind, to=to, body=body, status=status,
                provider_id=provider_id, error=error, dedupe_key=dedupe_key,
                sent_at=now() if status in ("inviato", "simulato") else None)
    db.add(m)
    db.flush()
    return m


def send_automatic(db: Session, tenant_id, kind: str, party: Party | None, values: dict, *,
                   appointment_id=None, dedupe_key: str | None = None) -> Message | None:
    if party is None:
        return None
    a = automation(db, tenant_id, kind)
    if not a.enabled:
        return None
    body = fill(a.template, {"nome": party.first_name or party.name.split(" ")[-1], **values})
    return send(db, tenant_id, kind=kind, party=party, body=body, channel=a.channel,
                appointment_id=appointment_id, dedupe_key=dedupe_key)


# --------------------------------------------------------------------------------------------------- segmenti
def segment_parties(db: Session, segment: str, on: date | None = None) -> list[Party]:
    """Destinatari di una campagna: SOLO clienti con consenso marketing e un cellulare (GDPR)."""
    from app.agenda.models import Appointment, ClientProfile
    on = on or datetime.now(TZ).date()
    rows = db.execute(
        select(Party, ClientProfile).join(ClientProfile, ClientProfile.party_id == Party.id)
        .where(ClientProfile.marketing_consent_at.is_not(None), Party.is_customer.is_(True))
    ).all()
    last = dict(db.execute(
        select(Appointment.party_id, func.max(Appointment.starts_at))
        .where(Appointment.status.not_in(("disdetto", "non_presentato"))).group_by(Appointment.party_id)
    ).all())
    out = []
    limit = datetime.combine(on - timedelta(days=60), datetime.min.time(), TZ)
    for party, prof in rows:
        if not normalize_phone(party.mobile or party.phone):
            continue
        if segment == "inattivi_60" and not (last.get(party.id) is None or last[party.id] < limit):
            continue
        if segment == "compleanno_mese" and not (prof.birth_date and prof.birth_date.month == on.month):
            continue
        if segment == "nuovi_30" and not (party.created_at and party.created_at.date() >= on - timedelta(days=30)):
            continue
        out.append(party)
    return out


def send_campaign(db: Session, tenant_id, campaign: Campaign, values: dict) -> int:
    if campaign.status == "inviata":
        return campaign.recipients
    sent = 0
    for p in segment_parties(db, campaign.segment):
        body = fill(campaign.body, {"nome": p.first_name or p.name, **values})
        if send(db, tenant_id, kind="campagna", party=p, body=body, channel=campaign.channel, campaign_id=campaign.id,
                dedupe_key=f"campagna:{campaign.id}:{p.id}"):
            sent += 1
    campaign.status, campaign.recipients, campaign.sent_at = "inviata", sent, now()
    db.flush()
    return sent
