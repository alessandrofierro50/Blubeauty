"""API fatturazione elettronica: /api/fatturapa/...  (modulo extra "fatturapa").

Le callback di Aruba (/api/fatturapa/callback/...) non hanno utente: si autenticano con l'api-key scelta nel pannello
Aruba e l'azienda si ricava dalla partita IVA del cedente (tabella einvoice_routes)."""

import hmac
import os
import uuid
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.anagrafiche.models import Party
from app.core import media
from app.core.config import get_settings
from app.core.db import get_db, set_tenant
from app.core.deps import TenantContext, require_module
from app.documenti.models import Document
from app.fatturapa import service as sdi
from app.fatturapa.aruba import ArubaError
from app.fatturapa.models import RESENDABLE, STATUS_LABELS, EInvoice, EInvoiceInbox
from app.saas.service import audit

router = APIRouter(prefix="/api/fatturapa", tags=["fatturapa"])
reader_base = require_module("fatturapa")


def reader(ctx: TenantContext = Depends(reader_base)) -> TenantContext:
    if ctx.user.role in ("cassa", "magazzino", "agente"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può usare la fatturazione elettronica")
    return ctx


def admin(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role not in ("amministratore", "amministrazione"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo l'amministrazione può modificare il collegamento ad Aruba")
    return ctx


def _aruba(exc: ArubaError) -> HTTPException:
    return HTTPException(status.HTTP_502_BAD_GATEWAY if exc.status and exc.status >= 500 else status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


def einvoice_out(e: EInvoice) -> dict:
    return {"id": str(e.id), "attempt": e.attempt, "progressive": e.progressive, "format": e.format, "filename": e.filename,
            "sdi_id": e.sdi_id, "status": e.status, "status_label": STATUS_LABELS.get(e.status, e.status), "errors": e.errors or [],
            "notifications": e.notifications or [], "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            "checked_at": e.checked_at.isoformat() if e.checked_at else None, "can_resend": e.status in RESENDABLE,
            "xml_url": f"/api/fatturapa/trasmissioni/{e.id}/xml"}


def _doc(db: Session, doc_id: uuid.UUID) -> Document:
    d = db.scalar(select(Document).where(Document.id == doc_id, Document.direction == "vendita").options(selectinload(Document.lines)))
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento non trovato")
    return d


# ====================================================================== impostazioni


@router.get("/impostazioni")
def get_settings_(ctx: TenantContext = Depends(reader)):
    return sdi.public_settings(ctx.db, ctx.tenant_id)


class SettingsIn(BaseModel):
    mode: str = Field(pattern="^(piattaforma|proprio)$")
    username: str = ""
    password: str | None = None  # vuoto = lascia quella salvata
    auto_send: bool = False
    sign_domain: str = ""
    sign_credential: str | None = None


@router.put("/impostazioni")
def put_settings(body: SettingsIn, ctx: TenantContext = Depends(admin)):
    out = sdi.save_settings(ctx.db, ctx.tenant_id, body.model_dump())
    audit(ctx.db, "fatturapa", "impostazioni", None, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after={"mode": body.mode})
    return out


@router.post("/impostazioni/prova")
def test_connection(ctx: TenantContext = Depends(admin)):
    try:
        info = sdi.client_for(ctx.db, ctx.tenant_id).user_info()
    except ArubaError as exc:
        raise _aruba(exc) from None
    return {"ok": True, "user": info.get("userDescription") or info.get("username"), "vat": info.get("vatCode"),
            "expires": (info.get("accountStatus") or {}).get("expirationDate"), "expired": (info.get("accountStatus") or {}).get("expired")}


# ====================================================================== fatture emesse


@router.get("/documenti/{doc_id}")
def doc_state(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    d = _doc(ctx.db, doc_id)
    rows = ctx.db.scalars(select(EInvoice).where(EInvoice.document_id == d.id).order_by(EInvoice.attempt.desc())).all()
    chk = sdi.xb.precheck(ctx.db, d) if d.doc_type in sdi.xb.TIPO else None
    return {"transmissions": [einvoice_out(e) for e in rows], "current": einvoice_out(rows[0]) if rows else None,
            "check": {"errors": chk.errors, "warnings": chk.warnings} if chk else None,
            "can_send": d.doc_type in sdi.xb.TIPO and d.status in ("confermato", "evaso") and (not rows or rows[0].status in RESENDABLE)}


@router.get("/documenti/{doc_id}/xml")
def preview_xml(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    """XML come verrebbe inviato adesso (anteprima, anche per controllo del commercialista)."""
    d = _doc(ctx.db, doc_id)
    r = _xml_for(ctx.db, d) if d.number else None
    if r is None:
        chk, xml, xsd = sdi.prepare(ctx.db, d)
        r = "; ".join(chk.errors) if xml is None else (f"fattura-bozza-{d.year}.xml", xml)
    if isinstance(r, str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, r)
    from fastapi.responses import Response
    return Response(r[1], media_type="application/xml", headers={"Content-Disposition": f'attachment; filename="{r[0]}"'})


def _xml_for(db: Session, d: Document) -> tuple[str, bytes] | str:
    """XML da esportare: il file trasmesso se la fattura è già stata inviata, altrimenti quello generato adesso.
    Restituisce (nome file, contenuto) oppure il testo dell'errore."""
    e = sdi.latest(db, d.id)
    if e is not None and e.xml_file:
        path = os.path.join(media.media_dir(), e.xml_file)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return (e.filename or f"fattura-{d.number}-{d.year}.xml").replace(".p7m", ""), f.read()
    chk, xml, xsd = sdi.prepare(db, d, sdi.xb.export_progressive(d))
    if xml is None:
        return "; ".join(chk.errors)
    name = f"{'NC' if d.doc_type == 'NC' else 'FT'}-{d.number}{'-' + d.series if d.series else ''}-{d.year}.xml"
    return name, xml


@router.get("/esporta")
def export_xml(dal: date, al: date, ctx: TenantContext = Depends(reader)):
    """ZIP con gli XML delle fatture e note di credito emesse nel periodo (per il commercialista o l'archivio).
    Le fatture che non si possono generare finiscono in ERRORI.txt con il motivo."""
    import io
    import zipfile

    from fastapi.responses import Response
    if al < dal:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La data finale è prima di quella iniziale")
    db = ctx.db
    rows = db.scalars(select(Document).where(
        Document.direction == "vendita", Document.doc_type.in_(list(sdi.xb.TIPO)), Document.status.in_(("confermato", "evaso")),
        Document.doc_date >= dal, Document.doc_date <= al).options(selectinload(Document.lines))
        .order_by(Document.doc_date, Document.number)).all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nessuna fattura emessa nel periodo")
    buf, errors, names = io.BytesIO(), [], set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in rows:
            r = _xml_for(db, d)
            label = f"{ {'FTI': 'Fattura', 'FTD': 'Fattura differita', 'NC': 'Nota di credito'}[d.doc_type]} n. {d.number}/{d.year} del {d.doc_date.strftime('%d/%m/%Y')}"
            if isinstance(r, str):
                errors.append(f"{label}: {r}")
                continue
            name = r[0]
            while name in names:
                name = name.replace(".xml", "_bis.xml")
            names.add(name)
            z.writestr(name, r[1])
        if errors:
            z.writestr("ERRORI.txt", "Fatture non esportate (da correggere):\n\n" + "\n".join(errors) + "\n")
    audit(db, "document", "esporta_xml", None, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          after={"dal": dal.isoformat(), "al": al.isoformat(), "file": len(names), "errori": len(errors)})
    fname = f"fatture-xml-{dal.isoformat()}_{al.isoformat()}.zip"
    return Response(buf.getvalue(), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{fname}"', "X-Esportate": str(len(names)), "X-Errori": str(len(errors)),
        "Access-Control-Expose-Headers": "X-Esportate, X-Errori"})


@router.post("/documenti/{doc_id}/verifica")
def verify(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    return sdi.verify(ctx.db, _doc(ctx.db, doc_id))


@router.post("/documenti/{doc_id}/invia")
def send(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    d = _doc(ctx.db, doc_id)
    e = sdi.send(ctx.db, d, ctx.user.id)
    audit(ctx.db, "document", "invio_sdi", d.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          after={"esito": e.status, "file": e.filename, "tentativo": e.attempt})
    return einvoice_out(e)


class ManyIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


@router.post("/invia-multiplo")
def send_many(body: ManyIn, ctx: TenantContext = Depends(reader)):
    out = []
    for i in body.ids:
        d = _doc(ctx.db, i)
        try:
            e = sdi.send(ctx.db, d, ctx.user.id)
            out.append({"id": str(i), "number": d.number, "status": e.status, "error": (e.errors or [{}])[0].get("description") if e.errors else None})
        except HTTPException as exc:
            out.append({"id": str(i), "number": d.number, "status": "non_inviata", "error": exc.detail})
    return {"results": out, "sent": sum(1 for r in out if r["status"] == "presa_in_carico")}


@router.post("/documenti/{doc_id}/aggiorna")
def refresh(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    e = sdi.latest(ctx.db, doc_id)
    if e is None or not e.filename:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La fattura non è ancora stata presa in carico da Aruba")
    try:
        sdi.refresh(ctx.db, e)
    except ArubaError as exc:
        raise _aruba(exc) from None
    return einvoice_out(e)


@router.get("/trasmissioni/{tid}/xml")
def sent_xml(tid: uuid.UUID, ctx: TenantContext = Depends(reader)):
    e = ctx.db.get(EInvoice, tid)
    if e is None or not e.xml_file:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File non trovato")
    return FileResponse(os.path.join(media.media_dir(), e.xml_file), media_type="application/xml",
                        filename=e.filename.replace(".p7m", "") if e.filename else f"fattura-{e.progressive}.xml")


@router.get("/stato")
def overview(ctx: TenantContext = Depends(reader)):
    """Riepilogo per la home e per l'elenco: fatture da inviare, scartate, in attesa."""
    db = ctx.db
    sent_ids = select(EInvoice.document_id)
    to_send = db.scalar(select(func.count()).select_from(Document).where(
        Document.direction == "vendita", Document.doc_type.in_(list(sdi.xb.TIPO)), Document.status.in_(("confermato", "evaso")),
        ~Document.id.in_(sent_ids))) or 0
    last = {}
    for e in db.scalars(select(EInvoice).order_by(EInvoice.document_id, EInvoice.attempt)):
        last[e.document_id] = e
    by = {}
    for e in last.values():
        by[e.status] = by.get(e.status, 0) + 1
    inbox = db.scalar(select(func.count()).select_from(EInvoiceInbox).where(EInvoiceInbox.status == "da_registrare")) or 0
    return {"to_send": to_send, "by_status": by, "inbox": inbox}


# ====================================================================== fatture ricevute


def inbox_out(r: EInvoiceInbox) -> dict:
    return {"id": str(r.id), "filename": r.filename, "sdi_id": r.sdi_id, "supplier_name": r.supplier_name, "supplier_vat": r.supplier_vat,
            "number": r.number, "invoice_date": r.invoice_date.isoformat() if r.invoice_date else None, "doc_type": r.doc_type,
            "total": str(r.total) if r.total is not None else None, "status": r.status, "document_id": str(r.document_id) if r.document_id else None,
            "received_at": r.received_at.isoformat(), "xml_url": f"/api/fatturapa/ricevute/{r.id}/xml"}


@router.get("/ricevute")
def inbox(stato: str = Query("da_registrare", pattern="^(da_registrare|registrata|ignorata|tutte)$"), ctx: TenantContext = Depends(reader)):
    stmt = select(EInvoiceInbox)
    if stato != "tutte":
        stmt = stmt.where(EInvoiceInbox.status == stato)
    rows = ctx.db.scalars(stmt.order_by(EInvoiceInbox.invoice_date.desc().nulls_last(), EInvoiceInbox.received_at.desc()).limit(500)).all()
    return {"rows": [inbox_out(r) for r in rows], "settings": sdi.public_settings(ctx.db, ctx.tenant_id)}


@router.post("/ricevute/sincronizza")
def inbox_sync(ctx: TenantContext = Depends(reader)):
    try:
        n = sdi.sync_received(ctx.db, ctx.tenant_id)
    except ArubaError as exc:
        raise _aruba(exc) from None
    return {"received": n}


class InboxStatusIn(BaseModel):
    status: str = Field(pattern="^(da_registrare|ignorata)$")


@router.post("/ricevute/{rid}/stato")
def inbox_status(rid: uuid.UUID, body: InboxStatusIn, ctx: TenantContext = Depends(reader)):
    r = ctx.db.get(EInvoiceInbox, rid)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fattura non trovata")
    if r.status == "registrata":
        raise HTTPException(status.HTTP_409_CONFLICT, "La fattura è già registrata negli acquisti")
    r.status = body.status
    return inbox_out(r)


@router.get("/ricevute/{rid}/xml")
def inbox_xml(rid: uuid.UUID, ctx: TenantContext = Depends(reader)):
    r = ctx.db.get(EInvoiceInbox, rid)
    if r is None or not r.xml_file:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File non trovato")
    return FileResponse(os.path.join(media.media_dir(), r.xml_file), media_type="application/xml", filename=r.filename.replace(".p7m", ""))


# ====================================================================== simulatore SDI (solo ambiente demo di Aruba)


@router.post("/simula/ricevuta")
def simulate_received(ctx: TenantContext = Depends(admin)):
    from app.core.models import Company
    co = ctx.db.scalar(select(Company).order_by(Company.name))
    try:
        r = sdi.client_for(ctx.db, ctx.tenant_id).simulate_received(sdi.xb.split_vat(co.vat_number)[1])
    except ArubaError as exc:
        raise _aruba(exc) from None
    return r


class SimNotifyIn(BaseModel):
    type: str = Field(pattern="^(NS|MC|AT|RC|NE_EC01|NE_EC02|DT)$")


@router.post("/documenti/{doc_id}/simula-notifica")
def simulate_notification(doc_id: uuid.UUID, body: SimNotifyIn, ctx: TenantContext = Depends(admin)):
    e = sdi.latest(ctx.db, doc_id)
    if e is None or not e.filename:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invia prima la fattura")
    try:
        sdi.client_for(ctx.db, ctx.tenant_id).simulate_notification(e.filename, body.type)
    except ArubaError as exc:
        raise _aruba(exc) from None
    return {"ok": True}


# ====================================================================== callback di Aruba


callbacks = APIRouter(prefix="/api/fatturapa/callback", tags=["fatturapa-callback"])


def _check_key(authorization: str | None) -> None:
    key = get_settings().aruba_callback_key
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not key or not hmac.compare_digest(given, key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "api-key non valida")


async def _payload(request: Request) -> dict:
    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON non valido") from None
    if not isinstance(data, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "JSON non valido")
    return data


def _route(db: Session, data: dict):
    tid = sdi.tenant_for_vat(db, data.get("countryCode"), data.get("vatCode"))
    if tid is None:
        return None
    set_tenant(db, tid)
    return tid


@callbacks.post("/createInvoice")
async def cb_invoice(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    _check_key(authorization)
    data = await _payload(request)
    if not data.get("invoiceXmlBase64"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Fattura mancante")
    tid = _route(db, data)
    if tid is None:
        return JSONResponse({"result": "ignorata: partita IVA non gestita"})
    sdi.callback_invoice(db, tid, data)
    return {"result": "ok"}


@callbacks.post("/createNotification")
async def cb_notification(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    _check_key(authorization)
    data = await _payload(request)
    if _route(db, data) is None:
        return {"result": "ignorata"}
    sdi.callback_notification(db, data)
    return {"result": "ok"}


@callbacks.post("/updateInvoiceStatus")
async def cb_status(request: Request, authorization: str | None = Header(None), db: Session = Depends(get_db)):
    _check_key(authorization)
    data = await _payload(request)
    if _route(db, data) is None:
        return {"result": "ignorata"}
    sdi.callback_status(db, data)
    return {"result": "ok"}


@callbacks.post("/updateUsage")
async def cb_usage(request: Request, authorization: str | None = Header(None)):
    _check_key(authorization)
    await _payload(request)
    return {"result": "ok"}


def today() -> date:
    return date.today()
