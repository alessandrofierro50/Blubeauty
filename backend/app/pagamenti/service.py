"""Pagamenti degli abbonamenti: unico punto che scrive `payments`, `payment_routes`, `payment_events`, i contatori delle
fatture e i periodi nati da un pagamento. Router, webhook e pannello passano sempre da qui.

Ciclo di un pagamento (contratto comune pagamenti.md):

    checkout ──► in_attesa ──(webhook firmato Stripe/PayPal, o «Conferma bonifico» del super admin)──► pagato
                     │                                                                                 │
                     └──► annullato (super admin) / fallito (gestore)                  confirm() nella transazione:
                                                                                        nuovo periodo, azienda riattivata,
                                                                                        numero N/BB, XML, PDF
                                                                                        ▼  dopo il commit
                                                                                        deliver(): email + invio SDI

Regole fisse:
- gli importi li calcola il server dal listino del pannello; il browser sceglie solo piano, periodicità e metodo;
- `confirm()` è idempotente: un pagamento già «pagato» non crea un secondo periodo né una seconda fattura;
- per il bonifico prima della conferma non esiste nulla: niente numero, XML, PDF, email né periodo;
- le email partono solo dopo il commit, così non si manda mai una fattura che il database non ha.
"""

import html
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import set_tenant
from app.core.mailer import send_email
from app.core.models import EmailLog, Plan, SaasSetting, Subscription, Tenant
from app.pagamenti import billing as bl
from app.pagamenti import invoice as inv
from app.pagamenti import providers as pv
from app.pagamenti.models import METHODS, STATUSES, Payment, PaymentEvent, PaymentRoute
from app.saas import logic
from app.saas.service import audit, lifecycle_settings, load_tenant, tenant_state, today

log = logging.getLogger(__name__)
PERIODS = ("mensile", "annuale")
SETTINGS_KEY = "pagamenti"


