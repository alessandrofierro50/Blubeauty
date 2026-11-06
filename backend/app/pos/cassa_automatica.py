"""Cassa automatica VNE (Automatic Cash, protocollo 3.06) in cassa: incasso e gestione della macchina tramite l'agent.

Procedura comune BluCode (progetto_blucode_informatica/comune/cassa-automatica-vne.md), come BluOrderScan:
1. «Cassa automatica» in cassa: il server controlla la vendita, calcola il totale e crea il lavoro «cash.payment» per
   l'agent del negozio (il server non vede la rete del negozio). La vendita resta qui (`PosCashMachinePayment`) e il
   carrello è bloccato finché la macchina risponde.
2. L'agent esegue il pagamento in un thread e manda gli avanzamenti (inserito, resto, avvisi); la risposta porta
   l'annullamento chiesto dall'operatore (1 accetta il parziale, 2 restituisci il denaro).
3. Esito: completed → scontrino pagato in contanti (ricevuto = inserito, resto = erogato; inserted = -2 = carta sulla
   macchina) creato SOLO adesso da `pos.service.create_sale` (unico punto che scrive gli incassi della cassa);
   returned/deleted → resta da incassare; partial o nessun riscontro → «da_verificare»: mai un nuovo incasso automatico.
4. Un lavoro non preso dall'agent entro 45 secondi scade come «non eseguito» (la macchina non ha ricevuto nulla).

Gestione (carico, prelievo, svuotamento, apertura porta, azzeramento): lavori «cash.admin»; mai insieme a un pagamento
né a un'altra operazione sulla stessa macchina. Stato e carico: chi incassa; il resto: l'amministrazione."""

import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.periferiche import service as per
from app.periferiche.models import Agent, Device, DeviceJob
from app.pos import service as pos
from app.pos.models import PosCashMachinePayment, PosRegister

CLAIM_SECONDS = 45  # lavoro non preso dall'agent entro 45 s: la cassa non l'ha mai ricevuto
CENT = Decimal("0.01")
ADMIN_OPS = {"prelievo", "svuota", "apri", "azzera"}  # riservate all'amministrazione
OPS = {"stato": "Disponibilità", "carico": "Carico", "prelievo": "Prelievo", "svuota": "Svuotamento", "apri": "Apertura porta",
       "azzera": "Azzeramento cassetti"}
STATUS_LABEL = {"in_corso": "in attesa della cassa automatica", "pagato": "pagato", "annullato": "annullato",
                "non_eseguito": "non eseguito", "da_verificare": "da verificare sul display della cassa", "non_pagato": "non pagato"}
DENOMS = {f"moneta_{d}" for d in (1, 2, 5, 10, 20, 50, 100, 200)} | {f"banconota_{d}" for d in (500, 1000, 2000, 5000, 10000, 20000, 50000)}


