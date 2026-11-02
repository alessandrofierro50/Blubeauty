"""Iscrizione alla prova gratuita dal sito (pagina pubblica /prova, linkata da blucodeinformatica.it): /api/public/...

Crea l'azienda in prova e manda per email nome utente e password provvisoria: la password non compare mai sulla
pagina, così l'accesso arriva solo a chi possiede davvero quell'indirizzo email.
Protezioni: campo trappola per i robot, tempo minimo di compilazione, limiti per IP, per email e al giorno."""

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.validators import valid_vat_it
from app.auth import passwords
from app.core.config import get_settings
from app.core.db import get_db, set_tenant
from app.core.mailer import send_email
from app.core.models import Plan, Tenant
from app.saas.service import today

router = APIRouter(prefix="/api/public", tags=["pubblico"])
log = logging.getLogger(__name__)
MIN_SECONDS = 3  # un modulo compilato più in fretta è di un robot


def _plan(db: Session) -> Plan | None:
    code = get_settings().trial_plan.strip().upper()
    return db.scalar(select(Plan).where(Plan.code == code)) if code else None


@router.get("/prova")
def trial_info(db: Session = Depends(get_db)):
    s = get_settings()
    plan = _plan(db)
    return {"enabled": plan is not None, "product": "BluBeauty", "plan": plan.name if plan else None, "days": s.trial_days,
            "terms_version": s.terms_version, "terms_url": s.terms_url,
            "website_url": s.website_url, "privacy_url": f"{s.website_url.rstrip('/')}/privacy"}


class TrialIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    vat_number: str | None = Field(None, max_length=20)
    sector: str | None = Field(None, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(None, max_length=40)
    privacy: bool
    terms: bool  # accettazione dei termini di utilizzo
    terms_version: str = Field(max_length=20)  # versione mostrata dal modulo: deve coincidere con TERMS_VERSION
    website: str | None = None  # campo trappola: invisibile alle persone, i robot lo compilano
    elapsed_ms: int | None = None  # tempo passato sulla pagina prima dell'invio


@router.post("/prova", status_code=201)
def trial_signup(body: TrialIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    ok = {"ok": True, "email": body.email.lower(),
          "message": f"Ti abbiamo mandato a {body.email.lower()} il nome utente e la password provvisoria."}
    if body.website or (body.elapsed_ms is not None and body.elapsed_ms < MIN_SECONDS * 1000):
        log.info("Iscrizione alla prova scartata (robot) da %s", passwords.client_ip(request))
        return ok  # al robot sembra andata bene
    plan = _plan(db)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Le iscrizioni alla prova gratuita sono chiuse")
    if not body.privacy:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Per continuare accetta l'informativa sulla privacy")
    if not body.terms:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Per continuare accetta i termini di utilizzo")
    if body.terms_version.strip() != s.terms_version:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "I termini di utilizzo sono stati aggiornati: ricarica la pagina, rileggili e accettali di nuovo")
    ip = passwords.client_ip(request)
    passwords.rate_limit(f"trial:{ip}", 10, 3600)
    passwords.rate_limit(f"trial:{body.email.lower()}", 10, 86400)
    passwords.rate_limit("trial:giorno", 50, 86400)
    vat = (body.vat_number or "").replace(" ", "").upper().removeprefix("IT") or None
    if vat and not valid_vat_it(vat):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Partita IVA non valida")
    from sqlalchemy import text
    if db.execute(text("SELECT 1 FROM auth_find_user(:e)"), {"e": body.email}).first():
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "email_registrata",
                            "message": "Questa email ha già un accesso a BluBeauty: usa «Password dimenticata?» per recuperarlo."})
    if vat and db.scalar(select(func.count()).select_from(Tenant).where(Tenant.vat_number == vat)):
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "azienda_registrata",
                            "message": "Questa azienda è già registrata: contatta l'assistenza per riattivare l'accesso."})

    from app.saas.router import TenantCreate, new_tenant
    start = today()
    end = start + timedelta(days=max(1, s.trial_days) - 1)
    data = TenantCreate(name=body.company_name.strip(), vat_number=vat, sector=(body.sector or None), contact_name=body.name.strip(),
                        contact_email=body.email, phone=body.phone, plan_code=plan.code, start_date=start, end_date=end,
                        is_trial=True, admin_name=body.name.strip(), admin_email=body.email, send_activation=True, admin_password="",
                        notes=f"Iscritto dal sito il {date.today().strftime('%d/%m/%Y')} (IP {ip}), termini v{s.terms_version}")
    extra = [m.strip() for m in s.trial_extra_modules.split(",") if m.strip()]
    tenant, info = new_tenant(db, data, None, extra_modules=extra, terms={"version": s.terms_version, "ip": ip})
    if s.admin_notify_email:
        try:
            send_email([s.admin_notify_email], f"Nuova prova gratuita: {tenant.name}",
                       f"<p>Nuova iscrizione alla prova di BluBeauty dal sito.</p><p><b>{_e(tenant.name)}</b><br>{_e(body.name)} · {_e(body.email)}"
                       f"{' · ' + _e(body.phone) if body.phone else ''}<br>Pacchetto {plan.name} fino al {end.strftime('%d/%m/%Y')}"
                       f"<br>Termini di utilizzo accettati: versione {_e(s.terms_version)} (IP {_e(ip)})"
                       f"{'' if info['email_sent'] else '<br><b>Attenzione: email con le credenziali non partita</b>'}</p>")
        except Exception:  # noqa: BLE001
            log.exception("Avviso nuova prova non inviato")
    if not info["email_sent"]:  # l'azienda resta creata: le credenziali le rimanda l'amministratore dal pannello
        return {**ok, "email_sent": False,
                "message": "Abbiamo creato la tua prova, ma l'email con le credenziali non è partita: ti contattiamo noi a breve."}
    return {**ok, "email_sent": True}