class PaymentError(Exception):
    """Errore da mostrare all'utente (il router lo trasforma in 4xx)."""

    def __init__(self, message: str, status: int = 400, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ====================================================================== impostazioni e metodi


def settings(db: Session) -> dict:
    """Impostazioni del pannello (Impostazioni › Pagamenti) sopra i valori del .env."""
    s = get_settings()
    out = {"metodi": [m.strip() for m in s.pagamenti_metodi.split(",") if m.strip() in METHODS],
           "iban": s.bonifico_iban, "intestatario": s.bonifico_intestatario, "bollo_a_carico": s.bollo_a_carico}
    row = db.get(SaasSetting, SETTINGS_KEY)
    if row and isinstance(row.value, dict):
        out.update({k: v for k, v in row.value.items() if k in out and v not in (None, "")})
    return out


def save_settings(db: Session, body: dict, admin_id=None) -> dict:
    row = db.get(SaasSetting, SETTINGS_KEY)
    cur = dict(row.value) if row and isinstance(row.value, dict) else {}
    if "metodi" in body:
        cur["metodi"] = [m for m in body["metodi"] if m in METHODS]
    for k in ("iban", "intestatario"):
        if k in body:
            cur[k] = (body[k] or "").replace(" ", "").upper() if k == "iban" else (body[k] or "").strip()
    if body.get("bollo_a_carico") in ("cliente", "cedente"):
        cur["bollo_a_carico"] = body["bollo_a_carico"]
    if row is None:
        db.add(SaasSetting(key=SETTINGS_KEY, value=cur))
    else:
        row.value = cur
    audit(db, "pagamenti", "impostazioni", admin_id=admin_id, after={k: v for k, v in cur.items()})
    db.flush()
    return admin_settings(db)


def method_status(db: Session) -> dict[str, dict]:
    """Per ogni metodo: scelto nelle impostazioni? configurato (chiavi nel .env)? → attivo solo se entrambi."""
    st = settings(db)
    ready = {"carta": pv.stripe_configured(), "paypal": pv.paypal_configured(), "bonifico": bool(st["iban"])}
    missing = {"carta": "STRIPE_SECRET_KEY e STRIPE_WEBHOOK_SECRET", "paypal": "PAYPAL_CLIENT_ID, PAYPAL_SECRET e PAYPAL_WEBHOOK_ID",
               "bonifico": "IBAN (BONIFICO_IBAN o Impostazioni › Pagamenti)"}
    return {m: {"label": label, "enabled": m in st["metodi"], "configured": ready[m],
                "active": m in st["metodi"] and ready[m], "missing": None if ready[m] else missing[m]}
            for m, label in METHODS.items()}


def active_methods(db: Session) -> list[str]:
    return [m for m, v in method_status(db).items() if v["active"]]


def admin_settings(db: Session) -> dict:
    s = get_settings()
    st = settings(db)
    return {**st, "methods": method_status(db), "sezionale": s.fatture_sezionale, "invio": s.fatture_invio,
            "regime": s.regime_fiscale, "cedente": inv.cedente(), "cedente_problems": inv.cedente_problems(),
            "paypal_mode": s.paypal_mode,
            "webhooks": {"stripe": f"{s.public_url.rstrip('/')}/api/pagamenti/webhook/stripe",
                         "paypal": f"{s.public_url.rstrip('/')}/api/pagamenti/webhook/paypal"}}


# ====================================================================== indice di sistema


def _sync_route(db: Session, p: Payment) -> None:
    """Allinea `payment_routes` (senza RLS) al pagamento: serve ai webhook, all'elenco del pannello e alla console."""
    values = {"tenant_id": p.tenant_id, "provider": p.method, "provider_ref": p.provider_ref, "status": p.status,
              "amount": p.amount, "total": p.total, "plan_code": p.plan_code, "period": p.period,
              "created_at": p.created_at or _now(), "paid_at": p.paid_at, "subscription_id": p.subscription_id,
              "invoice": p.invoice_label, "causale": p.causale}
    db.execute(insert(PaymentRoute).values(payment_id=p.id, **values)
               .on_conflict_do_update(index_elements=["payment_id"], set_=values))


def route(db: Session, payment_id) -> PaymentRoute | None:
    return db.get(PaymentRoute, payment_id)


def route_by_ref(db: Session, provider: str, ref: str | None) -> PaymentRoute | None:
    if not ref:
        return None
    return db.scalar(select(PaymentRoute).where(PaymentRoute.provider == provider, PaymentRoute.provider_ref == ref))


def load(db: Session, payment_id, lock: bool = False) -> Payment:
    """Carica il pagamento lato sistema: ricava l'azienda dall'indice e imposta il tenant per la RLS."""
    r = route(db, payment_id)
    if r is None:
        raise PaymentError("Pagamento non trovato", 404)
    set_tenant(db, r.tenant_id)
    q = select(Payment).where(Payment.id == r.payment_id)
    p = db.scalar(q.with_for_update() if lock else q)
    if p is None:
        raise PaymentError("Pagamento non trovato", 404)
    return p


# ====================================================================== lato cliente


def plans_offer(db: Session) -> list[dict]:
    st = settings(db)
    out = []
    for p in db.scalars(select(Plan).order_by(Plan.sort_order, Plan.code)):
        prices = {}
        for period in PERIODS:
            price = p.price_month if period == "mensile" else p.price_year
            if Decimal(price or 0) > 0:
                a = inv.amounts(price, st["bollo_a_carico"])
                prices[period] = {"importo": str(a.amount), "bollo": str(a.stamp), "totale": str(a.total)}
        if prices:
            out.append({"code": p.code, "name": p.name, "prezzi": prices})
    return out


def payment_out(p: Payment, *, admin: bool = False) -> dict:
    out = {"id": str(p.id), "piano": p.plan_code, "piano_nome": p.plan_name, "periodicita": p.period, "metodo": p.method,
           "metodo_label": METHODS.get(p.method, p.method), "stato": p.status, "stato_label": STATUSES.get(p.status, p.status),
           "importo": str(p.amount), "bollo": str(p.stamp), "totale": str(p.total), "causale": p.causale,
           "creato_il": p.created_at.isoformat() if p.created_at else None,
           "pagato_il": p.paid_at.isoformat() if p.paid_at else None,
           "periodo": {"dal": p.period_start.isoformat(), "al": p.period_end.isoformat()} if p.period_start else None,
           "fattura": p.invoice_label, "fattura_data": p.invoice_date.isoformat() if p.invoice_date else None,
           "ha_pdf": bool(p.invoice_pdf)}
    if admin:
        out.update({"ha_xml": bool(p.invoice_xml), "errori_fattura": p.invoice_errors or [], "formato": p.invoice_format,
                    "sdi_stato": p.sdi_status, "sdi_file": p.sdi_filename, "sdi_errore": p.sdi_error,
                    "rif_gestore": p.provider_ref, "rif_pagamento": p.provider_payment_ref, "confermato_da": p.confirmed_by,
                    "email_cliente_il": p.customer_email_at.isoformat() if p.customer_email_at else None,
                    "email_admin_il": p.admin_email_at.isoformat() if p.admin_email_at else None,
                    "errore_email": p.email_error, "errore": p.error, "dati_fatturazione": p.billing})
    return out


def bank_details(db: Session, p: Payment) -> dict:
    st = settings(db)
    return {"intestatario": st["intestatario"], "iban": st["iban"], "importo": str(p.total), "causale": p.causale,
            "pagamento": str(p.id)}


def pending_transfer(db: Session, tenant_id) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.tenant_id == tenant_id, Payment.method == "bonifico",
                                           Payment.status == "in_attesa").order_by(Payment.created_at.desc()).limit(1))


