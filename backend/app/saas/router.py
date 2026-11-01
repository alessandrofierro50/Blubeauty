"""API del pannello super amministratore: /api/admin/..."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi.responses import FileResponse
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.anagrafiche.bootstrap import bootstrap_tenant
from app.auth import accounts, passwords
from app.core.config import get_settings
from app.core.db import get_db, set_tenant
from app.core.deps import get_admin
from app.core.mailer import send_email
from app.saas import eliminazione
from app.core.models import (
    AuditLog,
    Company,
    EmailLog,
    EmailTemplate,
    Plan,
    ReminderRule,
    SaasSetting,
    Subscription,
    SuperAdmin,
    Tenant,
    TenantModule,
    User,
    Warehouse,
)
from app.core.security import (
    create_token,
    hash_password,
    new_totp_secret,
    random_token,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.saas import logic
from app.saas.reminders import run_reminders
from app.saas.service import audit, lifecycle_settings, load_tenant, tenant_state, today

router = APIRouter(prefix="/api/admin", tags=["super-admin"])


# ---------------------------------------------------------------- autenticazione


class AdminLogin(BaseModel):
    email: str
    password: str
    totp: str | None = None


@router.post("/auth/login")
def admin_login(body: AdminLogin, request: Request, db: Session = Depends(get_db)):
    passwords.rate_limit(f"admin-login:{passwords.client_ip(request)}", 10, 900)
    admin = db.scalar(select(SuperAdmin).where(func.lower(SuperAdmin.email) == body.email.lower()))
    if admin is None or not verify_password(body.password, admin.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o password errate")
    if admin.totp_enabled:
        if not body.totp:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, {"code": "totp_richiesto", "message": "Inserisci il codice di verifica"})
        if not verify_totp(admin.totp_secret, body.totp):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Codice di verifica errato")
    token = create_token(admin.id, "admin", get_settings().admin_token_minutes, version=admin.token_version or 0)
    return {"token": token, "email": admin.email, "totp_enabled": admin.totp_enabled}


@router.get("/auth/me")
def admin_me(admin: SuperAdmin = Depends(get_admin)):
    return {"email": admin.email, "totp_enabled": admin.totp_enabled}


@router.post("/auth/totp/setup")
def totp_setup(admin: SuperAdmin = Depends(get_admin)):
    admin.totp_secret = new_totp_secret()
    admin.totp_enabled = False
    return {"secret": admin.totp_secret, "uri": totp_uri(admin.totp_secret, admin.email)}


class TotpConfirm(BaseModel):
    code: str


@router.post("/auth/totp/confirm")
def totp_confirm(body: TotpConfirm, admin: SuperAdmin = Depends(get_admin)):
    if not admin.totp_secret or not verify_totp(admin.totp_secret, body.code):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Codice non valido")
    admin.totp_enabled = True
    return {"totp_enabled": True}


class AdminPasswordIn(BaseModel):
    current: str
    new: str


@router.post("/auth/password")
def admin_change_password(body: AdminPasswordIn, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    if not verify_password(body.current, admin.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password attuale errata")
    if body.current == body.new:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La nuova password deve essere diversa da quella attuale")
    accounts.check_admin_strength(body.new)
    admin.password_hash = hash_password(body.new)
    audit(db, "super_admin", "cambio password", admin.id, admin_id=admin.id)
    return {"ok": True}


class AdminForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)


@router.post("/auth/password-dimenticata")
def admin_forgot(body: AdminForgotIn, request: Request, db: Session = Depends(get_db)):
    passwords.rate_limit(f"admin-forgot:{passwords.client_ip(request)}", 3, 900)
    accounts.request_admin_reset(db, body.email)
    return {"ok": True, "message": "Se l'indirizzo è quello dell'amministratore, riceverai un'email con il link."}


class AdminResetIn(BaseModel):
    token: str = Field(min_length=10)
    password: str


@router.post("/auth/reimposta-password")
def admin_reset(body: AdminResetIn, request: Request, db: Session = Depends(get_db)):
    passwords.rate_limit(f"admin-reset:{passwords.client_ip(request)}", 10, 900)
    accounts.reset_admin(db, body.token, body.password)
    return {"ok": True}


@router.get("/password-provvisoria")
def suggest_password(admin: SuperAdmin = Depends(get_admin)):
    return {"password": passwords.temporary_password()}


# ---------------------------------------------------------------- serializzazione


def _sub_out(s: Subscription) -> dict:
    return {
        "id": str(s.id),
        "plan_code": s.plan.code,
        "plan_name": s.plan.name,
        "start_date": s.start_date.isoformat(),
        "end_date": s.end_date.isoformat(),
        "amount": str(s.amount),
        "period": s.period,
        "is_trial": s.is_trial,
        "grace_days": s.grace_days,
        "readonly_days": s.readonly_days,
        "notes": s.notes,
    }


def _tenant_out(t: Tenant, detail: bool = False) -> dict:
    st = tenant_state(t)
    out = {
        "id": str(t.id),
        "name": t.name,
        "vat_number": t.vat_number,
        "sector": t.sector,
        "contact_email": t.contact_email,
        "suspended": t.suspended,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        **st.to_dict(),
    }
    if detail:
        out.update(
            {
                "tax_code": t.tax_code,
                "contact_name": t.contact_name,
                "phone": t.phone,
                "billing_data": t.billing_data,
                "notes": t.notes,
                "extra_modules": [m.module for m in t.extra_modules],
                "terms": {"version": t.terms_version, "accepted_at": t.terms_accepted_at.isoformat(), "ip": t.terms_accepted_ip}
                if t.terms_accepted_at else None,
                "custom_limits": {
                    "max_users": t.max_users,
                    "max_companies": t.max_companies,
                    "max_warehouses": t.max_warehouses,
                    "max_pos": t.max_pos,
                },
                "subscriptions": [_sub_out(s) for s in sorted(t.subscriptions, key=lambda s: s.start_date, reverse=True)],
            }
        )
    return out


def _get_tenant(db: Session, tenant_id: uuid.UUID) -> Tenant:
    t = load_tenant(db, tenant_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Azienda non trovata")
    return t


def _plan(db: Session, code: str) -> Plan:
    p = db.scalar(select(Plan).where(Plan.code == code))
    if p is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Pacchetto {code} inesistente")
    return p


# ---------------------------------------------------------------- dashboard


@router.get("/dashboard")
def dashboard(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    tenants = db.scalars(
        select(Tenant).options(
            selectinload(Tenant.subscriptions).selectinload(Subscription.plan),
            selectinload(Tenant.extra_modules),
        )
    ).all()
    counts = {k: 0 for k in logic.STATUS_LABELS}
    by_plan: dict[str, int] = {}
    mrr = Decimal("0")
    expiring = []
    for t in tenants:
        st = tenant_state(t)
        counts[st.status] += 1
        if st.plan and st.access != "none":
            by_plan[st.plan.code] = by_plan.get(st.plan.code, 0) + 1
        s = st.subscription
        if s and st.access == "full" and not s.is_trial:
            mrr += logic.monthly_amount(s.amount, s.period, s.start_date, s.end_date)
        if st.status in ("in_scadenza", "tolleranza", "sola_lettura"):
            expiring.append({"id": str(t.id), "name": t.name, "status": st.status,
                             "status_label": logic.STATUS_LABELS[st.status],
                             "end_date": st.end_date.isoformat() if st.end_date else None,
                             "days_left": st.days_left})
    expiring.sort(key=lambda e: e["days_left"] if e["days_left"] is not None else 0)
    return {
        "tenants_total": len(tenants),
        "status_counts": counts,
        "by_plan": by_plan,
        "mrr": str(mrr.quantize(Decimal("0.01"))),
        "attention": expiring,
    }


# ---------------------------------------------------------------- aziende clienti


@router.get("/tenants")
def list_tenants(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    tenants = db.scalars(
        select(Tenant)
        .options(selectinload(Tenant.subscriptions).selectinload(Subscription.plan), selectinload(Tenant.extra_modules))
        .order_by(Tenant.name)
    ).all()
    return [_tenant_out(t) for t in tenants]


EXPORT_COLUMNS = ["Azienda", "Partita IVA", "Referente", "Email", "Telefono", "Pacchetto", "Stato", "Fine periodo",
                  "Giorni", "Importo", "Periodicità", "Prova"]


def _export_rows(db: Session) -> list[list]:
    tenants = db.scalars(
        select(Tenant)
        .options(selectinload(Tenant.subscriptions).selectinload(Subscription.plan), selectinload(Tenant.extra_modules))
        .order_by(Tenant.name)
    ).all()
    rows = []
    for t in tenants:
        st = tenant_state(t)
        s = st.subscription
        rows.append([t.name, t.vat_number or "", t.contact_name or "", t.contact_email, t.phone or "",
                     st.plan.name if st.plan else "", logic.STATUS_LABELS[st.status], st.end_date,
                     st.days_left if st.days_left is not None else "", s.amount if s else Decimal("0"),
                     s.period if s else "", "sì" if s and s.is_trial else "no"])
    return rows


@router.get("/tenants/export")
def export_tenants(format: str = "xlsx", admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    """Elenco delle aziende con pacchetto, stato, scadenza, importo e contatti, in Excel o CSV (separatore ;)."""
    import csv
    import io

    from fastapi.responses import Response

    rows = _export_rows(db)
    stamp = today().isoformat()
    if format == "csv":
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(EXPORT_COLUMNS)
        for r in rows:
            w.writerow([x.strftime("%d/%m/%Y") if isinstance(x, date) else (f"{x:.2f}".replace(".", ",") if isinstance(x, Decimal) else x)
                        for x in r])
        return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="aziende-{stamp}.csv"'})
    if format != "xlsx":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Formato non valido: csv oppure xlsx")
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Aziende"
    ws.append(EXPORT_COLUMNS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append([float(x) if isinstance(x, Decimal) else x for x in r])
        ws.cell(ws.max_row, 8).number_format = "DD/MM/YYYY"
        ws.cell(ws.max_row, 10).number_format = "#,##0.00 €"
    for col, width in zip("ABCDEFGHIJKL", (34, 14, 22, 30, 16, 16, 20, 13, 8, 12, 14, 8)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    out = io.BytesIO()
    wb.save(out)
    return Response(out.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="aziende-{stamp}.xlsx"'})


class TenantCreate(BaseModel):
    name: str = Field(min_length=2)
    vat_number: str | None = None
    tax_code: str | None = None
    sector: str | None = None
    contact_name: str | None = None
    contact_email: EmailStr
    phone: str | None = None
    notes: str | None = None
    # primo abbonamento
    plan_code: str = "SALONE"
    start_date: date | None = None
    end_date: date | None = None
    period: str = "annuale"
    amount: Decimal | None = None
    is_trial: bool = False
    # primo utente amministratore dell'azienda
    admin_name: str
    admin_email: EmailStr
    send_activation: bool = True  # manda l'email (credenziali con la password provvisoria, o link per sceglierla)
    # password provvisoria dell'utente amministratore: se indicata, l'email contiene nome utente e password
    # (da cambiare al primo accesso); se vuota, l'email contiene il link per scegliere la password
    admin_password: str | None = None


def new_tenant(db: Session, body: TenantCreate, admin_id=None, extra_modules: list[str] | None = None,
               terms: dict | None = None):
    """Azienda con abbonamento (o prova), dati iniziali e primo utente; manda le credenziali o il link di attivazione.
    `terms` = {"version", "ip"}: termini accettati nell'iscrizione dal sito (registrati e citati nell'email)."""
    plan = _plan(db, body.plan_code)
    start = body.start_date or today()
    trial_days = max(1, get_settings().trial_days)  # prova: 7 giorni come sul sito (standard comune)
    end = body.end_date or (start + timedelta(days=trial_days - 1) if body.is_trial else logic.next_period(start, body.period))
    if end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La data di fine è precedente all'inizio")
    amount = body.amount if body.amount is not None else (
        Decimal("0") if body.is_trial else plan.price_month if body.period == "mensile" else plan.price_year
    )

    tenant = Tenant(
        name=body.name, vat_number=body.vat_number, tax_code=body.tax_code, sector=body.sector,
        contact_name=body.contact_name, contact_email=body.contact_email.lower(), phone=body.phone,
        notes=body.notes, billing_data={},
    )
    if terms:
        tenant.terms_version = terms["version"]
        tenant.terms_accepted_at = datetime.now(timezone.utc)
        tenant.terms_accepted_ip = terms.get("ip")
    db.add(tenant)
    db.flush()
    life = lifecycle_settings(db)
    db.add(Subscription(tenant_id=tenant.id, plan_id=plan.id, start_date=start, end_date=end,
                        amount=amount, period="personalizzata" if body.is_trial else body.period,
                        is_trial=body.is_trial, grace_days=life["grace_days"], readonly_days=life["readonly_days"]))
    for m in extra_modules or []:
        if m in logic.EXTRA_MODULES:
            db.add(TenantModule(tenant_id=tenant.id, module=m))

    # Dati iniziali dell'azienda (tabelle protette da RLS: impostiamo il tenant)
    set_tenant(db, tenant.id)
    company = Company(tenant_id=tenant.id, name=body.name, vat_number=body.vat_number,
                      tax_code=body.tax_code, email=body.contact_email.lower())
    db.add(company)
    db.flush()
    db.add(Warehouse(tenant_id=tenant.id, company_id=company.id, code="MAG01", name="Magazzino principale"))
    bootstrap_tenant(db, tenant.id, body.sector)
    token = random_token()
    user = User(tenant_id=tenant.id, email=body.admin_email.lower(), full_name=body.admin_name,
                role="amministratore", activation_token=token)
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esiste già un utente con questa email") from None
    temp_password = None
    if body.admin_password is not None:
        temp_password = accounts.set_temporary_password(db, user, body.admin_password)

    audit(db, "tenant", "creazione", tenant.id, tenant_id=tenant.id, admin_id=admin_id,
          after={"name": tenant.name, "plan": plan.code, "dal": str(start), "al": str(end)})

    activation_link = f"{get_settings().public_url}/attiva?token={token}" if temp_password is None else None
    email_sent = False
    if body.send_activation:
        if temp_password is not None:
            period = (f"Il periodo di prova del pacchetto {plan.name} dura fino al {end.strftime('%d/%m/%Y')}." if body.is_trial
                      else f"Abbonamento {plan.name} attivo fino al {end.strftime('%d/%m/%Y')}.")
            email_sent = accounts.send_credentials(db, user, body.name, temp_password, period,
                                                   terms_version=terms["version"] if terms else None)
        else:
            email_sent = accounts.send_template(db, "attivazione_utente", user.email, {
                "nome": body.admin_name, "ragione_sociale": body.name, "link_attivazione": activation_link})
    db.expire(tenant)
    return tenant, {"activation_link": activation_link, "temp_password": temp_password, "email_sent": email_sent,
                    "username": user.email}


@router.post("/tenants", status_code=201)
def create_tenant(body: TenantCreate, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    tenant, extra = new_tenant(db, body, admin.id)
    return {**_tenant_out(_get_tenant(db, tenant.id), detail=True), **extra}


@router.get("/tenants/{tenant_id}")
def get_tenant(tenant_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    t = _get_tenant(db, tenant_id)
    out = _tenant_out(t, detail=True)
    set_tenant(db, tenant_id)
    out["users"] = [
        {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role, "active": u.active,
         "pending_activation": u.password_hash is None, "must_change_password": u.must_change_password}
        for u in db.scalars(select(User).order_by(User.full_name))
    ]
    out["usage"] = {
        "users": len(out["users"]),
        "companies": db.scalar(select(func.count()).select_from(Company)),
        "warehouses": db.scalar(select(func.count()).select_from(Warehouse)),
    }
    return out


class TenantUpdate(BaseModel):
    name: str | None = None
    vat_number: str | None = None
    tax_code: str | None = None
    sector: str | None = None
    contact_name: str | None = None
    contact_email: EmailStr | None = None
    phone: str | None = None
    notes: str | None = None
    billing_data: dict | None = None
    max_users: int | None = None
    max_companies: int | None = None
    max_warehouses: int | None = None
    max_pos: int | None = None
    extra_modules: list[str] | None = None


@router.patch("/tenants/{tenant_id}")
def update_tenant(tenant_id: uuid.UUID, body: TenantUpdate, admin: SuperAdmin = Depends(get_admin),
                  db: Session = Depends(get_db)):
    t = _get_tenant(db, tenant_id)
    data = body.model_dump(exclude_unset=True)
    extra = data.pop("extra_modules", None)
    before = {k: getattr(t, k) for k in data}
    for k, v in data.items():
        setattr(t, k, v.lower() if k == "contact_email" and v else v)
    if extra is not None:
        unknown = set(extra) - set(logic.EXTRA_MODULES)
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Moduli sconosciuti: {', '.join(unknown)}")
        before["extra_modules"] = [m.module for m in t.extra_modules]
        t.extra_modules = [TenantModule(tenant_id=t.id, module=m) for m in extra]
        data["extra_modules"] = extra
    audit(db, "tenant", "modifica", t.id, tenant_id=t.id, admin_id=admin.id,
          before={k: str(v) if v is not None else None for k, v in before.items()},
          after={k: str(v) if v is not None else None for k, v in data.items()})
    db.flush()
    db.expire(t)
    return _tenant_out(_get_tenant(db, tenant_id), detail=True)


@router.post("/tenants/{tenant_id}/suspend")
def suspend_tenant(tenant_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    t = _get_tenant(db, tenant_id)
    t.suspended = True
    audit(db, "tenant", "sospensione", t.id, tenant_id=t.id, admin_id=admin.id)
    return _tenant_out(t)


class DeleteIn(BaseModel):
    file: str
    sha256: str
    name: str
    confirm: str


@router.post("/tenants/{tenant_id}/archivio")
def create_tenant_archive(tenant_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    """Archivio completo (ZIP) dell'azienda sospesa: resta sul server e va scaricato sul computer."""
    return eliminazione.create_archive(db, _get_tenant(db, tenant_id), admin.id)


