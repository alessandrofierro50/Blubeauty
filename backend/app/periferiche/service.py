"""Periferiche: abbinamento degli agent, coda dei lavori, documenti per il registratore telematico e le stampanti.

È l'unico punto che crea lavori per le periferiche e che registra gli esiti nei documenti (dati del documento
commerciale nello scontrino, numero di chiusura Z nell'apertura di cassa)."""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import get_settings
from app.core.db import set_tenant
from app.documenti import service as docs
from app.documenti.models import Document
from app.periferiche.models import Agent, AgentKey, Device, DeviceJob
from app.pos.models import PosDepartment, PosPayment, PosRegister, PosSession

CENT = Decimal("0.01")
ONLINE_SECONDS = 70  # l'agent si fa vivo almeno ogni 25-40 secondi

KINDS = {"rt": "Registratore telematico", "stampante": "Stampante di ricevute", "etichette": "Stampante di etichette", "bilancia": "Bilancia"}
DRIVERS = {
    "epson_rt": {"kind": "rt", "label": "Epson FP-81 II RT / FP-90III (rete)", "address": "Indirizzo IP, es. 192.168.1.50",
                 "options": {"serial": "", "departments": {"22": 1, "10": 2, "5": 3, "4": 4, "0": 5}}},
    "custom_rt": {"kind": "rt", "label": "Custom RT (Q3X, KUBE II F… in rete)", "address": "Indirizzo IP, es. 192.168.1.51",
                  "options": {"serial": "", "departments": {"22": 1, "10": 2, "5": 3, "4": 4, "0": 5}, "username": "", "password": "",
                              "vat_ids": {}, "width": 32}},
    "simulatore_rt": {"kind": "rt", "label": "Simulatore (prove senza registratore)", "address": "", "options": {"serial": "99SIM000001"}},
    "escpos_tcp": {"kind": "stampante", "label": "Stampante termica ESC/POS in rete", "address": "IP[:porta], es. 192.168.1.60:9100",
                   "options": {"columns": 48, "charset": "pc858"}},
    "escpos_windows": {"kind": "stampante", "label": "Stampante termica installata su Windows (USB)", "address": "Nome della stampante in Windows",
                       "options": {"columns": 48, "charset": "pc858"}},
    "simulatore_stampante": {"kind": "stampante", "label": "Simulatore (salva su file)", "address": "Cartella (facoltativa)", "options": {"columns": 48, "charset": "pc858"}},
    "zpl_tcp": {"kind": "etichette", "label": "Stampante di etichette ZPL (Zebra…) in rete", "address": "IP[:porta], es. 192.168.1.70:9100", "options": {}},
    "zpl_windows": {"kind": "etichette", "label": "Stampante di etichette ZPL installata su Windows (USB)", "address": "Nome della stampante in Windows", "options": {}},
    "simulatore_etichette": {"kind": "etichette", "label": "Simulatore (salva il file ZPL)", "address": "Cartella (facoltativa)", "options": {}},
    "bilancia_seriale": {"kind": "bilancia", "label": "Bilancia su porta seriale/USB", "address": "Porta, es. COM3 o /dev/ttyUSB0",
                         "options": {"baud": 9600, "request": "W\\r", "regex": "([-+]?\\d+[.,]\\d+)", "grams": False}},
    "simulatore_bilancia": {"kind": "bilancia", "label": "Simulatore (peso inventato o fisso)", "address": "", "options": {"weight": ""}},
}
# Tabelle dei caratteri delle termiche (agent: CHARSETS). Esperienza di BluOrderScan: le compatibili spesso al n. 19 non
# hanno la PC858 ma un'altra tabella (es. greca: «più» → «piΩ») e vanno messe su PC850 o PC437.
CHARSETS = {"pc858": "PC858 (Epson originali: accenti ed €)", "pc850": "PC850 (compatibili: accenti, € scritto EUR)",
            "pc437": "PC437 (compatibili più vecchie)", "ascii": "Senza accenti (più → piu')"}
STATUS_LABEL = {"in_coda": "in coda", "inviato": "in stampa", "eseguito": "eseguito", "errore": "errore", "annullato": "annullato"}