def _e(v) -> str:
    import html
    return html.escape(str(v or ""))


# ====================================================================== acquisto dal sito (solo annuale)
# Contratto comune: comune/acquisto-dal-sito.md. Crea l'azienda (come la prova, con le credenziali per email), salva i dati di
# fatturazione, apre il pagamento annuale e manda subito l'email con contratto, termini, privacy e link a manuale e video.
# Carta: Stripe Checkout, poi fattura subito (webhook). Bonifico: istruzioni; la fattura parte alla conferma del super admin.


@router.get("/acquisto")
def purchase_info(db: Session = Depends(get_db)):
    from app.pagamenti import service as pay
    s = get_settings()
    offers = [{"code": p["code"], "name": p["name"], "prezzi": {"annuale": p["prezzi"]["annuale"]}}
              for p in pay.plans_offer(db) if "annuale" in p["prezzi"]]
    methods = [m for m in pay.active_methods(db) if m in ("carta", "bonifico")]
    return {"enabled": bool(offers and methods), "product": s.brand_name, "piani": offers, "metodi": methods, "periodicita": "annuale",
            "terms_version": s.terms_version, "terms_url": s.terms_url, "privacy_url": f"{s.website_url.rstrip('/')}/privacy"}


class PurchaseIn(BaseModel):
    plan_code: str = Field(max_length=40)
    method: str = Field(pattern="^(carta|bonifico)$")
    name: str = Field(min_length=2, max_length=120)  # referente, diventa l'amministratore
    email: EmailStr
    phone: str | None = Field(None, max_length=40)
    billing: dict  # stessi campi dei dati di fatturazione (tipo, denominazione, partita_iva, indirizzo, cap, comune, ...)
    privacy: bool
    terms: bool
    terms_version: str = Field(max_length=20)
    return_url: str | None = Field(None, max_length=300)  # pagina del sito a cui tornare dopo la carta
    website: str | None = None
    elapsed_ms: int | None = None