@router.get("/tenants/{tenant_id}/archivio/{file}")
def download_tenant_archive(tenant_id: uuid.UUID, file: str, admin: SuperAdmin = Depends(get_admin)):
    path = eliminazione.archive_path(tenant_id, file)
    return FileResponse(path, media_type="application/zip", filename=file)


@router.post("/tenants/{tenant_id}/elimina")
def delete_tenant(tenant_id: uuid.UUID, body: DeleteIn, admin: SuperAdmin = Depends(get_admin),
                  db: Session = Depends(get_db)):
    """Eliminazione definitiva: azienda sospesa, archivio scaricato (stessa impronta SHA-256), nome e parola ELIMINA."""
    return eliminazione.delete_tenant(db, _get_tenant(db, tenant_id), admin.id, name=body.name, confirm=body.confirm,
                                      sha256=body.sha256, file=body.file)


@router.post("/tenants/{tenant_id}/reactivate")
def reactivate_tenant(tenant_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    t = _get_tenant(db, tenant_id)
    t.suspended = False
    audit(db, "tenant", "riattivazione", t.id, tenant_id=t.id, admin_id=admin.id)
    return _tenant_out(t)


@router.post("/tenants/{tenant_id}/impersonate/{user_id}")
def impersonate(tenant_id: uuid.UUID, user_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin),
                db: Session = Depends(get_db)):
    """Accesso come utente del cliente, per assistenza. Sempre registrato nel log."""
    set_tenant(db, tenant_id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utente non trovato")
    audit(db, "user", "impersonificazione", user.id, tenant_id=tenant_id, user_id=user.id, admin_id=admin.id)
    token = create_token(user.id, "user", 60, tenant_id=tenant_id, impersonated_by=admin.id,
                         version=admin.token_version or 0)
    return {"token": token, "user": {"email": user.email, "full_name": user.full_name}}


@router.post("/tenants/{tenant_id}/users/{user_id}/activation-link")
def activation_link(tenant_id: uuid.UUID, user_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin),
                    db: Session = Depends(get_db)):
    set_tenant(db, tenant_id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utente non trovato")
    user.activation_token = random_token()
    return {"activation_link": f"{get_settings().public_url}/attiva?token={user.activation_token}"}


class UserPasswordIn(BaseModel):
    password: str | None = None  # vuota: la genera BluBeauty
    send_email: bool = True


@router.post("/tenants/{tenant_id}/users/{user_id}/password")
def set_user_password(tenant_id: uuid.UUID, user_id: uuid.UUID, body: UserPasswordIn, admin: SuperAdmin = Depends(get_admin),
                      db: Session = Depends(get_db)):
    """Nuova password provvisoria per un utente dell'azienda (da cambiare al primo accesso); la si vede solo qui."""
    t = _get_tenant(db, tenant_id)
    set_tenant(db, tenant_id)
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utente non trovato")
    password = accounts.set_temporary_password(db, user, body.password)
    audit(db, "user", "password provvisoria", user.id, tenant_id=tenant_id, user_id=user.id, admin_id=admin.id)
    sent = accounts.send_credentials(db, user, t.name, password) if body.send_email else False
    return {"username": user.email, "password": password, "email_sent": sent}


# ---------------------------------------------------------------- abbonamenti


class SubscriptionCreate(BaseModel):
    plan_code: str
    start_date: date
    end_date: date
    amount: Decimal | None = None
    period: str = "annuale"
    is_trial: bool = False
    grace_days: int | None = None  # vuoto = valore predefinito del pannello
    readonly_days: int | None = None
    notes: str | None = None


def _insert_period(db: Session, t: Tenant, admin_id, plan: Plan, start: date, end: date, *, action: str = "nuovo_periodo",
                   keep: Subscription | None = None, **fields) -> Subscription:
    """Inserisce un periodo. Un periodo in corso che lo contiene viene chiuso il giorno prima (cambio pacchetto,
    conversione della prova); uno che inizia lo stesso giorno viene sostituito (correzione), restando nel log."""
    if end < start:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La data di fine è precedente all'inizio")
    for s in list(t.subscriptions):
        if s is keep:  # già sistemato da chi chiama (es. la prova convertita resta nello storico)
            continue
        if s.start_date < start <= s.end_date:
            s.end_date = start - timedelta(days=1)
        elif s.start_date == start:
            audit(db, "subscription", "sostituzione", s.id, tenant_id=t.id, admin_id=admin_id, before=_sub_out(s))
            t.subscriptions.remove(s)
            db.delete(s)
        elif s.start_date > start and s.end_date <= end:
            raise HTTPException(status.HTTP_409_CONFLICT, "Esiste già un periodo compreso in queste date")
    sub = Subscription(tenant_id=t.id, plan_id=plan.id, start_date=start, end_date=end, **fields)
    db.add(sub)
    audit(db, "subscription", action, tenant_id=t.id, admin_id=admin_id,
          after={"plan": plan.code, "dal": str(start), "al": str(end), "importo": str(fields.get("amount"))})
    db.flush()
    return sub


def _list_price(plan: Plan, period: str) -> Decimal:
    return plan.price_month if period == "mensile" else plan.price_year


@router.post("/tenants/{tenant_id}/subscriptions", status_code=201)
def add_subscription(tenant_id: uuid.UUID, body: SubscriptionCreate, admin: SuperAdmin = Depends(get_admin),
                     db: Session = Depends(get_db)):
    """Nuovo periodo con date libere (dal/al) — usato anche per il cambio pacchetto."""
    t = _get_tenant(db, tenant_id)
    plan = _plan(db, body.plan_code)
    amount = body.amount if body.amount is not None else _list_price(plan, body.period)
    life = lifecycle_settings(db)
    fields = body.model_dump(exclude={"plan_code", "amount", "start_date", "end_date"})
    fields["grace_days"] = life["grace_days"] if body.grace_days is None else body.grace_days
    fields["readonly_days"] = life["readonly_days"] if body.readonly_days is None else body.readonly_days
    _insert_period(db, t, admin.id, plan, body.start_date, body.end_date, amount=amount, **fields)
    db.expire(t)
    return _tenant_out(_get_tenant(db, tenant_id), detail=True)


class ConvertTrial(BaseModel):
    plan_code: str
    period: str = Field("annuale", pattern="^(mensile|annuale)$")
    start: str = Field("oggi", pattern="^(oggi|fine_prova)$")  # da oggi o dal giorno dopo la fine della prova
    amount: Decimal | None = None
    grace_days: int | None = None
    readonly_days: int | None = None
    notes: str | None = None


@router.post("/tenants/{tenant_id}/convert-trial")
def convert_trial(tenant_id: uuid.UUID, body: ConvertTrial, admin: SuperAdmin = Depends(get_admin),
                  db: Session = Depends(get_db)):
    """Converte la prova in abbonamento: nuovo periodo pagato (pacchetto e periodicità a scelta) da oggi, chiudendo
    la prova a ieri, oppure dal giorno dopo la fine della prova. L'azienda riparte con i suoi dati."""
    t = _get_tenant(db, tenant_id)
    trial = max((s for s in t.subscriptions if s.is_trial), key=lambda s: s.start_date, default=None)
    if trial is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Questa azienda non ha un periodo di prova da convertire")
    if any(not s.is_trial and s.start_date >= trial.start_date for s in t.subscriptions):
        raise HTTPException(status.HTTP_409_CONFLICT, "La prova è già stata convertita in abbonamento")
    plan = _plan(db, body.plan_code)
    start = today() if body.start == "oggi" else trial.end_date + timedelta(days=1)
    amount = body.amount if body.amount is not None else _list_price(plan, body.period)
    life = lifecycle_settings(db)
    # la prova resta nello storico: chiusa a ieri (o al suo primo giorno, se è iniziata oggi)
    if trial.end_date >= start:
        trial.end_date = max(trial.start_date, start - timedelta(days=1))
    _insert_period(db, t, admin.id, plan, start, logic.next_period(start, body.period), action="conversione_prova", keep=trial,
                   amount=amount, period=body.period, is_trial=False,
                   grace_days=life["grace_days"] if body.grace_days is None else body.grace_days,
                   readonly_days=life["readonly_days"] if body.readonly_days is None else body.readonly_days,
                   notes=body.notes or "Conversione della prova gratuita")
    db.expire(t)
    return _tenant_out(_get_tenant(db, tenant_id), detail=True)


@router.post("/tenants/{tenant_id}/renew")
def renew(tenant_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    """Rinnovo con un clic: nuovo periodo stesso pacchetto e periodicità, dal giorno dopo la scadenza
    (o da oggi, se il cliente è scaduto da più della tolleranza)."""
    t = _get_tenant(db, tenant_id)
    st = tenant_state(t)
    last = max(t.subscriptions, key=lambda s: s.end_date, default=None)
    if last is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nessun abbonamento da rinnovare")
    start = last.end_date + timedelta(days=1)
    if st.status in ("sola_lettura", "sospeso", "prova_scaduta") and start < today():
        start = today()
    period = "annuale" if last.period == "personalizzata" else last.period
    plan = last.plan
    amount = plan.price_month if period == "mensile" else plan.price_year
    if not last.is_trial and last.period == period:
        amount = last.amount
    sub = Subscription(tenant_id=t.id, plan_id=plan.id, start_date=start, end_date=logic.next_period(start, period),
                       amount=amount, period=period,
                       # da una prova (senza tolleranza propria) si parte dai valori predefiniti del pannello
                       grace_days=lifecycle_settings(db)["grace_days"] if last.is_trial else last.grace_days,
                       readonly_days=lifecycle_settings(db)["readonly_days"] if last.is_trial else last.readonly_days)
    db.add(sub)
    audit(db, "subscription", "rinnovo", tenant_id=t.id, admin_id=admin.id,
          after={"plan": plan.code, "dal": str(sub.start_date), "al": str(sub.end_date)})
    db.flush()
    db.expire(t)
    return _tenant_out(_get_tenant(db, tenant_id), detail=True)


class SubscriptionUpdate(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    amount: Decimal | None = None
    grace_days: int | None = None
    readonly_days: int | None = None
    notes: str | None = None


@router.patch("/subscriptions/{sub_id}")
def update_subscription(sub_id: uuid.UUID, body: SubscriptionUpdate, admin: SuperAdmin = Depends(get_admin),
                        db: Session = Depends(get_db)):
    sub = db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Periodo non trovato")
    data = body.model_dump(exclude_unset=True)
    before = {k: str(getattr(sub, k)) for k in data}
    for k, v in data.items():
        setattr(sub, k, v)
    if sub.end_date < sub.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La data di fine è precedente all'inizio")
    audit(db, "subscription", "modifica", sub.id, tenant_id=sub.tenant_id, admin_id=admin.id,
          before=before, after={k: str(v) for k, v in data.items()})
    db.flush()
    return _tenant_out(_get_tenant(db, sub.tenant_id), detail=True)


@router.delete("/subscriptions/{sub_id}")
def delete_subscription(sub_id: uuid.UUID, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    sub = db.get(Subscription, sub_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Periodo non trovato")
    tenant_id = sub.tenant_id
    audit(db, "subscription", "eliminazione", sub.id, tenant_id=tenant_id, admin_id=admin.id, before=_sub_out(sub))
    db.delete(sub)
    db.flush()
    return _tenant_out(_get_tenant(db, tenant_id), detail=True)


# ---------------------------------------------------------------- pacchetti


@router.get("/plans")
def list_plans(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    return [
        {"id": str(p.id), "code": p.code, "name": p.name, "price_month": str(p.price_month),
         "price_year": str(p.price_year), "modules": p.modules, "max_users": p.max_users,
         "max_companies": p.max_companies, "max_warehouses": p.max_warehouses, "max_pos": p.max_pos}
        for p in db.scalars(select(Plan).order_by(Plan.sort_order))
    ]


@router.get("/modules")
def list_modules(admin: SuperAdmin = Depends(get_admin)):
    return [{"code": k, "label": v} for k, v in logic.MODULES.items() if k in logic.CATALOG_MODULES]


class PlanUpdate(BaseModel):
    name: str | None = None
    price_month: Decimal | None = None
    price_year: Decimal | None = None
    modules: list[str] | None = None
    max_users: int | None = None
    max_companies: int | None = None
    max_warehouses: int | None = None
    max_pos: int | None = None


@router.patch("/plans/{code}")
def update_plan(code: str, body: PlanUpdate, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    plan = _plan(db, code)
    data = body.model_dump(exclude_unset=True)
    if "modules" in data and set(data["modules"]) - set(logic.CATALOG_MODULES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Moduli sconosciuti")
    for k, v in data.items():
        setattr(plan, k, v)
    audit(db, "plan", "modifica", plan.code, admin_id=admin.id, after={k: str(v) for k, v in data.items()})
    return {"ok": True}


# ---------------------------------------------------------------- email e avvisi


@router.get("/email-templates")
def list_templates(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    return [{"code": t.code, "description": t.description, "subject": t.subject, "body": t.body}
            for t in db.scalars(select(EmailTemplate).order_by(EmailTemplate.code))]


class TemplateUpdate(BaseModel):
    subject: str
    body: str


@router.put("/email-templates/{code}")
def update_template(code: str, body: TemplateUpdate, admin: SuperAdmin = Depends(get_admin),
                    db: Session = Depends(get_db)):
    tpl = db.get(EmailTemplate, code)
    if tpl is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modello non trovato")
    tpl.subject, tpl.body = body.subject, body.body
    audit(db, "email_template", "modifica", code, admin_id=admin.id)
    return {"ok": True}


@router.get("/reminder-rules")
def get_rules(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    return [r.days_before for r in db.scalars(select(ReminderRule).where(ReminderRule.active).order_by(ReminderRule.days_before.desc()))]


class RulesUpdate(BaseModel):
    days: list[int] = Field(min_length=1)


@router.put("/reminder-rules")
def set_rules(body: RulesUpdate, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    days = sorted({d for d in body.days if 0 <= d <= 365}, reverse=True)
    for r in db.scalars(select(ReminderRule)):
        db.delete(r)
    db.flush()
    for d in days:
        db.add(ReminderRule(days_before=d, active=True))
    audit(db, "reminder_rules", "modifica", admin_id=admin.id, after={"giorni": days})
    return days


class LifecycleUpdate(BaseModel):
    grace_days: int | None = Field(None, ge=0, le=365)
    readonly_days: int | None = Field(None, ge=0, le=365)
    trial_reminder_days: list[int] | None = None


@router.get("/lifecycle")
def get_lifecycle(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    """Valori predefiniti del ciclo di vita: valgono per i nuovi periodi (ognuno conserva i suoi)."""
    return lifecycle_settings(db)


@router.put("/lifecycle")
def set_lifecycle(body: LifecycleUpdate, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    if "trial_reminder_days" in data:
        data["trial_reminder_days"] = sorted({d for d in data["trial_reminder_days"] if 0 <= d <= 60}, reverse=True)
    for k, v in data.items():
        row = db.get(SaasSetting, k)
        if row is None:
            db.add(SaasSetting(key=k, value=v))
        else:
            row.value = v
    audit(db, "saas_settings", "modifica", admin_id=admin.id, after=data)
    db.flush()
    return lifecycle_settings(db)


@router.get("/email-log")
def email_log(limit: int = 100, admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(EmailLog, Tenant.name).outerjoin(Tenant, Tenant.id == EmailLog.tenant_id)
        .order_by(EmailLog.sent_at.desc()).limit(min(limit, 500))
    ).all()
    return [{"id": str(e.id), "tenant": name, "rule": e.rule, "recipients": e.recipients, "subject": e.subject,
             "success": e.success, "error": e.error, "sent_at": e.sent_at.isoformat()} for e, name in rows]


@router.post("/reminders/run")
def run_now(admin: SuperAdmin = Depends(get_admin), db: Session = Depends(get_db)):
    """Esegue subito il controllo scadenze (normalmente parte da solo ogni mattina)."""
    return {"sent": run_reminders(db, today())}


@router.get("/audit")
def audit_list(tenant_id: uuid.UUID | None = None, limit: int = 100, admin: SuperAdmin = Depends(get_admin),
               db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.at.desc()).limit(min(limit, 500))
    if tenant_id:
        q = q.where(AuditLog.tenant_id == tenant_id)
    return [{"at": a.at.isoformat(), "entity": a.entity, "action": a.action, "entity_id": a.entity_id,
             "admin": bool(a.admin_id), "before": a.before, "after": a.after} for a in db.scalars(q)]