def options(db: Session, tenant: Tenant) -> dict:
    """GET /api/app/pagamenti/opzioni (il tenant della sessione è già impostato)."""
    st = tenant_state(tenant)
    pend = pending_transfer(db, tenant.id)
    data = tenant.billing_data or {}
    return {
        "piani": plans_offer(db),
        "metodi": [{"code": m, "label": METHODS[m]} for m in active_methods(db)],
        "dati_fatturazione": data or None,
        "dati_completi": bl.is_complete(data),
        "problemi_dati": bl.problems(data) if data else [],
        "bonifico_in_attesa": {**payment_out(pend), "bonifico": bank_details(db, pend)} if pend else None,
        "attuale": {"piano": st.plan.code if st.plan else None, "periodicita": st.subscription.period if st.subscription else None,
                    "stato": st.status, "scadenza": st.end_date.isoformat() if st.end_date else None,
                    "prova": bool(st.subscription and st.subscription.is_trial)},
        "bollo_a_carico": settings(db)["bollo_a_carico"],
        "pagamenti": [payment_out(p) for p in db.scalars(select(Payment).where(Payment.tenant_id == tenant.id)
                                                          .order_by(Payment.created_at.desc()).limit(20))],
    }


def save_billing(db: Session, tenant: Tenant, body: dict, user_id=None) -> dict:
    data = bl.normalize(body)
    errs = bl.problems(data)
    if errs:
        raise PaymentError("; ".join(errs), 422, "dati_fatturazione")
    before = tenant.billing_data or {}
    tenant.billing_data = data
    audit(db, "tenant", "dati_fatturazione", tenant.id, tenant_id=tenant.id, user_id=user_id, before=before, after=data)
    db.flush()
    return data


def _new_causale() -> tuple[uuid.UUID, str]:
    pid = uuid.uuid4()
    return pid, f"BLUCODE {get_settings().fatture_sezionale} {pid.hex[:8].upper()}"


