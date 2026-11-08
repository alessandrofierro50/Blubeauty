"""Modelli dei messaggi WhatsApp (Meta): conversione dei testi, richiesta di approvazione, stato e invio.

Meta permette all'azienda di scrivere per prima (fuori dalla finestra di 24 ore dall'ultimo messaggio del cliente) solo con
un **modello approvato**. BluBeauty genera i modelli dai testi degli automatici e delle campagne: i segnaposto `{nome}`,
`{ora}`… diventano `{{1}}`, `{{2}}`… e all'invio si passano i valori nello stesso ordine.

Scrive soltanto i campi `wa_template` di `automations` e `campaigns` (il resto lo scrive `service.py`).
Ogni modifica del testo richiede un nuovo modello (`bb_<tipo>_v<versione>`): finché non è approvato, il messaggio parte
come testo libero (arriva solo se la cliente ha scritto al salone nelle ultime 24 ore).
"""

import re
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.marketing import service as msg
from app.marketing.models import Automation, Campaign

LANG = "it"
PLACEHOLDER = re.compile(r"\{(\w+)\}")
# valori d'esempio che Meta chiede per ogni variabile (servono solo all'approvazione)
EXAMPLES = {
    "nome": "Giulia", "salone": "Aurora Hair & Beauty", "data": "martedì 10 novembre", "ora": "15:30", "servizio": "Colore e piega",
    "link": "https://blubeauty.blucodeinformatica.it/prenota/aurora", "recensione": "https://g.page/r/aurora/review", "giorni": "5",
    "punti": "120", "premio": "Piega in omaggio", "codice": "BR-7KQ2-M9TX", "importo": "50,00 €", "residuo": "35,00 €",
    "usato": "15,00 €", "buono": "https://blubeauty.blucodeinformatica.it/prenota/aurora/buono/abc123",
    "scadenza": ", valido fino al 10/11/2027", "regalato_da": "Laura", "pacchetto": "5 pressoterapie", "sedute": "5 × Pressoterapia",
    "seduta": "2", "totale": "5", "restano": "3", "rimaste": "Pressoterapia 3", "cosa": "il tuo buono regalo BR-7KQ2-M9TX",
    "resta": "hai ancora 35,00 € da usare",
}
STATUS_IT = {"approved": "Approvato", "pending": "In approvazione", "rejected": "Rifiutato", "paused": "In pausa",
             "disabled": "Disattivato", "errore": "Errore", "da_inviare": "Da inviare a Meta", "cambiato": "Testo cambiato: da inviare di nuovo"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def convert(text: str) -> tuple[str, list[str]]:
    """Testo BluBeauty → testo del modello Meta ({{1}}…) e nomi dei segnaposto in ordine.
    Meta non accetta una variabile all'inizio o alla fine del testo: in quel caso si aggiunge una parola fissa."""
    params: list[str] = []

    def sub(m: re.Match) -> str:
        params.append(m.group(1))
        return "{{%d}}" % len(params)

    body = PLACEHOLDER.sub(sub, text.strip())
    body = re.sub(r"\n{3,}", "\n\n", body)
    if body.startswith("{{"):
        body = "Ciao! " + body
    if body.endswith("}}"):
        body += "\nA presto!"
    return body[:1024], params


def category(kind: str) -> str:
    return "UTILITY" if kind in msg.AGENDA_KINDS + msg.PREPAID_KINDS else "MARKETING"


def state(obj) -> str:
    """Stato del modello rispetto al testo attuale (automatico o campagna)."""
    t = obj.wa_template or {}
    if not t.get("name"):
        return "da_inviare"
    if t.get("text") != convert(_text(obj))[0]:
        return "cambiato"
    return t.get("status") or "pending"


def out(obj) -> dict:
    t, st = obj.wa_template or {}, state(obj)
    return {"name": t.get("name"), "status": st, "label": STATUS_IT.get(st, st), "reason": t.get("reason"),
            "category": t.get("category"), "text": convert(_text(obj))[0]}


def _text(obj) -> str:
    return obj.template if isinstance(obj, Automation) else obj.body


def _kind(obj) -> str:
    return obj.kind if isinstance(obj, Automation) else "campagna"


def _client(db: Session, tenant_id) -> tuple[str, dict]:
    s = msg.settings(db, tenant_id)
    if s.whatsapp_mode != "cloud_api" or not s.whatsapp_token_enc:
        raise HTTPException(422, "Prima collega WhatsApp Business (modalità, Phone number ID e token)")
    if not s.whatsapp_waba_id:
        raise HTTPException(422, "Manca l'ID dell'account WhatsApp Business (WABA ID): lo trovi nel WhatsApp Manager")
    from app.fatturapa.service import decrypt
    return s.whatsapp_waba_id, {"Authorization": f"Bearer {decrypt(s.whatsapp_token_enc)}"}


def _error(r: httpx.Response) -> str:
    try:
        e = r.json().get("error", {})
        return (e.get("error_user_msg") or e.get("message") or r.text)[:400]
    except ValueError:
        return f"HTTP {r.status_code}"


def submit(db: Session, tenant_id, obj) -> dict:
    """Chiede a Meta l'approvazione del modello per il testo attuale (nuova versione se il testo è cambiato)."""
    waba, headers = _client(db, tenant_id)
    body, params = convert(_text(obj))
    old = obj.wa_template or {}
    version = int(old.get("version") or 0) + 1
    suffix = obj.kind if isinstance(obj, Automation) else f"campagna_{str(obj.id).replace('-', '')[:8]}"
    name = f"bb_{suffix}_v{version}"
    comp = {"type": "BODY", "text": body}
    if params:
        comp["example"] = {"body_text": [[EXAMPLES.get(p, p) for p in params]]}
    payload = {"name": name, "language": LANG, "category": category(_kind(obj)), "components": [comp]}
    try:
        with httpx.Client(timeout=30, transport=msg._transport) as c:
            r = c.post(f"{msg.GRAPH_URL}/{waba}/message_templates", headers=headers, json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Meta non risponde: {exc}") from exc
    if r.status_code >= 400:
        obj.wa_template = {**old, "last_error": _error(r), "last_error_at": now_iso()}
        db.flush()
        raise HTTPException(422, f"Meta ha rifiutato la richiesta: {_error(r)}")
    j = r.json()
    obj.wa_template = {"name": name, "version": version, "id": j.get("id"), "status": (j.get("status") or "PENDING").lower(),
                       "category": j.get("category") or payload["category"], "text": body, "params": params,
                       "submitted_at": now_iso(), "reason": None}
    db.flush()
    return out(obj)


def submit_all(db: Session, tenant_id, modules: list[str]) -> dict:
    """Invia a Meta gli automatici attivi (dei moduli del pacchetto) senza un modello valido per il testo attuale."""
    sent, errors = [], []
    for a in msg.ensure_automations(db, tenant_id):
        needs = "agenda" if a.kind in msg.AGENDA_KINDS else "pos" if a.kind in msg.PREPAID_KINDS else "marketing"
        if not a.enabled or needs not in modules or state(a) in ("approved", "pending"):
            continue
        try:
            submit(db, tenant_id, a)
            sent.append(a.kind)
        except HTTPException as e:
            if e.status_code != 422 or "Meta ha rifiutato" not in str(e.detail):
                raise
            errors.append({"kind": a.kind, "label": msg.KIND_LABEL[a.kind], "error": str(e.detail)})
    return {"sent": sent, "errors": errors}


def sync(db: Session, tenant_id) -> int:
    """Aggiorna lo stato dei modelli da Meta (approvato, rifiutato con motivo…). Restituisce quanti sono cambiati."""
    waba, headers = _client(db, tenant_id)
    remote, url = {}, f"{msg.GRAPH_URL}/{waba}/message_templates"
    params = {"fields": "name,status,category,rejected_reason,language", "limit": 200}
    with httpx.Client(timeout=30, transport=msg._transport) as c:
        for _ in range(10):  # paginazione
            r = c.get(url, headers=headers, params=params)
            if r.status_code >= 400:
                raise HTTPException(422, f"Meta: {_error(r)}")
            j = r.json()
            for t in j.get("data", []):
                if t.get("language", LANG) == LANG:
                    remote[t["name"]] = t
            nxt = (j.get("paging") or {}).get("next")
            if not nxt:
                break
            url, params = nxt, None
    changed = 0
    objs = list(db.scalars(select(Automation))) + list(db.scalars(select(Campaign).where(Campaign.status == "bozza")))
    for o in objs:
        t = o.wa_template or {}
        rt = remote.get(t.get("name") or "")
        if rt is None:
            continue
        new = {**t, "status": rt["status"].lower(), "category": rt.get("category") or t.get("category"),
               "reason": None if rt.get("rejected_reason") in (None, "NONE") else rt["rejected_reason"]}
        if new != t:
            o.wa_template, changed = new, changed + 1
    db.flush()
    return changed


def for_send(obj, values: dict) -> dict | None:
    """Modello da usare per l'invio, con i valori dei segnaposto in ordine; None = testo libero."""
    if state(obj) != "approved":
        return None
    t = obj.wa_template

    def clean(p) -> str:  # Meta non accetta parametri vuoti, a capo, tabulazioni o più di 4 spazi di fila
        v = values.get(p)
        s = re.sub(r"\s+", " ", str(v)).strip() if v not in (None, "") else ""
        return s[:1000] or EMPTY.get(p, "-")

    return {"name": t["name"], "params": [clean(p) for p in t.get("params", [])]}


EMPTY = {"scadenza": ", senza scadenza", "regalato_da": "chi ti vuole bene"}
