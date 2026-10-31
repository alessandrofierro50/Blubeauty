"""API per la BluCode Console: riepilogo in sola lettura (GET /api/console/riepilogo, §7) e cambio delle
credenziali del super amministratore (POST /api/console/super-admin/credenziali, §8).

Standard comune (progetto_blucode_informatica/comune/abbonamenti.md §7): chiave CONSOLE_API_KEY in
`Authorization: Bearer`, 404 se la chiave non è configurata, confronto a tempo costante, 60 richieste all'ora.
La chiamata parte dal server della console, non dal browser: nessuna origine CORS da aggiungere.
Importi in euro IVA esclusa, date ISO, fuso Europe/Rome.

Incassato: con il modulo pagamenti (app/pagamenti) è la somma dei canoni dei pagamenti «pagato» nel mese, alla data del
pagamento (senza il rimborso del bollo); i periodi inseriti a mano dal pannello si contano ancora alla data di inizio.
"""

import hmac
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta
import logging
import re

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.auth import passwords
from app.core.config import get_settings
from app.core.db import get_db
from app.core.mailer import send_email
from app.core.models import AuditLog, SuperAdmin, Subscription, Tenant
from app.core.security import hash_password
from app.pagamenti.models import PaymentRoute
from app.saas import logic
from app.saas.service import audit, tenant_state, today

log = logging.getLogger("blubeauty.console")

router = APIRouter(prefix="/api/console", tags=["console"])

RATE_LIMIT = (60, 3600)
CREDENTIALS_RATE_LIMIT = (5, 3600)
PAYING = ("attivo", "in_scadenza", "tolleranza")  # base del ricavo ricorrente (sempre fuori le prove)


def _same(given: str | None, key: str) -> bool:
    """Confronto a tempo costante."""
    return hmac.compare_digest((given or "").encode(), key.encode())


def _bearer(authorization: str | None) -> str:
    if authorization and authorization[:7].lower() == "bearer ":
        return authorization[7:].strip()
    return ""