def checkout(db: Session, tenant: Tenant, *, plan_code: str, period: str, method: str, user_id=None,
             return_urls: tuple[str, str] | None = None) -> dict:
    """POST /api/app/pagamenti/checkout. Crea il pagamento «in_attesa» con l'importo del listino e:
    carta → sessione Stripe Checkout; paypal → ordine PayPal; bonifico → istruzioni (nessun documento)."""
    s = get_settings()
    if period not in PERIODS:
        raise PaymentError("Periodicità non valida")
    if method not in active_methods(db):
        raise PaymentError("Metodo di pagamento non disponibile")
    if not bl.is_complete(tenant.billing_data):
        raise PaymentError("Completa i dati di fatturazione prima di pagare", 422, "dati_fatturazione")
    plan = db.scalar(select(Plan).where(Plan.code == plan_code))
    price = (plan.price_month if period == "mensile" else plan.price_year) if plan else None
    if plan is None or Decimal(price or 0) <= 0:
        raise PaymentError("Piano non disponibile per il pagamento online")
    a = inv.amounts(price, settings(db)["bollo_a_carico"])

    if method == "bonifico":
        pend = pending_transfer(db, tenant.id)
        if pend and pend.plan_code == plan.code and pend.period == period and pend.total == a.total:
            return {"pagamento": str(pend.id), "bonifico": bank_details(db, pend)}
        if pend:  # scelta diversa: il vecchio bonifico non ancora confermato si annulla, così ne resta uno solo
            pend.status, pend.cancelled_at, pend.error = "annullato", _now(), "Sostituito da una nuova richiesta di bonifico"
            _sync_route(db, pend)

    pid, causale = _new_causale()
    p = Payment(id=pid, tenant_id=tenant.id, plan_id=plan.id, plan_code=plan.code, plan_name=plan.name, period=period,
                amount=a.amount, stamp=a.stamp, stamp_duty=a.stamp_duty, total=a.total, method=method, status="in_attesa",
                causale=causale, billing=dict(tenant.billing_data), created_by=user_id, created_at=_now())
    db.add(p)
    db.flush()
    _sync_route(db, p)
    audit(db, "pagamento", "checkout", p.id, tenant_id=tenant.id, user_id=user_id,
          after={"metodo": method, "piano": plan.code, "periodicita": period, "totale": str(a.total)})
    if method == "bonifico":
        db.flush()
        return {"pagamento": str(p.id), "bonifico": bank_details(db, p)}

    url = s.public_url.rstrip("/")
    desc = f"{plan.name if plan.name.lower().startswith(s.brand_name.lower()) else s.brand_name + ' ' + plan.name} - abbonamento {period}"
    try:
        if method == "carta":
            r = pv.stripe_checkout(payment_id=str(p.id), tenant_id=str(tenant.id), description=desc, total=a.total,
                                   email=(tenant.billing_data or {}).get("email") or tenant.contact_email,
                                   success_url=return_urls[0] if return_urls else f"{url}/pagamento/esito?stato=ok&id={p.id}",
                                   cancel_url=return_urls[1] if return_urls else f"{url}/pagamento/esito?stato=annullato&id={p.id}")
        else:
            r = pv.paypal_create_order(payment_id=str(p.id), causale=causale, description=desc, total=a.total,
                                       return_url=f"{url}/api/pagamenti/paypal/ritorno?id={p.id}",
                                       cancel_url=f"{url}/pagamento/esito?stato=annullato&id={p.id}")
    except pv.ProviderError as exc:
        p.status, p.error = "fallito", str(exc)
        _sync_route(db, p)
        db.flush()
        raise PaymentError(str(exc), 502, "gestore_non_disponibile") from None
    p.provider_ref = r["id"]
    _sync_route(db, p)
    db.flush()
    return {"pagamento": str(p.id), "redirect_url": r["url"]}


# ====================================================================== conferma


def _new_period(db: Session, t: Tenant, p: Payment) -> Subscription:
    """Nuovo periodo: dalla fine del periodo in corso; da oggi se è scaduto (tolleranza, sola lettura, sospeso),
    se l'azienda è in prova (la prova si chiude, come «Converti prova») o se è stata sospesa a mano dopo la scadenza.
    L'azienda si riattiva sempre."""
    on = today()
    st = tenant_state(t, on)
    subs = list(t.subscriptions)
    end = logic.effective_end(subs, on)
    trial = st.subscription if st.subscription and st.subscription.is_trial else None
    if end is not None and end >= on and trial is None:
        start = end + timedelta(days=1)
    else:
        start = on
        if trial is not None and trial.end_date >= on:
            trial.end_date = max(trial.start_date, on - timedelta(days=1))
    life = lifecycle_settings(db)
    sub = Subscription(tenant_id=t.id, plan_id=p.plan_id, start_date=start, end_date=logic.next_period(start, p.period),
                       amount=p.amount, period=p.period, is_trial=False, grace_days=life["grace_days"],
                       readonly_days=life["readonly_days"],
                       notes=f"Pagamento online ({METHODS.get(p.method, p.method)}) {p.causale}")
    db.add(sub)
    if t.suspended:
        t.suspended = False
        audit(db, "tenant", "riattivazione", t.id, tenant_id=t.id, after={"da": "pagamento", "pagamento": str(p.id)})
    db.flush()
    return sub