@router.post("/acquisto", status_code=201)
def purchase(body: PurchaseIn, request: Request, db: Session = Depends(get_db)):
    from app.pagamenti import billing as bl
    from app.pagamenti import service as pay
    from app.saas import contratto
    s = get_settings()
    if body.website or (body.elapsed_ms is not None and body.elapsed_ms < MIN_SECONDS * 1000):
        return {"ok": True, "robot": True}
    if not (body.privacy and body.terms):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Per continuare accetta informativa privacy, termini e contratto")
    if body.terms_version.strip() != s.terms_version:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "I termini di utilizzo sono stati aggiornati: ricarica la pagina, rileggili e accettali di nuovo")
    ip = passwords.client_ip(request)
    passwords.rate_limit(f"buy:{ip}", 10, 3600)
    passwords.rate_limit(f"buy:{body.email.lower()}", 10, 86400)
    passwords.rate_limit("buy:giorno", 50, 86400)
    data = bl.normalize(body.billing)
    errs = bl.problems(data)
    if errs:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "dati_fatturazione", "message": "; ".join(errs)})
    plan = db.scalar(select(Plan).where(Plan.code == body.plan_code))
    if plan is None or body.method not in pay.active_methods(db) or not plan.price_year or plan.price_year <= 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pacchetto o metodo di pagamento non disponibile")
    from sqlalchemy import text
    if db.execute(text("SELECT 1 FROM auth_find_user(:e)"), {"e": body.email}).first():
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "email_registrata", "message":
                            f"Questa email ha già un accesso a {s.brand_name}: accedi e usa «Rinnova abbonamento»."})
    vat = (data.get("partita_iva") or "").strip() or None
    if vat and db.scalar(select(func.count()).select_from(Tenant).where(Tenant.vat_number == vat)):
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "azienda_registrata", "message":
                            "Questa azienda è già registrata: accedi e usa «Rinnova abbonamento», o contatta l'assistenza."})

    from app.saas.router import TenantCreate, new_tenant
    start = today()
    end = start + timedelta(days=max(1, s.trial_days) - 1)
    name = bl.display_name(data) or body.name
    tc = TenantCreate(name=name[:200], vat_number=vat, tax_code=data.get("codice_fiscale"), contact_name=body.name.strip(),
                      contact_email=body.email, phone=body.phone, plan_code=plan.code, start_date=start, end_date=end, is_trial=True,
                      admin_name=body.name.strip(), admin_email=body.email, send_activation=True, admin_password="",
                      notes=f"Acquisto dal sito il {date.today().strftime('%d/%m/%Y')} (IP {ip}), termini v{s.terms_version}")
    tenant, info = new_tenant(db, tc, None, terms={"version": s.terms_version, "ip": ip})
    pay.save_billing(db, tenant, data)
    set_tenant(db, tenant.id)
    return_urls = None
    if body.return_url and body.return_url.startswith(s.website_url.rstrip("/")):
        sep = "&" if "?" in body.return_url else "?"
        return_urls = (f"{body.return_url}{sep}stato=ok", f"{body.return_url}{sep}stato=annullato")
    try:
        res = pay.checkout(db, tenant, plan_code=plan.code, period="annuale", method=body.method, return_urls=return_urls)
    except pay.PaymentError as exc:
        db.commit()  # l'azienda resta (come una prova): l'errore si mostra e si può riprovare dall'area clienti
        raise HTTPException(exc.status, {"code": exc.code, "message": str(exc)}) from None
    p = pay.load(db, res["pagamento"])
    db.commit()
    _send_order_email(db, tenant, p, data, body.method)
    if s.admin_notify_email:
        try:
            send_email([s.admin_notify_email], f"Nuovo ordine dal sito: {tenant.name}",
                       f"<p>Ordine {_e(s.brand_name)} dal sito.</p><p><b>{_e(tenant.name)}</b> · {_e(body.name)} · {_e(body.email)}<br>"
                       f"{_e(plan.name)} annuale, {_e('carta' if body.method == 'carta' else 'bonifico')}, totale {_e(p.total)} €<br>"
                       f"Causale {_e(p.causale)}"
                       + ("<br><b>Bonifico: conferma il pagamento dal pannello quando arriva l'accredito: la fattura parte solo allora.</b>" if body.method == "bonifico" else "") + "</p>")
        except Exception:  # noqa: BLE001
            log.exception("Avviso nuovo ordine non inviato")
    return {"ok": True, "pagamento": res["pagamento"], "redirect_url": res.get("redirect_url"), "bonifico": res.get("bonifico"),
            "email": body.email.lower(), "credenziali_inviate": bool(info["email_sent"])}


