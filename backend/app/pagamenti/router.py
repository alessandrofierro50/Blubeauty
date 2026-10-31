"""API dei pagamenti (endpoint del contratto comune pagamenti.md, uguali in ogni software).

- Cliente (amministratore dell'azienda, permesso anche in sola lettura e da sospesi): /api/app/pagamenti/...
- Gestori (senza utente, firma verificata): /api/pagamenti/webhook/stripe, /api/pagamenti/webhook/paypal,
  ritorno del cliente da PayPal /api/pagamenti/paypal/ritorno
- Super amministratore: /api/admin/pagamenti/...

Le email (proforma al cliente, XML a BluCode) partono solo dopo il commit della conferma: prima `db.commit()`, poi
`service.deliver()`.
"""

import csv
import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import passwords
from app.core.config import get_settings
from app.core.db import get_db
from app.core.deps import TenantContext, get_admin, require_role
from app.core.models import SuperAdmin, Tenant
from app.pagamenti import billing as bl
from app.pagamenti import invoice as inv
from app.pagamenti import providers as pv
from app.pagamenti import service as svc
from app.pagamenti.models import METHODS, STATUSES, Payment, PaymentRoute

log = logging.getLogger(__name__)

app_router = APIRouter(prefix="/api/app/pagamenti", tags=["pagamenti"])
public = APIRouter(prefix="/api/pagamenti", tags=["pagamenti"])
admin_router = APIRouter(prefix="/api/admin/pagamenti", tags=["super-admin"])

CHECKOUT_LIMIT = (10, 3600)  # tentativi di pagamento all'ora, per azienda e per IP


def _raise(exc: svc.PaymentError):
    detail = {"code": exc.code, "message": str(exc)} if exc.code else str(exc)
    raise HTTPException(exc.status, detail) from None


# ====================================================================== cliente


@app_router.get("/opzioni")
def options(ctx: TenantContext = Depends(require_role("amministratore"))):
    return svc.options(ctx.db, ctx.state.tenant)


@app_router.put("/dati-fatturazione")
def save_billing(body: bl.BillingIn, ctx: TenantContext = Depends(require_role("amministratore"))):
    try:
        data = svc.save_billing(ctx.db, ctx.state.tenant, body.model_dump(), ctx.user.id)
    except svc.PaymentError as exc:
        _raise(exc)
    return {"ok": True, "dati_fatturazione": data}


class CheckoutIn(BaseModel):
    piano: str = Field(max_length=20)
    periodicita: str = Field(pattern="^(mensile|annuale)$")
    metodo: str = Field(pattern="^(carta|paypal|bonifico)$")


@app_router.post("/checkout")
def checkout(body: CheckoutIn, request: Request, ctx: TenantContext = Depends(require_role("amministratore"))):
    """Nessun prezzo dal browser: solo piano, periodicità e metodo. Risposta {redirect_url} oppure {bonifico: {...}}."""
    if ctx.impersonated_by:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il pagamento lo fa il cliente, non l'assistenza")
    passwords.rate_limit(f"checkout:{ctx.tenant_id}", *CHECKOUT_LIMIT)
    passwords.rate_limit(f"checkout:{passwords.client_ip(request)}", *CHECKOUT_LIMIT)
    try:
        return svc.checkout(ctx.db, ctx.state.tenant, plan_code=body.piano.upper(), period=body.periodicita,
                            method=body.metodo, user_id=ctx.user.id)
    except svc.PaymentError as exc:
        if exc.status >= 500:
            ctx.db.commit()  # il pagamento resta registrato come «fallito»
        _raise(exc)


def _own(ctx: TenantContext, payment_id: uuid.UUID) -> Payment:
    p = ctx.db.scalar(select(Payment).where(Payment.id == payment_id))  # RLS: solo i pagamenti dell'azienda
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pagamento non trovato")
    return p


@app_router.get("/{payment_id}")
def payment_status(payment_id: uuid.UUID, ctx: TenantContext = Depends(require_role("amministratore"))):
    """Per la pagina di esito: lo stato diventa «pagato» quando arriva la notifica del gestore."""
    p = _own(ctx, payment_id)
    out = svc.payment_out(p)
    if p.method == "bonifico" and p.status == "in_attesa":
        out["bonifico"] = svc.bank_details(ctx.db, p)
    return out