def check_key(authorization: str | None = Header(None)) -> None:
    key = get_settings().console_api_key
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    passwords.rate_limit("console:riepilogo", *RATE_LIMIT)
    if not _same(_bearer(authorization), key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chiave non valida")


def check_admin_keys(authorization: str | None = Header(None),
                     x_console_admin_key: str | None = Header(None)) -> None:
    """Due chiavi: CONSOLE_API_KEY e CONSOLE_ADMIN_KEY. Comando disattivato (404) se una delle due è vuota."""
    s = get_settings()
    if not s.console_admin_key or not s.console_api_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    passwords.rate_limit("console:credenziali", *CREDENTIALS_RATE_LIMIT)
    ok_api = _same(_bearer(authorization), s.console_api_key)
    ok_admin = _same(x_console_admin_key, s.console_admin_key)
    if not (ok_api and ok_admin):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Chiave non valida")


def _money(v: Decimal) -> float:
    return float(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _plan_label(plan) -> str:
    return plan.code.title() if plan else ""


def _snapshot(tenant: Tenant, on: date, suspended: bool) -> tuple[str, Subscription | None]:
    """Stato dell'azienda a una data, ricalcolato dai periodi (la sospensione manuale si conosce solo per oggi)."""
    subs = list(tenant.subscriptions)
    sub = logic.current_subscription(subs, on)
    return logic.subscription_status(sub, on, suspended, logic.effective_end(subs, on)), sub


def _mrr_part(status_: str, sub: Subscription | None) -> Decimal | None:
    if status_ in PAYING and sub is not None and not sub.is_trial:
        return logic.monthly_amount(sub.amount, sub.period, sub.start_date, sub.end_date)
    return None


def build_summary(db: Session, on: date | None = None) -> dict:
    on = on or today()
    tz = ZoneInfo(get_settings().timezone)
    tenants = db.scalars(
        select(Tenant).options(selectinload(Tenant.subscriptions).selectinload(Subscription.plan),
                               selectinload(Tenant.extra_modules)).order_by(Tenant.name)
    ).all()

    counts = {"totale": len(tenants), "attive": 0, "prova": 0, "tolleranza": 0, "sola_lettura": 0, "sospese": 0}
    mrr = Decimal("0")
    per_plan: dict[str, dict] = {}
    in_scadenza, scadute = [], []
    cashed_month = cashed_year = Decimal("0")
    window = on - timedelta(days=30)
    mov = {"nuove_prove": 0, "prove_convertite": 0, "prove_scadute_non_convertite": 0, "rinnovi": 0,
           "nuovi_abbonamenti": 0, "disdette_o_sospensioni": 0}
    suspended_recently = {
        a.tenant_id for a in db.scalars(
            select(AuditLog).where(AuditLog.entity == "tenant", AuditLog.action == "sospensione",
                                   AuditLog.at >= datetime.combine(window, datetime.min.time(), tz)))
    }

    # Incassato (comune/pagamenti.md, Collegamenti): i pagamenti online «pagato» contano alla data del pagamento; i periodi
    # nati da un pagamento non si contano una seconda volta alla data di inizio. Gli altri periodi (rinnovi a mano dal
    # pannello) restano contati alla data di inizio, come prima del modulo pagamenti.
    paid = [(r.paid_at.astimezone(tz).date(), Decimal(r.amount), r.subscription_id) for r in db.scalars(
        select(PaymentRoute).where(PaymentRoute.status == "pagato", PaymentRoute.paid_at.is_not(None)))]
    from_payment = {sid for _, _, sid in paid if sid}
    for d, amount, _ in paid:
        if d.year == on.year and d <= on:
            cashed_year += amount
            if d.month == on.month:
                cashed_month += amount

    for t in tenants:
        st = tenant_state(t, on)
        sub = st.subscription
        if st.status in ("attivo", "in_scadenza"):
            counts["attive"] += 1
        elif st.status == "prova":
            counts["prova"] += 1
        elif st.status in ("tolleranza", "sola_lettura"):
            counts[st.status] += 1
        elif st.status in ("sospeso", "prova_scaduta"):
            counts["sospese"] += 1

        part = _mrr_part(st.status, sub)
        if part is not None:
            mrr += part
            row = per_plan.setdefault(_plan_label(st.plan), {"piano": _plan_label(st.plan), "aziende": 0, "mrr": Decimal("0")})
            row["aziende"] += 1
            row["mrr"] += part

        if not t.suspended and st.end_date and st.days_left is not None and 0 <= st.days_left <= 30 \
                and st.status in ("attivo", "in_scadenza", "prova"):
            in_scadenza.append({
                "azienda": t.name, "piano": _plan_label(st.plan), "scadenza": st.end_date.isoformat(),
                "giorni": st.days_left, "stato": "attivo" if st.status == "in_scadenza" else st.status, "importo": _money(sub.amount) if sub else 0.0,
                "periodicita": sub.period if sub else None, "prova": bool(sub and sub.is_trial),
                "email": t.contact_email, "telefono": t.phone or "",
            })
        if st.status in ("tolleranza", "sola_lettura", "sospeso", "prova_scaduta"):
            scadute.append({
                "azienda": t.name, "stato": "sospeso" if st.status == "prova_scaduta" else st.status,
                "scadenza": st.end_date.isoformat() if st.end_date else None,
                "giorni_da": max(0, (on - st.end_date).days) if st.end_date else None,
                "prova": bool(sub and sub.is_trial),
            })

        # movimenti e incassi, dai periodi
        ordered = sorted(t.subscriptions, key=lambda s: s.start_date)
        for i, s in enumerate(ordered):
            prev = ordered[i - 1] if i else None
            if not s.is_trial and s.id not in from_payment:
                if s.start_date.year == on.year and s.start_date <= on:
                    cashed_year += s.amount
                    if s.start_date.month == on.month:
                        cashed_month += s.amount
            if not (window < s.start_date <= on):
                continue
            if s.is_trial:
                mov["nuove_prove"] += 1
            elif prev is None:
                mov["nuovi_abbonamenti"] += 1
            elif prev.is_trial:
                mov["prove_convertite"] += 1
            else:
                mov["rinnovi"] += 1
        last = ordered[-1] if ordered else None
        if last and last.is_trial and window <= last.end_date < on:
            mov["prove_scadute_non_convertite"] += 1
        if t.id in suspended_recently:
            mov["disdette_o_sospensioni"] += 1
        elif last and not last.is_trial:
            suspension_day = last.end_date + timedelta(days=last.grace_days + last.readonly_days + 1)
            if window < suspension_day <= on:
                mov["disdette_o_sospensioni"] += 1

    in_scadenza.sort(key=lambda r: (r["scadenza"], r["azienda"]))
    scadute.sort(key=lambda r: (r["scadenza"] or "", r["azienda"]))

    trend = []
    first = on.replace(day=1) - relativedelta(months=11)
    for k in range(12):
        m_start = first + relativedelta(months=k)
        m_end = min(m_start + relativedelta(months=1) - timedelta(days=1), on)
        m_mrr, paying, trials, cashed = Decimal("0"), 0, 0, Decimal("0")
        for t in tenants:
            st_, sub_ = _snapshot(t, m_end, t.suspended if m_end == on else False)
            part = _mrr_part(st_, sub_)
            if part is not None:
                m_mrr += part
                paying += 1
            trials += sum(1 for s in t.subscriptions if s.is_trial and m_start <= s.start_date <= m_end)
            cashed += sum((s.amount for s in t.subscriptions
                           if not s.is_trial and s.id not in from_payment and m_start <= s.start_date <= m_end), Decimal("0"))
        cashed += sum((a for d, a, _ in paid if m_start <= d <= m_end), Decimal("0"))
        trend.append({"mese": m_start.strftime("%Y-%m"), "mensile_ricorrente": _money(m_mrr),
                      "aziende_paganti": paying, "nuove_prove": trials, "incassato": _money(cashed)})

    return {
        "prodotto": get_settings().brand_name,
        "generato_il": datetime.now(tz).replace(microsecond=0).isoformat(),
        "aziende": counts,
        "ricavi": {
            "mensile_ricorrente": _money(mrr),
            "annuale_ricorrente": _money(mrr * 12),
            "incassato_mese_corrente": _money(cashed_month),
            "incassato_anno_corrente": _money(cashed_year),
        },
        "movimenti_30_giorni": mov,
        "per_piano": [{"piano": r["piano"], "aziende": r["aziende"], "mensile_ricorrente": _money(r["mrr"])}
                      for r in sorted(per_plan.values(), key=lambda r: -r["mrr"])],
        "in_scadenza": in_scadenza,
        "scadute": scadute,
        "andamento_12_mesi": trend,
    }


@router.get("/riepilogo", dependencies=[Depends(check_key)])
def summary(db: Session = Depends(get_db)):
    return build_summary(db)


# ---------------------------------------------------------------- §8 credenziali del super amministratore


class CredentialsIn(BaseModel):
    email: EmailStr | None = None
    password: str


def _check_console_password(pw: str) -> None:
    """Almeno 12 caratteri, con maiuscole, minuscole e cifre (standard comune §8)."""
    if len(pw) < 12 or not re.search(r"[A-Z]", pw) or not re.search(r"[a-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "La password deve avere almeno 12 caratteri, con maiuscole, minuscole e cifre")


def main_super_admin(db: Session) -> SuperAdmin | None:
    """Il super amministratore principale: quello di CONSOLE_SUPERADMIN_EMAIL, altrimenti il primo creato."""
    wanted = get_settings().console_superadmin_email.strip().lower()
    if wanted:
        admin = db.scalar(select(SuperAdmin).where(func.lower(SuperAdmin.email) == wanted))
        if admin is not None:
            return admin
    return db.scalar(select(SuperAdmin).order_by(SuperAdmin.created_at, SuperAdmin.email).limit(1))


@router.post("/super-admin/credenziali", dependencies=[Depends(check_admin_keys)])
def change_super_admin_credentials(body: CredentialsIn, request: Request, db: Session = Depends(get_db)):
    """Cambia email di accesso e password del super amministratore principale. Invalida tutte le sue sessioni
    (token_version), non attiva il cambio forzato e lascia com'è la verifica in due passaggi."""
    _check_console_password(body.password)
    admin = main_super_admin(db)
    if admin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nessun super amministratore")
    old_email = admin.email
    new_email = body.email.strip().lower() if body.email else None
    if new_email and new_email != admin.email.lower():
        taken = db.scalar(select(SuperAdmin).where(func.lower(SuperAdmin.email) == new_email, SuperAdmin.id != admin.id))
        if taken is None:
            # anche gli utenti delle aziende: la funzione SECURITY DEFINER li vede tutti, senza RLS
            from sqlalchemy import text
            taken = db.execute(text("SELECT id FROM auth_find_user(:e)"), {"e": new_email}).first()
        if taken is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email già usata da un altro utente")
        admin.email = new_email
    now = datetime.now(ZoneInfo(get_settings().timezone)).replace(microsecond=0)
    admin.password_hash = hash_password(body.password)
    admin.token_version = (admin.token_version or 0) + 1
    admin.reset_token_hash = admin.reset_expires_at = None  # un link di recupero già mandato non vale più
    admin.credentials_changed_at = now
    ip = passwords.client_ip(request)
    audit(db, "super_admin", "credenziali da console", admin.id, admin_id=None,
          before={"email": old_email},
          after={"email": admin.email, "chi": "console", "ip": ip, "data": now.isoformat(),
                 "email_cambiata": admin.email != old_email})
    db.flush()
    s = get_settings()
    if s.admin_notify_email:
        try:
            send_email([s.admin_notify_email], f"{s.brand_name}: credenziali del super amministratore cambiate",
                       f"<p>Le credenziali del super amministratore di {s.brand_name} sono state cambiate dalla "
                       f"BluCode Console il {now.strftime('%d/%m/%Y alle %H:%M')} (IP {ip}).</p>"
                       f"<p>Email di accesso: <b>{admin.email}</b>"
                       + (f" (prima: {old_email})" if admin.email != old_email else "")
                       + ".</p><p>Tutte le sessioni aperte sono state chiuse. La password non è riportata.</p>")
        except Exception:  # noqa: BLE001  l'avviso non deve annullare il cambio
            log.exception("Avviso del cambio credenziali non inviato")
    return {"ok": True, "email": admin.email, "cambiato_il": now.isoformat()}
