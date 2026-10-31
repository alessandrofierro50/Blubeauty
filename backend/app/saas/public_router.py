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
from app.core.db import get_db
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
    passwords.rate_limit(f"trial:{ip}", 3, 3600)
    passwords.rate_limit(f"trial:{body.email.lower()}", 2, 86400)
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