def confirm(db: Session, payment_id, *, by: str, provider_payment_ref: str | None = None,
            paid_total: Decimal | None = None, admin_id=None, manual: bool = False) -> tuple[Payment, bool]:
    """Conferma il pagamento nella transazione corrente. Restituisce (pagamento, appena_confermato).

    Idempotente: il pagamento si blocca con FOR UPDATE, e se è già «pagato» non si fa nulla. Se il gestore comunica un
    importo diverso da quello del listino il pagamento non si conferma (resta da verificare dal pannello)."""
    p = load(db, payment_id, lock=True)
    if p.status == "pagato":
        return p, False
    if manual and (p.method != "bonifico" or p.status != "in_attesa"):
        raise PaymentError("Si confermano a mano solo i bonifici in attesa", 409)
    if paid_total is not None and Decimal(paid_total).quantize(inv.xb.CENT) != Decimal(p.total):
        p.error = f"Importo ricevuto {paid_total} diverso dal dovuto {p.total}: verificare prima di confermare"
        log.error("Pagamento %s: %s", p.id, p.error)
        _sync_route(db, p)
        db.flush()
        return p, False

    t = load_tenant(db, p.tenant_id)
    sub = _new_period(db, t, p)
    p.status, p.paid_at, p.confirmed_by, p.error = "pagato", _now(), by, None
    if provider_payment_ref:
        p.provider_payment_ref = provider_payment_ref
    p.subscription_id, p.period_start, p.period_end = sub.id, sub.start_date, sub.end_date

    s = get_settings()
    p.invoice_date = today()
    p.invoice_sezionale, p.invoice_year = s.fatture_sezionale, p.invoice_date.year
    p.invoice_number = inv.next_number(db, p.invoice_sezionale, p.invoice_year)
    p.invoice_format = inv.transmission_format(p.billing or {})
    _make_documents(db, p)
    p.sdi_status = "da_inviare" if s.fatture_invio == "sdi" else None
    _sync_route(db, p)
    audit(db, "pagamento", "conferma", p.id, tenant_id=p.tenant_id, admin_id=admin_id,
          after={"da": by, "fattura": p.invoice_label, "dal": str(sub.start_date), "al": str(sub.end_date), "totale": str(p.total)})
    db.flush()
    return p, True


def _make_documents(db: Session, p: Payment) -> None:
    """XML (validato sull'XSD) e proforma PDF. Il numero non cambia mai: si rigenerano solo i file."""
    from app.pagamenti.pdf import proforma_pdf

    xml, errs = inv.make_xml(p, settings(db)["iban"])
    p.invoice_xml, p.invoice_errors = xml, errs
    if errs:
        log.error("Fattura %s: %s", p.invoice_label, errs)
    p.invoice_pdf = proforma_pdf(p)


def fail(db: Session, payment_id, reason: str) -> Payment:
    p = load(db, payment_id, lock=True)
    if p.status == "in_attesa":
        p.status, p.error = "fallito", reason
        _sync_route(db, p)
        db.flush()
    return p


def cancel(db: Session, payment_id, admin_id=None) -> Payment:
    """«Annulla pagamento in attesa» (super admin). Un pagamento confermato non si annulla: serve una nota di credito."""
    p = load(db, payment_id, lock=True)
    if p.status != "in_attesa":
        raise PaymentError("Si annullano solo i pagamenti in attesa", 409)
    p.status, p.cancelled_at = "annullato", _now()
    if p.method == "carta" and p.provider_ref and pv.stripe_configured():
        pv.stripe_expire(p.provider_ref)
    _sync_route(db, p)
    audit(db, "pagamento", "annullamento", p.id, tenant_id=p.tenant_id, admin_id=admin_id)
    db.flush()
    return p