@app_router.get("/{payment_id}/pdf")
def payment_pdf(payment_id: uuid.UUID, ctx: TenantContext = Depends(require_role("amministratore"))):
    p = _own(ctx, payment_id)
    if not p.invoice_pdf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento non ancora disponibile")
    return Response(p.invoice_pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Proforma_{p.invoice_number}_{p.invoice_sezionale}.pdf"'})


# ====================================================================== gestori (webhook)


def _deliver_after_webhook(db: Session, payment_id) -> None:
    """Email e invio SDI dopo il commit della conferma. Un errore qui non deve far ripetere il webhook al gestore
    (il pagamento è già confermato): si registra e si rimedia con «Reinvia» dal pannello."""
    if not payment_id:
        return
    try:
        svc.deliver(db, payment_id)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception("Documenti del pagamento %s non inviati dopo il webhook", payment_id)


@public.post("/webhook/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not pv.stripe_configured():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    payload = await request.body()
    try:
        event = pv.stripe_verify(payload, request.headers.get("stripe-signature"))
    except pv.ProviderError as exc:
        log.warning("Webhook Stripe rifiutato: %s", exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Firma non valida") from None
    if not event.get("id"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Evento non valido")
    confirmed = svc.stripe_event(db, event)
    db.commit()
    _deliver_after_webhook(db, confirmed)
    return {"ok": True}


@public.post("/webhook/paypal")
async def paypal_webhook(request: Request, db: Session = Depends(get_db)):
    if not pv.paypal_configured():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    try:
        event = await request.json()
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Evento non valido") from None
    if not isinstance(event, dict) or not event.get("id") or not pv.paypal_verify(request.headers, event):
        log.warning("Webhook PayPal rifiutato (firma non verificata)")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Firma non valida")
    confirmed = svc.paypal_event(db, event)
    db.commit()
    _deliver_after_webhook(db, confirmed)
    return {"ok": True}


@public.get("/paypal/ritorno")
def paypal_return(id: uuid.UUID, token: str, db: Session = Depends(get_db)):
    """Il cliente torna da PayPal dopo aver approvato: si cattura l'ordine lato server e si va alla pagina di esito,
    che attende la conferma (webhook PAYMENT.CAPTURE.COMPLETED)."""
    url = get_settings().public_url.rstrip("/")
    r = svc.route(db, id)
    if r is None or r.provider != "paypal" or r.provider_ref != token:
        return RedirectResponse(f"{url}/pagamento/esito?stato=errore", status_code=303)
    try:
        svc.paypal_capture_order(db, token)
    except pv.ProviderError:
        db.rollback()
        return RedirectResponse(f"{url}/pagamento/esito?stato=errore&id={id}", status_code=303)
    db.commit()
    return RedirectResponse(f"{url}/pagamento/esito?stato=ok&id={id}", status_code=303)


# ====================================================================== super amministratore


class SettingsIn(BaseModel):
    metodi: list[str] | None = None
    iban: str | None = Field(None, max_length=34)
    intestatario: str | None = Field(None, max_length=120)
    bollo_a_carico: str | None = Field(None, pattern="^(cliente|cedente)$")


@admin_router.get("/impostazioni")
def get_settings_(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    return svc.admin_settings(db)


@admin_router.put("/impostazioni")
def put_settings(body: SettingsIn, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    return svc.save_settings(db, body.model_dump(exclude_unset=True), admin.id)


def _rows(db: Session, stato, metodo, tenant_id, q, limit: int):
    stmt = select(PaymentRoute, Tenant.name).join(Tenant, Tenant.id == PaymentRoute.tenant_id)
    if stato:
        stmt = stmt.where(PaymentRoute.status == stato)
    if metodo:
        stmt = stmt.where(PaymentRoute.provider == metodo)
    if tenant_id:
        stmt = stmt.where(PaymentRoute.tenant_id == tenant_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Tenant.name.ilike(like), PaymentRoute.causale.ilike(like), PaymentRoute.invoice.ilike(like)))
    return db.execute(stmt.order_by(PaymentRoute.created_at.desc()).limit(limit)).all()


def _row_out(r: PaymentRoute, name: str) -> dict:
    return {"id": str(r.payment_id), "tenant_id": str(r.tenant_id), "azienda": name, "metodo": r.provider,
            "metodo_label": METHODS.get(r.provider, r.provider), "stato": r.status, "stato_label": STATUSES.get(r.status, r.status),
            "piano": r.plan_code, "periodicita": r.period, "importo": str(r.amount), "totale": str(r.total), "causale": r.causale,
            "fattura": r.invoice, "creato_il": r.created_at.isoformat() if r.created_at else None,
            "pagato_il": r.paid_at.isoformat() if r.paid_at else None}


@admin_router.get("")
def list_payments(stato: str | None = None, metodo: str | None = None, tenant_id: uuid.UUID | None = None,
                  q: str | None = None, limit: int = 200, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    return [_row_out(r, n) for r, n in _rows(db, stato, metodo, tenant_id, q, min(limit, 1000))]


@admin_router.get("/export")
def export_payments(stato: str | None = None, metodo: str | None = None, admin: SuperAdmin = Depends(get_admin),
                    db: Session = Depends(get_db)):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Creato il", "Pagato il", "Azienda", "Piano", "Periodicità", "Metodo", "Stato", "Canone", "Totale", "Causale", "Fattura"])
    for r, n in _rows(db, stato, metodo, None, None, 10000):
        w.writerow([r.created_at.date().isoformat() if r.created_at else "", r.paid_at.date().isoformat() if r.paid_at else "", n,
                    r.plan_code, r.period, METHODS.get(r.provider, r.provider), STATUSES.get(r.status, r.status),
                    str(r.amount).replace(".", ","), str(r.total).replace(".", ","), r.causale, r.invoice or ""])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="pagamenti.csv"'})


def _detail(db: Session, payment_id: uuid.UUID) -> dict:
    try:
        p = svc.load(db, payment_id)
    except svc.PaymentError as exc:
        _raise(exc)
    t = db.get(Tenant, p.tenant_id)
    out = svc.payment_out(p, admin=True)
    out.update({"azienda": t.name, "tenant_id": str(t.id), "email_azienda": t.contact_email})
    if p.method == "bonifico":
        out["bonifico"] = svc.bank_details(db, p)
    return out


@admin_router.get("/{payment_id}")
def get_payment(payment_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    return _detail(db, payment_id)


@admin_router.post("/{payment_id}/conferma-bonifico")
def confirm_transfer(payment_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    """«Conferma bonifico»: solo ora nascono periodo, numero di fattura, XML e proforma; poi partono le email."""
    try:
        _, new = svc.confirm(db, payment_id, by=f"super admin {admin.email}", admin_id=admin.id, manual=True)
        db.commit()
        if new:
            svc.deliver(db, payment_id)
            db.commit()
    except svc.PaymentError as exc:
        _raise(exc)
    return _detail(db, payment_id)


@admin_router.post("/{payment_id}/annulla")
def cancel_payment(payment_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    try:
        svc.cancel(db, payment_id, admin.id)
    except svc.PaymentError as exc:
        _raise(exc)
    return _detail(db, payment_id)


class ResendIn(BaseModel):
    cliente: bool = True
    blucode: bool = True


@admin_router.post("/{payment_id}/reinvia")
def resend(payment_id: uuid.UUID, body: ResendIn | None = None, admin: SuperAdmin = Depends(get_admin),
           db: Session = Depends(get_db)):
    body = body or ResendIn()
    try:
        svc.regenerate(db, payment_id, admin.id)
        db.commit()
        svc.deliver(db, payment_id, customer=body.cliente, admin=body.blucode)
        db.commit()
    except svc.PaymentError as exc:
        _raise(exc)
    return _detail(db, payment_id)


@admin_router.get("/{payment_id}/xml")
def download_xml(payment_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    try:
        p = svc.load(db, payment_id)
    except svc.PaymentError as exc:
        _raise(exc)
    if not p.invoice_xml:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "XML non disponibile")
    return Response(p.invoice_xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{inv.xml_filename(p)}"'})


@admin_router.get("/{payment_id}/pdf")
def download_pdf(payment_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    try:
        p = svc.load(db, payment_id)
    except svc.PaymentError as exc:
        _raise(exc)
    if not p.invoice_pdf:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "PDF non disponibile")
    return Response(p.invoice_pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Proforma_{p.invoice_number}_{p.invoice_sezionale}.pdf"'})