def fail(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def cents(v) -> int:
    return int((Decimal(v or 0) * 100).to_integral_value())


def eur(c) -> str:
    return f"{(c or 0) / 100:.2f} €".replace(".", ",")


def machine(db: Session, reg: PosRegister) -> Device | None:
    """Cassa automatica collegata alla cassa (Impostazioni della cassa › periferiche › «Cassa automatica»)."""
    d = per.register_device(db, reg, "cash")
    return d if d and d.kind == "cassa_auto" else None


def webtool_url(d: Device) -> str | None:
    """WebTool della macchina (prelievi, ricariche, chiusure, configurazione): https://IP/tool/."""
    if d.driver != "vne_cash" or not d.address:
        return None
    return f"https://{d.address.strip().split(':')[0]}/tool/"


def _online(db: Session, d: Device) -> Agent:
    a = db.get(Agent, d.agent_id)
    if a is None or not a.active or not per.is_online(a):
        raise fail(f"Il computer «{a.name if a else '?'}» con BluBeauty Agent non è collegato: la cassa automatica non si raggiunge",
                   status.HTTP_409_CONFLICT)
    return a


# ====================================================================== stato dei lavori


def _expire(db: Session, j: DeviceJob, what: str) -> bool:
    return per.expire_unclaimed(db, j, CLAIM_SECONDS,
                                f"Il computer del negozio non ha preso {what} entro {CLAIM_SECONDS} secondi: la cassa automatica non ha ricevuto nulla")


def refresh(db: Session, p: PosCashMachinePayment) -> PosCashMachinePayment:
    """Pagamento in corso: se l'agent non ha preso il lavoro in tempo, si chiude come non eseguito."""
    if p.status == "in_corso" and p.job_id:
        j = db.get(DeviceJob, p.job_id)
        if j is None:
            _finish(p, "da_verificare", "Lavoro della cassa automatica non trovato: controlla il display della cassa")
        elif _expire(db, j, "il pagamento"):
            on_job_result(db, j)
    return p


def _busy(db: Session, d: Device, *, admin_ok: bool = False) -> None:
    """Come chiede VNE: mai due operazioni insieme sulla stessa macchina."""
    for p in db.scalars(select(PosCashMachinePayment).where(PosCashMachinePayment.device_id == d.id, PosCashMachinePayment.status == "in_corso")):
        if refresh(db, p).status == "in_corso":
            raise fail("C'è un pagamento in corso sulla cassa automatica: attendi che finisca", status.HTTP_409_CONFLICT)
    if admin_ok:
        return
    for j in db.scalars(select(DeviceJob).where(DeviceJob.device_id == d.id, DeviceJob.kind == "cash.admin",
                                                DeviceJob.status.in_(("in_coda", "inviato")))):
        if not _expire(db, j, "l'operazione") and j.status in ("in_coda", "inviato"):
            raise fail(f"La cassa automatica sta già eseguendo un'operazione ({OPS.get((j.payload or {}).get('op'), 'gestione')})",
                       status.HTTP_409_CONFLICT)


# ====================================================================== incasso


def start(db: Session, reg: PosRegister, user_id, body: dict, operator: str = "") -> PosCashMachinePayment:
    """Vendita con la cassa automatica: controlli e totale come per i contanti, poi il lavoro per l'agent.

    `body` = stessa vendita di POST /vendite; `payments` sono le ALTRE parti (carta, buono…): alla macchina va il resto."""
    client_uuid = uuid.UUID(str(body["client_uuid"]))
    prev = db.scalar(select(PosCashMachinePayment).where(PosCashMachinePayment.client_uuid == client_uuid))
    if prev is not None:  # doppio clic o rete che rimanda la richiesta: stesso pagamento
        return refresh(db, prev)
    if pos._existing(db, client_uuid) is not None:
        raise fail("Questa vendita è già stata registrata", status.HTTP_409_CONFLICT)
    d = machine(db, reg)
    if d is None:
        raise fail("Nessuna cassa automatica collegata a questa cassa (Vendita al banco › Casse › periferiche)")
    if body.get("rt_result"):
        raise fail("La cassa automatica funziona solo con la connessione al gestionale")
    total = pos.check_sale(db, reg, body)
    others = []
    for p in body.get("payments") or []:
        m, a = p.get("method"), pos._q(p.get("amount")).quantize(CENT)
        if m == pos.CASH:
            raise fail("Con la cassa automatica il contante lo prende la macchina: togli i contanti dal pagamento")
        if m not in pos.METHODS or a <= 0:
            raise fail("Pagamento non valido")
        others.append({"method": m, "amount": str(a)})
    amount = (total - sum((Decimal(p["amount"]) for p in others), Decimal(0))).quantize(CENT)
    if amount <= 0:
        raise fail("Non resta nulla da incassare con la cassa automatica")
    voucher = sum((Decimal(p["amount"]) for p in others if p["method"] == "buono_regalo"), Decimal(0))
    if voucher > 0:  # il buono si controlla adesso: dopo che il cliente ha pagato non si può più rifiutare la vendita
        from app.prepagati import service as prepaid
        if body.get("nonfiscal_reason") or body.get("invoice_party_id"):
            raise fail("Il buono regalo multiuso si usa con lo scontrino fiscale")
        prepaid.check_bank_voucher(db, body.get("voucher_code"), voucher)
    _busy(db, d)
    _online(db, d)
    ses = pos._session_for(db, reg, body.get("session_id"))
    sale = {**body, "client_uuid": str(client_uuid), "session_id": str(ses.id), "payments": others}
    job = per.enqueue(db, d, "cash.payment", {"amount_cents": cents(amount), "reference": f"Cassa {reg.code}", "operator": operator[:60]},
                      user_id=user_id)
    p = PosCashMachinePayment(tenant_id=reg.tenant_id, register_id=reg.id, session_id=ses.id, device_id=d.id, job_id=job.id,
                              client_uuid=client_uuid, status="in_corso", total=total, amount=amount, sale=sale, result={},
                              cancel_request=0, resolution={}, created_by=user_id)
    db.add(p)
    db.flush()
    return p


def _finish(p: PosCashMachinePayment, st: str, message: str, result: dict | None = None) -> None:
    p.status, p.message = st, message[:1000]
    if result is not None:
        p.result = result
        flag_modified(p, "result")


def outcome(job: DeviceJob) -> dict:
    """Esito del lavoro «cash.payment» → stato del pagamento (stesse regole di BluOrderScan, gateway.vne_outcome)."""
    res = job.result or {}
    if job.status == "eseguito":
        st, inserted, rest = res.get("status"), int(res.get("inserted") or 0), int(res.get("rest") or 0)
        card = inserted == -2
        if st == "completed":
            return {"status": "pagato", "card": card, "inserted": inserted, "rest": rest,
                    "message": "Pagato con carta sulla cassa automatica" if card else f"Inseriti {eur(inserted)}, resto {eur(rest)}"}
        who = f" da {res['cancelled_by']}" if res.get("cancelled_by") else ""
        if st == "partial":
            kept = 0 if card else max(0, inserted - rest)
            return {"status": "da_verificare", "partial": True, "kept": kept,
                    "message": f"Annullato{who} accettando il pagamento parziale: la cassa ha trattenuto {eur(kept)}. "
                               "Incassa la differenza in altro modo e registra la vendita da «Da verificare»"}
        if st == "returned":
            return {"status": "annullato", "message": f"Pagamento annullato{who}: {eur(inserted)} restituiti al cliente"}
        if st == "deleted":
            return {"status": "annullato", "message": f"Pagamento annullato{who} prima dell'inserimento del denaro"}
        return {"status": "da_verificare", "message": f"Esito sconosciuto della cassa automatica ({st}): controlla il display"}
    if job.status == "annullato":
        return {"status": "annullato", "message": "Annullato prima dell'invio alla cassa automatica"}
    if job.status == "errore" and res.get("sent") is False:
        return {"status": "non_eseguito", "message": job.error or "Pagamento non eseguito dalla cassa automatica"}
    return {"status": "da_verificare",
            "message": job.error or "Nessun riscontro dalla cassa automatica: controlla il display prima di incassare di nuovo"}


def on_job_result(db: Session, job: DeviceJob) -> None:
    """Esito della macchina (chiamato da periferiche.service.complete, o alla scadenza del lavoro)."""
    p = db.scalar(select(PosCashMachinePayment).where(PosCashMachinePayment.job_id == job.id))
    if p is None or p.status != "in_corso":
        return
    out = outcome(job)
    final = {k: v for k, v in (job.result or {}).items() if k != "cancel"} if job.status == "eseguito" else {}
    if out["status"] != "pagato":
        _finish(p, out["status"], out["message"], {**final, **{k: out[k] for k in ("partial", "kept") if k in out}})
        db.flush()
        return
    amount = pos._q(p.amount)
    if out["card"]:
        machine_pay = [{"method": "carta", "amount": str(amount)}]
    else:  # ricevuto = inserito, resto = erogato: lo scontrino è pagato in contanti come al banco
        machine_pay = [{"method": pos.CASH, "amount": str((Decimal(out["inserted"]) / 100).quantize(CENT))}]
    _register(db, p, machine_pay, out["message"], {**final, "card": out["card"]})


def _register(db: Session, p: PosCashMachinePayment, machine_pay: list[dict], message: str, result: dict) -> bool:
    """Registra la vendita (scontrino, scarico, documento commerciale sul registratore) col pagamento della macchina."""
    reg = db.get(PosRegister, p.register_id)
    body = {**p.sale, "payments": [*(p.sale.get("payments") or []), *machine_pay]}
    try:
        with db.begin_nested():
            d, change, _ = pos.create_sale(db, reg, p.created_by, body)
            d.fiscal = {**(d.fiscal or {}), "cash_machine": {"payment_id": str(p.id), "device_id": str(p.device_id) if p.device_id else None,
                                                             "inserted": result.get("inserted"), "rest": result.get("rest"),
                                                             "card": bool(result.get("card")), "id": result.get("id")}}
            flag_modified(d, "fiscal")
            db.flush()
    except HTTPException as e:  # es. cassa chiusa nel frattempo: il denaro c'è, la vendita va registrata a mano
        detail = e.detail if isinstance(e.detail, str) else str(e.detail)
        _finish(p, "da_verificare", f"La cassa automatica ha incassato ({message}) ma la vendita non si è registrata: {detail}", result)
        db.flush()
        return False
    p.document_id = d.id
    _finish(p, "pagato", message, result)
    db.flush()
    return True


def request_cancel(db: Session, p: PosCashMachinePayment, mode: str) -> PosCashMachinePayment:
    """Annullamento chiesto dall'operatore: «restituisci» il denaro inserito o accetta il «parziale»."""
    refresh(db, p)
    if p.status != "in_corso":
        raise fail("Nessun pagamento in attesa sulla cassa automatica da annullare", status.HTTP_409_CONFLICT)
    j = db.get(DeviceJob, p.job_id) if p.job_id else None
    if j is not None and j.status == "in_coda":  # non ancora preso dall'agent: si ritira (UPDATE condizionato)
        res = db.execute(update(DeviceJob).where(DeviceJob.id == j.id, DeviceJob.status == "in_coda").values(status="annullato", done_at=per.now()))
        db.refresh(j)
        if res.rowcount:
            on_job_result(db, j)
            return p
    code = 1 if mode == "parziale" else 2
    p.cancel_request = code
    if j is not None:
        per.request_stop(db, j, code)
    db.flush()
    return p


def resolve(db: Session, p: PosCashMachinePayment, user_id, esito: str, metodo: str | None, note: str) -> PosCashMachinePayment:
    """Verifica manuale di un esito incerto (display della cassa): «pagato» registra la vendita, «non_pagato» la libera."""
    if p.status != "da_verificare":
        raise fail("Il pagamento non è da verificare", status.HTTP_409_CONFLICT)
    p.resolution = {"by": str(user_id) if user_id else None, "at": per.now().isoformat(), "esito": esito, "note": note, "metodo": metodo}
    flag_modified(p, "resolution")
    if esito == "non_pagato":
        _finish(p, "non_pagato", f"Verifica manuale: non pagato. {note}".strip())
        db.flush()
        return p
    amount = pos._q(p.amount)
    kept = (Decimal(int((p.result or {}).get("kept") or 0)) / 100).quantize(CENT) if (p.result or {}).get("partial") else amount
    kept = min(kept, amount)
    machine_pay = [{"method": pos.CASH, "amount": str(kept)}] if kept > 0 else []
    if kept < amount:  # parziale: la differenza incassata in altro modo
        if not metodo or metodo not in pos.METHODS or metodo == "buono_regalo":
            raise fail(f"La cassa automatica ha trattenuto {eur(cents(kept))}: indica come hai incassato i restanti {eur(cents(amount - kept))}")
        machine_pay.append({"method": metodo, "amount": str(amount - kept)})
    if not _register(db, p, machine_pay, f"Verifica manuale: pagato. {note}".strip(), dict(p.result or {})):
        raise fail(p.message or "Vendita non registrata", status.HTTP_409_CONFLICT)
    return p


def payment_out(db: Session, p: PosCashMachinePayment, receipt: bool = True) -> dict:
    j = db.get(DeviceJob, p.job_id) if p.job_id else None
    live = dict(((j.result or {}).get("progress") or {}) if j is not None else {})
    if p.status != "in_corso" and p.result:
        live.update({k: v for k, v in p.result.items() if k in ("amount", "inserted", "rest", "status", "card", "not_returned")})
    out = {"id": str(p.id), "status": p.status, "status_label": STATUS_LABEL.get(p.status, p.status), "register_id": str(p.register_id),
           "client_uuid": str(p.client_uuid), "total": str(p.total), "amount": str(p.amount), "amount_cents": cents(p.amount),
           "job_status": j.status if j is not None else None, "live": live, "cancel_request": p.cancel_request, "message": p.message,
           "partial": bool((p.result or {}).get("partial")), "kept_cents": int((p.result or {}).get("kept") or 0),
           "document_id": str(p.document_id) if p.document_id else None, "resolution": p.resolution or {},
           "created_at": p.created_at.isoformat() if p.created_at else None, "lines": len(p.sale.get("lines") or [])}
    if receipt and p.document_id:
        from app.documenti.models import Document
        d = db.get(Document, p.document_id)
        out["receipt"] = pos.receipt_out(db, d) if d else None
    return out


# ====================================================================== gestione della macchina


def admin_op(db: Session, reg: PosRegister, user_id, op: str, body: dict, operator: str = "") -> DeviceJob:
    d = machine(db, reg)
    if d is None:
        raise fail("Nessuna cassa automatica collegata a questa cassa", status.HTTP_404_NOT_FOUND)
    _busy(db, d)
    _online(db, d)
    if op == "prelievo":
        denoms = {k: int(v) for k, v in (body.get("denoms") or {}).items() if int(v) > 0}
        if set(denoms) - DENOMS:
            raise fail("Tagli non validi")
        if denoms:
            body["amount_cents"] = sum(int(k.split("_")[1]) * v for k, v in denoms.items())
        if not int(body.get("amount_cents") or 0):
            raise fail("Indica l'importo da prelevare")
        body["denoms"] = denoms
    return per.enqueue(db, d, "cash.admin", {"op": op, **body, "operator": operator[:60]}, user_id=user_id)


def admin_refresh(db: Session, j: DeviceJob) -> DeviceJob:
    _expire(db, j, "l'operazione")
    return j


def admin_stop(db: Session, j: DeviceJob) -> DeviceJob:
    """Fine carico / fine prelievo (o ritiro dell'operazione ancora in coda)."""
    admin_refresh(db, j)
    if j.status == "in_coda":
        db.execute(update(DeviceJob).where(DeviceJob.id == j.id, DeviceJob.status == "in_coda").values(status="annullato", done_at=per.now()))
        db.refresh(j)
    if j.status == "inviato":
        per.request_stop(db, j, 2)
    elif j.status not in ("annullato",):
        raise fail("Operazione già conclusa", status.HTTP_409_CONFLICT)
    return j


def admin_out(j: DeviceJob) -> dict:
    res = j.result or {}
    return {"id": str(j.id), "op": (j.payload or {}).get("op"), "op_label": OPS.get((j.payload or {}).get("op"), ""), "status": j.status,
            "progress": res.get("progress") or {}, "result": {k: v for k, v in res.items() if k not in ("progress", "cancel")} if j.status == "eseguito" else {},
            "cancel_request": int(res.get("cancel") or 0), "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None}


def last_cash(db: Session, d: Device) -> dict | None:
    """Ultimo contenuto letto (stato, operazioni di gestione, prova del dispositivo)."""
    for j in db.scalars(select(DeviceJob).where(DeviceJob.device_id == d.id, DeviceJob.status == "eseguito",
                                                DeviceJob.kind.in_(("cash.admin", "status"))).order_by(DeviceJob.done_at.desc()).limit(5)):
        if (j.result or {}).get("cash"):
            return {**j.result["cash"], "read_at": j.done_at.isoformat() if j.done_at else None}
    return None


def overview(db: Session, reg: PosRegister) -> dict:
    d = machine(db, reg)
    if d is None:
        return {"device": None, "payments": [], "job": None, "cash": None}
    a = db.get(Agent, d.agent_id)
    open_pays = [refresh(db, p) for p in db.scalars(select(PosCashMachinePayment).where(
        PosCashMachinePayment.register_id == reg.id, PosCashMachinePayment.status.in_(("in_corso", "da_verificare")))
        .order_by(PosCashMachinePayment.created_at.desc()).limit(20))]
    job = db.scalar(select(DeviceJob).where(DeviceJob.device_id == d.id, DeviceJob.kind == "cash.admin",
                                            DeviceJob.status.in_(("in_coda", "inviato"))).order_by(DeviceJob.created_at.desc()))
    if job is not None:
        admin_refresh(db, job)
    return {"device": {"id": str(d.id), "name": d.name, "driver": d.driver, "address": d.address, "webtool_url": webtool_url(d),
                       "agent_name": a.name if a else None, "agent_online": per.is_online(a) if a else False},
            "payments": [payment_out(db, p, receipt=False) for p in open_pays if p.status in ("in_corso", "da_verificare")],
            "job": admin_out(job) if job is not None else None, "cash": last_cash(db, d)}