# ====================================================================== webhook (lato sistema)


def record_event(db: Session, provider: str, event_id: str, event_type: str | None, payment_id=None) -> bool:
    """Registra l'evento del gestore. False = già elaborato (replay): non si rifà nulla.
    Sta nella stessa transazione dell'elaborazione: se questa fallisce, l'evento non risulta visto e il gestore lo rimanda."""
    r = db.execute(insert(PaymentEvent).values(provider=provider, event_id=event_id, event_type=event_type,
                                               payment_id=payment_id).on_conflict_do_nothing().returning(PaymentEvent.event_id))
    return r.first() is not None


def stripe_event(db: Session, event: dict) -> uuid.UUID | None:
    """Elabora un evento Stripe già verificato. Restituisce l'id del pagamento appena confermato (per le email)."""
    kind = event.get("type") or ""
    obj = (event.get("data") or {}).get("object") or {}
    if not kind.startswith("checkout.session."):
        return None
    pid = (obj.get("metadata") or {}).get("payment_id") or obj.get("client_reference_id")
    r = route(db, _uuid(pid)) if _uuid(pid) else None
    if r is None or r.provider != "carta" or r.provider_ref != obj.get("id"):
        log.warning("Evento Stripe %s per una sessione sconosciuta (%s)", event.get("id"), obj.get("id"))
        return None
    if not record_event(db, "stripe", event["id"], kind, r.payment_id):
        return None
    if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        if obj.get("payment_status") != "paid":
            return None  # metodo asincrono: arriverà async_payment_succeeded
        if (obj.get("currency") or "").lower() != "eur":
            fail(db, r.payment_id, f"Valuta inattesa {obj.get('currency')}")
            return None
        total = Decimal(obj.get("amount_total") or 0) / 100
        p, new = confirm(db, r.payment_id, by="webhook Stripe", provider_payment_ref=obj.get("payment_intent"), paid_total=total)
        return p.id if new else None
    if kind in ("checkout.session.expired", "checkout.session.async_payment_failed"):
        fail(db, r.payment_id, "Pagamento con carta non completato" if kind.endswith("expired") else "Pagamento rifiutato")
    return None


def paypal_capture_order(db: Session, order_id: str) -> Payment | None:
    """Cattura lato server un ordine approvato (ritorno del cliente da PayPal o evento CHECKOUT.ORDER.APPROVED).
    La conferma vera arriva con il webhook PAYMENT.CAPTURE.COMPLETED."""
    r = route_by_ref(db, "paypal", order_id)
    if r is None:
        return None
    p = load(db, r.payment_id, lock=True)
    if p.status != "in_attesa":
        return p
    res = pv.paypal_capture(order_id, str(p.id))
    cap = _first_capture(res)
    if cap and cap.get("id"):
        p.provider_payment_ref = cap["id"]
    db.flush()
    return p


def _first_capture(order: dict) -> dict | None:
    for unit in order.get("purchase_units") or []:
        for cap in ((unit.get("payments") or {}).get("captures") or []):
            return cap
    return None