def _send_order_email(db, tenant, p, billing: dict, method: str) -> None:
    """Conferma d'ordine con contratto (PDF compilato), termini, privacy e link a manuale e video. Non blocca mai l'acquisto."""
    from app.auth import accounts
    from app.pagamenti import service as pay
    from app.saas import contratto
    s = get_settings()
    try:
        atts = [(f"Contratto_{s.brand_name.replace(' ', '')}_{p.causale.split()[-1]}.pdf",
                 contratto.contract_pdf(product=s.brand_name, plan_name=p.plan_name, amount=p.amount, stamp=p.stamp, total=p.total,
                                        billing=billing, causale=p.causale, method=method, terms_version=s.terms_version),
                 "application/pdf")]
        t = accounts.terms_pdf()
        if t:
            atts.append((f"termini-di-utilizzo-v{s.terms_version}.pdf", t, "application/pdf"))
        pv = accounts.fetch_pdf(s.privacy_pdf_url)
        if pv:
            atts.append(("informativa-privacy.pdf", pv, "application/pdf"))
        bank = ""
        if method == "bonifico":
            b = pay.bank_details(db, p)
            bank = (f"<p><b>Per attivare l'abbonamento fai il bonifico</b> di <b>{_e(p.total)} €</b> a <b>{_e(b['intestatario'])}</b><br>"
                    f"IBAN <b>{_e(b['iban'])}</b><br>Causale: <b>{_e(b['causale'])}</b></p>"
                    "<p>Quando il bonifico risulta accreditato confermiamo il pagamento e ti mandiamo la fattura elettronica e la ricevuta. "
                    "Nel frattempo puoi già usare il programma con il periodo di prova.</p>")
        else:
            bank = ("<p>Appena il pagamento con carta è confermato ricevi la ricevuta con la proforma della fattura elettronica, "
                    "e l'abbonamento annuale parte da subito.</p>")
        html_ = (f"<div style=\"font-family:Arial,sans-serif;color:#1b2b45;max-width:580px;margin:auto;border-top:4px solid #2340a8;padding:24px\">"
                 f"<h2 style=\"color:#2340a8\">Grazie per l'ordine, {_e(billing.get('denominazione') or billing.get('nome') or tenant.name)}</h2>"
                 f"<p>Hai scelto <b>{_e(p.plan_name)}</b>, abbonamento annuale: <b>{_e(p.total)} €</b>.</p>{bank}"
                 f"<p>Ti abbiamo mandato in un'altra email le credenziali per il primo accesso.</p>"
                 f"<p><b>In allegato</b>: contratto di abbonamento, termini di utilizzo e informativa sulla privacy.</p>"
                 f"<p><b>Per cominciare</b>:<br>• <a href=\"{_e(s.manual_url)}\">Manuale d'uso</a><br>"
                 f"• <a href=\"{_e(s.videos_url)}\">Video tutorial</a><br>• Assistenza: {_e(s.support_email)}"
                 f"{' · ' + _e(s.support_phone) if s.support_phone else ''}</p>"
                 f"<p style=\"color:#4a5b75;font-size:13px\">Il team {_e(s.brand_name)} · BluCode Informatica</p></div>")
        send_email([billing.get("email") or tenant.contact_email], f"Conferma d'ordine {s.brand_name}", html_, atts)
    except Exception:  # noqa: BLE001
        log.exception("Email d'ordine non inviata a %s", tenant.contact_email)