def fail(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def now() -> datetime:
    return datetime.now(timezone.utc)


def digest(key: str) -> str:
    return hashlib.sha256(key.strip().upper().encode()).hexdigest()


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ====================================================================== abbinamento


def new_pairing_code(db: Session, agent: Agent) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    code = "".join(secrets.choice(alphabet) for _ in range(8))
    db.execute(AgentKey.__table__.delete().where(AgentKey.agent_id == agent.id, AgentKey.kind == "abbina"))
    db.add(AgentKey(key_hash=digest(code), kind="abbina", tenant_id=agent.tenant_id, agent_id=agent.id, expires_at=now() + timedelta(hours=24)))
    db.flush()
    return f"{code[:4]}-{code[4:]}"


def allowed_origins() -> list[str]:
    url = get_settings().public_url.rstrip("/")
    out = [url]
    if "localhost" in url or "127.0.0.1" in url:
        out += ["http://localhost:5173", "http://127.0.0.1:5173"]
    return sorted(set(out))


def pair(db: Session, code: str, info: dict) -> dict:
    """Scambia il codice di abbinamento con il token dell'agent (il codice vale una volta sola)."""
    k = db.get(AgentKey, digest(code.replace("-", "")))
    if k is None or k.kind != "abbina" or (k.expires_at and k.expires_at < now()):
        raise fail("Codice non valido o scaduto: generane uno nuovo dal gestionale", status.HTTP_404_NOT_FOUND)
    set_tenant(db, k.tenant_id)
    agent = db.get(Agent, k.agent_id)
    if agent is None or not agent.active:
        raise fail("Computer disattivato nel gestionale", status.HTTP_404_NOT_FOUND)
    token = secrets.token_urlsafe(32)
    db.execute(AgentKey.__table__.delete().where(AgentKey.agent_id == agent.id))
    db.add(AgentKey(key_hash=token_digest(token), kind="token", tenant_id=agent.tenant_id, agent_id=agent.id))
    agent.local_key = secrets.token_hex(16)
    agent.hostname, agent.version = (info.get("hostname") or "")[:120] or None, (info.get("version") or "")[:20] or None
    agent.platform = (info.get("platform") or "")[:60] or None
    agent.paired_at = agent.last_seen_at = now()
    db.flush()
    return {"token": token, "agent_id": str(agent.id), "name": agent.name, "local_key": agent.local_key, "allowed_origins": allowed_origins()}


def agent_from_token(db: Session, token: str | None) -> Agent:
    if not token:
        raise fail("Agent non autorizzato", status.HTTP_401_UNAUTHORIZED)
    k = db.get(AgentKey, token_digest(token))
    if k is None or k.kind != "token":
        raise fail("Agent non autorizzato: rifai l'abbinamento", status.HTTP_401_UNAUTHORIZED)
    set_tenant(db, k.tenant_id)
    agent = db.get(Agent, k.agent_id)
    if agent is None or not agent.active:
        raise fail("Computer disattivato nel gestionale", status.HTTP_403_FORBIDDEN)
    return agent


def device_config(d: Device) -> dict:
    return {"id": str(d.id), "name": d.name, "kind": d.kind, "driver": d.driver, "address": d.address, "options": d.options or {}}


def agent_config(db: Session, agent: Agent) -> dict:
    devs = db.scalars(select(Device).where(Device.agent_id == agent.id, Device.active)).all()
    return {"name": agent.name, "devices": [device_config(d) for d in devs], "local_key": agent.local_key, "allowed_origins": allowed_origins()}


def is_online(agent: Agent) -> bool:
    return bool(agent.last_seen_at and (now() - agent.last_seen_at).total_seconds() < ONLINE_SECONDS)


# ====================================================================== coda dei lavori


def enqueue(db: Session, device: Device, kind: str, payload: dict, *, document_id=None, session_id=None, user_id=None) -> DeviceJob:
    if not device.active:
        raise fail(f"Dispositivo «{device.name}» disattivato")
    job = DeviceJob(tenant_id=device.tenant_id, agent_id=device.agent_id, device_id=device.id, kind=kind, payload=payload,
                    status="in_coda", result={}, document_id=document_id, session_id=session_id, created_by=user_id)
    db.add(job)
    db.flush()
    return job


def claim(db: Session, agent: Agent, limit: int = 10) -> list[dict]:
    """Lavori in coda per questo agent: passano a "inviato" (un lavoro inviato non si rimanda da solo: niente scontrini doppi)."""
    agent.last_seen_at = now()
    jobs = db.scalars(select(DeviceJob).where(DeviceJob.agent_id == agent.id, DeviceJob.status == "in_coda")
                      .order_by(DeviceJob.created_at).limit(limit).with_for_update(skip_locked=True)).all()
    out = []
    for j in jobs:
        dev = db.get(Device, j.device_id)
        j.status, j.sent_at = "inviato", now()
        out.append({"id": str(j.id), "kind": j.kind, "payload": j.payload, "device_id": str(j.device_id), "device": device_config(dev) if dev else None})
        _mirror(db, j)
    db.flush()
    return out


def complete(db: Session, agent: Agent, job_id: uuid.UUID, ok: bool, result: dict | None, error: str | None) -> DeviceJob:
    j = db.get(DeviceJob, job_id)
    if j is None or j.agent_id != agent.id:
        raise fail("Lavoro non trovato", status.HTTP_404_NOT_FOUND)
    agent.last_seen_at = now()
    if j.status in ("eseguito", "annullato"):
        return j  # esito ripetuto: già registrato
    j.status = "eseguito" if ok else "errore"
    j.result, j.error, j.done_at = result or {}, (None if ok else (error or "Errore sconosciuto")[:1000]), now()
    _mirror(db, j)
    db.flush()
    return j


def _mirror(db: Session, j: DeviceJob) -> None:
    """Riporta lo stato del lavoro sul documento (scontrino/reso) o sull'apertura di cassa."""
    if j.kind in ("rt.receipt", "rt.refund") and j.document_id:
        d = db.get(Document, j.document_id)
        if d is None:
            return
        rt = dict((d.fiscal or {}).get("rt") or {})
        if rt.get("job_id") not in (None, str(j.id)) and rt.get("status") == "emesso":
            return
        rt.update(job_id=str(j.id), status={"in_coda": "in_coda", "inviato": "inviato", "eseguito": "emesso", "errore": "errore"}.get(j.status, j.status))
        if j.status == "eseguito":
            rt.update({k: v for k, v in (j.result or {}).items() if k in ("number", "z", "date", "time", "serial", "simulated")}, error=None)
        elif j.status == "errore":
            rt["error"] = j.error
        d.fiscal = {**(d.fiscal or {}), "rt": rt}
        flag_modified(d, "fiscal")
    if j.kind == "rt.z" and j.session_id and j.status == "eseguito":
        s = db.get(PosSession, j.session_id)
        if s is not None and (j.result or {}).get("z"):
            s.z_number = str(j.result["z"])[:20]


def cancel(db: Session, j: DeviceJob) -> None:
    if j.status == "in_coda":
        j.status = "annullato"
        db.flush()


def retry(db: Session, j: DeviceJob, user_id=None, force: bool = False) -> DeviceJob:
    """Rimette in coda un lavoro fallito. Uno "inviato" senza risposta si ripete solo forzando (rischio di doppia stampa)."""
    if j.status == "eseguito":
        raise fail("Il lavoro è già stato eseguito", status.HTTP_409_CONFLICT)
    if j.status == "inviato" and not force:
        raise fail("Il lavoro è stato inviato al computer ma non è arrivata la risposta: controlla sul registratore se il documento "
                   "è uscito prima di ripeterlo", status.HTTP_409_CONFLICT)
    if j.status == "in_coda":
        return j
    dev = db.get(Device, j.device_id)
    if j.status != "annullato":
        j.status = "annullato"
    new = enqueue(db, dev, j.kind, j.payload, document_id=j.document_id, session_id=j.session_id, user_id=user_id)
    _mirror(db, new)
    return new


def job_out(j: DeviceJob, dev: Device | None = None) -> dict:
    return {"id": str(j.id), "kind": j.kind, "status": j.status, "status_label": STATUS_LABEL.get(j.status, j.status), "result": j.result or {},
            "error": j.error, "device_id": str(j.device_id), "device_name": dev.name if dev else None,
            "document_id": str(j.document_id) if j.document_id else None, "created_at": j.created_at.isoformat() if j.created_at else None,
            "sent_at": j.sent_at.isoformat() if j.sent_at else None, "done_at": j.done_at.isoformat() if j.done_at else None}


# ====================================================================== documenti per il registratore e le stampanti


def _d(v) -> Decimal:
    return Decimal(v or 0)


def _s(v: Decimal) -> str:
    return str(Decimal(v).quantize(CENT, ROUND_HALF_UP))


def _lines(db: Session, d: Document) -> tuple[list[dict], list[dict]]:
    deps = {x.id: x for x in db.scalars(select(PosDepartment))}
    lines, adjustments = [], []
    for ln in sorted(d.lines, key=lambda x: x.line_no):
        gross = _d(ln.unit_price_gross)
        dep = deps.get(ln.department_id)
        rt_dep = dep.rt_department if dep and dep.rt_department else None
        if gross < 0:
            adjustments.append({"description": ln.description[:60], "amount": _s(-docs.gross_amount(ln)), "vat_rate": str(_d(ln.vat_rate)),
                                "department": rt_dep})
            continue
        qty = _d(ln.quantity)
        lines.append({"description": ln.description[:60], "quantity": str(qty.normalize()), "unit_price": _s(gross),
                      "full_amount": _s(gross * qty), "amount": _s(docs.gross_amount(ln)), "vat_rate": str(_d(ln.vat_rate)), "department": rt_dep})
    return lines, adjustments


def _payments(db: Session, d: Document) -> list[dict]:
    out = []
    for p in db.scalars(select(PosPayment).where(PosPayment.document_id == d.id).order_by(PosPayment.created_at)):
        amount = p.tendered if p.method == "contanti" and p.tendered is not None else p.amount
        out.append({"method": p.method, "amount": _s(abs(_d(amount)))})
    return out


def receipt_payload(db: Session, d: Document) -> dict:
    lines, adjustments = _lines(db, d)
    return {"lines": lines, "adjustments": adjustments, "payments": _payments(db, d), "lottery": (d.fiscal or {}).get("lottery"),
            "total": _s(_d(d.total)), "document": f"SCO {d.number}/{d.year}"}


def refund_payload(db: Session, d: Document, orig: Document | None) -> dict:
    lines, adjustments = _lines(db, d)
    # nel reso non ci sono sconti separati: le righe di sconto riducono gli articoli della stessa aliquota
    for a in adjustments:
        left = Decimal(a["amount"])
        for ln in lines:
            if left <= 0:
                break
            if Decimal(ln["vat_rate"]) == Decimal(a["vat_rate"]):
                cut = min(left, Decimal(ln["amount"]))
                ln["amount"] = ln["full_amount"] = _s(Decimal(ln["amount"]) - cut)
                left -= cut
    rt = ((orig.fiscal or {}).get("rt") or {}) if orig else {}
    ref = {"z": rt.get("z"), "number": rt.get("number"), "date": rt.get("date"), "serial": rt.get("serial")} if rt.get("status") == "emesso" else None
    return {"lines": [ln for ln in lines if Decimal(ln["amount"]) > 0], "payments": _payments(db, d), "reference": ref,
            "void": (d.fiscal or {}).get("kind") == "annullo", "total": _s(_d(d.total)), "document": f"RSO {d.number}/{d.year}"}


def register_device(db: Session, reg: PosRegister, role: str) -> Device | None:
    dev_id = (reg.devices or {}).get(role)
    if not dev_id:
        return None
    try:
        dev = db.get(Device, uuid.UUID(str(dev_id)))
    except ValueError:
        return None
    return dev if dev and dev.active else None


def fiscalize(db: Session, reg: PosRegister, d: Document, user_id=None, local_result: dict | None = None) -> None:
    """Documento commerciale per scontrini e resi: lavoro per il registratore, oppure esito già stampato dalla cassa senza rete."""
    if d.doc_type not in ("SCO", "RSO"):
        return
    rt = register_device(db, reg, "rt")
    if rt is None:
        return
    if local_result:  # stampato dall'agent locale mentre mancava internet
        d.fiscal = {**(d.fiscal or {}), "rt": {"status": "emesso", "offline": True,
                                              **{k: v for k, v in local_result.items() if k in ("number", "z", "date", "time", "serial", "simulated")}}}
        flag_modified(d, "fiscal")
        return
    if d.doc_type == "SCO":
        job = enqueue(db, rt, "rt.receipt", receipt_payload(db, d), document_id=d.id, user_id=user_id)
    else:
        from app.documenti.models import DocumentLink
        orig_id = db.scalar(select(DocumentLink.from_id).where(DocumentLink.to_id == d.id))
        job = enqueue(db, rt, "rt.refund", refund_payload(db, d, db.get(Document, orig_id) if orig_id else None), document_id=d.id, user_id=user_id)
    _mirror(db, job)


def close_fiscal_day(db: Session, reg: PosRegister, s: PosSession, user_id=None) -> DeviceJob | None:
    rt = register_device(db, reg, "rt")
    if rt is None or (reg.settings or {}).get("z_on_close") is False:
        return None
    return enqueue(db, rt, "rt.z", {}, session_id=s.id, user_id=user_id)


def text_receipt(d: Document, company, pays: list[PosPayment], register_name: str = "") -> dict:
    """Ricevuta di cortesia per la stampante termica (formato neutro dell'agent)."""
    L = []
    if company:
        L += [{"text": company.name, "align": "center", "bold": True, "size": 2},
              {"text": " ".join(x for x in [company.address, company.zip_code, company.city] if x), "align": "center"}]
        if company.vat_number:
            L.append({"text": f"P.IVA {company.vat_number}", "align": "center"})
    title = {"SCO": "RICEVUTA DI CORTESIA", "RSO": "DOCUMENTO DI RESO", "FTI": f"FATTURA N. {d.number}/{d.year}"}.get(d.doc_type, d.doc_type)
    L += [{"type": "line"}, {"text": title, "align": "center", "bold": True}]
    if d.doc_type == "SCO":
        L.append({"text": "non valida ai fini fiscali", "align": "center"})
    L.append({"type": "line"})
    for ln in sorted(d.lines, key=lambda x: x.line_no):
        amount = docs.gross_amount(ln) if d.prices_vat_included else _d(ln.line_total)
        L.append({"text": ln.description, "right": _s(amount).replace(".", ",")})
        if _d(ln.quantity) != 1:
            L.append({"text": f"  {_d(ln.quantity).normalize():f} x {_s(_d(ln.unit_price_gross)).replace('.', ',')}"})
    L += [{"type": "line"}, {"text": "TOTALE EURO", "right": _s(_d(d.total)).replace(".", ","), "bold": True, "size": 2}]
    change = Decimal((d.fiscal or {}).get("change") or 0)
    for p in pays:
        L.append({"text": {"contanti": "Contanti", "carta": "Carta", "bancomat": "Bancomat"}.get(p.method, p.method.capitalize()),
                  "right": _s(abs(_d(p.tendered if p.tendered is not None else p.amount))).replace(".", ",")})
    if change > 0:
        L.append({"text": "Resto", "right": _s(change).replace(".", ",")})
    rt = (d.fiscal or {}).get("rt") or {}
    L.append({"type": "line"})
    if rt.get("status") == "emesso":
        L.append({"text": f"Documento commerciale {rt.get('z')}-{rt.get('number')}", "align": "center"})
    L.append({"text": f"{register_name} n. {d.number}  {d.doc_date.strftime('%d/%m/%Y')}", "align": "center"})
    if d.number:
        L.append({"type": "barcode", "data": f"S{d.year % 100:02d}{d.number:07d}", "align": "center"})
    L += [{"text": "Grazie e arrivederci", "align": "center"}, {"type": "cut"}]
    return {"lines": L}


def mark_agents_seen(db: Session, agent_ids: list[uuid.UUID]) -> None:
    if agent_ids:
        db.execute(update(Agent).where(Agent.id.in_(agent_ids)).values(last_seen_at=now()))