def paypal_event(db: Session, event: dict) -> uuid.UUID | None:
    kind = event.get("event_type") or ""
    res = event.get("resource") or {}
    if kind == "CHECKOUT.ORDER.APPROVED":
        if record_event(db, "paypal", event["id"], kind):
            try:
                paypal_capture_order(db, res.get("id"))
            except pv.ProviderError:
                log.exception("Cattura PayPal dal webhook non riuscita")
        return None
    if not kind.startswith("PAYMENT.CAPTURE."):
        return None
    order_id = ((res.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
    r = route_by_ref(db, "paypal", order_id)
    if r is None or str(r.payment_id) != (res.get("custom_id") or ""):
        log.warning("Evento PayPal %s per un ordine sconosciuto (%s)", event.get("id"), order_id)
        return None
    if not record_event(db, "paypal", event["id"], kind, r.payment_id):
        return None
    if kind == "PAYMENT.CAPTURE.COMPLETED":
        amt = res.get("amount") or {}
        if (amt.get("currency_code") or "").upper() != "EUR":
            fail(db, r.payment_id, f"Valuta inattesa {amt.get('currency_code')}")
            return None
        p, new = confirm(db, r.payment_id, by="webhook PayPal", provider_payment_ref=res.get("id"),
                         paid_total=Decimal(str(amt.get("value") or "0")))
        return p.id if new else None
    if kind in ("PAYMENT.CAPTURE.DENIED", "PAYMENT.CAPTURE.DECLINED"):
        fail(db, r.payment_id, "Pagamento PayPal rifiutato")
    return None


def _uuid(v) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v))
    except (TypeError, ValueError):
        return None


# ====================================================================== dopo il commit: email e SDI


def _e(v) -> str:
    return html.escape(str(v or ""))


def _eur(v) -> str:
    from app.pagamenti.pdf import eur
    return eur(v)


def _log_email(db: Session, p: Payment, kind: str, to: list[str], subject: str, error: str | None) -> None:
    db.add(EmailLog(tenant_id=p.tenant_id, subscription_id=None, rule=f"pag:{p.id.hex[:10]}:{kind[:3]}:{uuid.uuid4().hex[:12]}",
                    recipients=", ".join(to), subject=subject[:300], success=error is None, error=error))


def deliver(db: Session, payment_id, *, customer: bool = True, admin: bool = True) -> Payment:
    """Proforma PDF al cliente («Ricevuta di pagamento <prodotto>») e XML + riepilogo a ADMIN_NOTIFY_EMAIL; poi, con
    FATTURE_INVIO=sdi, l'invio allo SDI. Da chiamare DOPO il commit della conferma. Usato anche da «Reinvia»."""
    s = get_settings()
    p = load(db, payment_id, lock=True)
    if p.status != "pagato":
        raise PaymentError("Il pagamento non è ancora confermato: nessun documento da inviare", 409)
    t = db.get(Tenant, p.tenant_id)
    b = p.billing or {}
    errors = []
    period = f"dal {p.period_start.strftime('%d/%m/%Y')} al {p.period_end.strftime('%d/%m/%Y')}"
    if customer:
        to = [b.get("email") or t.contact_email]
        subject = f"Ricevuta di pagamento {s.brand_name}"
        body = (f"<div style=\"font-family:Arial,sans-serif;color:#1b2b45;max-width:560px;margin:auto;border-top:4px solid #2340a8;padding:24px\">"
                f"<h2 style=\"color:#2340a8\">Grazie, {_e(bl.display_name(b) or t.name)}</h2>"
                f"<p>abbiamo ricevuto il pagamento di <b>{_eur(p.total)}</b> ({_e(METHODS[p.method])}) per l'abbonamento "
                f"<b>{_e(p.plan_name)}</b> {_e(p.period)}, {period}.</p>"
                f"<p>In allegato trovi la proforma della fattura n. <b>{_e(p.invoice_label)}</b>.</p>"
                f"<p style=\"color:#4a5b75;font-size:13px\">{_e(inv.PROFORMA_NOTE)}.</p>"
                f"<p style=\"color:#4a5b75;font-size:13px\">Il team {_e(s.brand_name)} · BluCode Informatica</p></div>")
        err = None
        try:
            send_email(to, subject, body, [(f"Proforma_{p.invoice_number}_{p.invoice_sezionale}_{p.invoice_year}.pdf",
                                            p.invoice_pdf, "application/pdf")])
            p.customer_email_at = _now()
        except Exception as exc:  # noqa: BLE001  il pagamento resta confermato: si reinvia dal pannello
            log.exception("Ricevuta del pagamento %s non inviata", p.id)
            err = str(exc)[:500]
            errors.append(f"cliente: {err}")
        _log_email(db, p, "ricevuta", to, subject, err)
    if admin and s.admin_notify_email:
        to = [s.admin_notify_email]
        subject = f"{s.brand_name}: pagamento ricevuto, fattura {p.invoice_label} — {t.name}"
        problems = "".join(f"<li>{_e(x)}</li>" for x in p.invoice_errors or [])
        manual = s.fatture_invio != "sdi"
        body = (f"<h2>Pagamento confermato</h2><p><b>{_e(t.name)}</b> ({_e(bl.display_name(b))})<br>"
                f"{_e(p.plan_name)} {_e(p.period)} {period}<br>"
                f"{_e(METHODS[p.method])} · {_eur(p.total)} (canone {_eur(p.amount)}"
                + (f" + rimborso bollo {_eur(p.stamp)}" if p.stamp else "") + f")<br>"
                f"Causale {_e(p.causale)} · riferimento {_e(p.provider_payment_ref or p.provider_ref or '-')} · confermato da {_e(p.confirmed_by)}</p>"
                f"<p>Fattura <b>{_e(p.invoice_label)}</b> del {p.invoice_date.strftime('%d/%m/%Y')} ({_e(p.invoice_format)}).</p>"
                + (f"<p><b>L'XML non è stato generato o non è valido:</b></p><ul>{problems}</ul>" if problems else
                   ("<p>Carica l'XML allegato sul portale Fatture e Corrispettivi dell'Agenzia delle Entrate.</p>" if manual else
                    "<p>L'XML viene inviato allo SDI tramite Aruba: l'esito è nel pannello, alla voce Pagamenti.</p>")))
        att = [(inv.xml_filename(p), p.invoice_xml, "application/xml")] if p.invoice_xml else []
        att.append((f"Proforma_{p.invoice_number}_{p.invoice_sezionale}_{p.invoice_year}.pdf", p.invoice_pdf, "application/pdf"))
        err = None
        try:
            send_email(to, subject, body, att)
            p.admin_email_at = _now()
        except Exception as exc:  # noqa: BLE001
            log.exception("Avviso del pagamento %s a BluCode non inviato", p.id)
            err = str(exc)[:500]
            errors.append(f"BluCode: {err}")
        _log_email(db, p, "xml", to, subject, err)
    p.email_error = "; ".join(errors) or None
    if s.fatture_invio == "sdi" and p.invoice_xml and p.sdi_status in ("da_inviare", "errore"):
        transmit(db, p)
    db.flush()
    return p


def transmit(db: Session, p: Payment) -> None:
    """Invio allo SDI tramite Aruba con l'utenza della piattaforma (ARUBA_*). BluCode deve essere un cedente abilitato
    dell'utenza. L'esito si registra sulla fattura; gli stati successivi si leggono dal pannello Aruba."""
    from app.fatturapa import service as sdi_service
    from app.fatturapa.aruba import ArubaClient, ArubaError

    s = get_settings()
    try:
        client = ArubaClient(s.aruba_username, s.aruba_password, s.aruba_env, transport=sdi_service._transport)
        r = client.upload(p.invoice_xml)
        p.sdi_status, p.sdi_filename, p.sdi_error = "presa_in_carico", r.get("uploadFileName"), None
    except ArubaError as exc:
        p.sdi_status, p.sdi_error = "errore", str(exc)[:500]
        log.error("Fattura %s non inviata allo SDI: %s", p.invoice_label, exc)


def regenerate(db: Session, payment_id, admin_id=None) -> Payment:
    """«Reinvia»: se l'XML mancava o era da correggere (es. dati del cedente impostati dopo), si rigenerano XML e PDF
    con lo stesso numero, poi si rimandano le email. Il numero di fattura non cambia mai."""
    p = load(db, payment_id, lock=True)
    if p.status != "pagato":
        raise PaymentError("Il pagamento non è ancora confermato: nessun documento da inviare", 409)
    if not p.invoice_xml or p.invoice_errors:
        _make_documents(db, p)
    audit(db, "pagamento", "reinvio", p.id, tenant_id=p.tenant_id, admin_id=admin_id)
    db.flush()
    return p
