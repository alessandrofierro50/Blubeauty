"""API dell'area cliente (Fase 1: stato abbonamento, menu moduli, utenti, ragioni sociali)."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core import media
from app.core.config import get_settings
from app.core.deps import TenantContext, get_tenant_ctx, require_module, require_role
from app.core.mailer import send_email
from app.core.models import Company, EmailTemplate, User, Warehouse
from app.core.security import random_token
from app.saas import logic
from app.pagamenti.service import active_methods
from app.saas.service import audit

router = APIRouter(prefix="/api/app", tags=["app"])

ROLES = ["amministratore", "amministrazione", "contabilita", "vendite", "agente", "magazzino", "cassa"]


@router.get("/status")
def app_status(ctx: TenantContext = Depends(get_tenant_ctx)):
    """Banner di scadenza e menu: i moduli non inclusi sono mostrati come 'pacchetto superiore'."""
    st = ctx.state
    banner = None
    if st.status == "in_scadenza":
        banner = {"level": "warning", "text": f"Il tuo abbonamento scade tra {st.days_left} giorni."}
    elif st.status == "prova":
        banner = {"level": "info", "text": f"Periodo di prova: restano {st.days_left} giorni."}
    elif st.status == "tolleranza":
        banner = {"level": "error", "text": "Abbonamento scaduto: rinnova per evitare il passaggio in sola lettura."}
    elif st.status == "sola_lettura":
        banner = {"level": "error", "text": "Abbonamento scaduto: il gestionale è in sola lettura."}
    elif st.status == "sospeso":
        banner = {"level": "error", "text": "Abbonamento sospeso: rinnova per tornare a usare il gestionale."}
    elif st.status == "prova_scaduta":
        banner = {"level": "error", "text": "Il periodo di prova è terminato: attiva l'abbonamento per continuare con i tuoi dati."}
    if banner and st.status != "prova":
        banner["renew"] = True  # pulsante «Rinnova ora» verso la pagina di pagamento (comune/pagamenti.md)
    elif banner and st.days_left is not None and st.days_left <= 3:
        banner["renew"] = True
    return {
        **st.to_dict(),
        "banner": banner,
        "menu": [{"code": code, "label": label, "enabled": code in st.modules, "extra": code in logic.EXTRA_MODULES}
                 for code, label in logic.MODULES.items() if code in logic.CATALOG_MODULES],
    }


@router.get("/abbonamento")
def subscription_page(ctx: TenantContext = Depends(get_tenant_ctx)):
    """Pagina «Abbonamento» (standard comune §5): piano, stato, scadenza e giorni mancanti, contatti per rinnovare;
    per l'amministratore anche uso rispetto ai limiti e storico dei periodi. Permessa anche da sospesi e in sola lettura."""
    from app.pos.models import PosRegister

    st = ctx.state
    s = get_settings()
    out = {
        **st.to_dict(),
        "tenant": st.tenant.name,
        "is_trial": bool(st.subscription and st.subscription.is_trial),
        "period": st.subscription.period if st.subscription else None,
        "amount": str(st.subscription.amount) if st.subscription and ctx.user.role == "amministratore" else None,
        "grace_days": st.subscription.grace_days if st.subscription else None,
        "readonly_days": st.subscription.readonly_days if st.subscription else None,
        "contacts": {"email": s.support_email, "phone": s.support_phone, "website": s.website_url},
        "is_admin": ctx.user.role == "amministratore",
        "online_payments": bool(active_methods(ctx.db)),  # «Rinnova ora» verso /pagamento
    }
    if ctx.user.role != "amministratore":
        return out
    db = ctx.db
    out["usage"] = {
        "max_users": db.scalar(select(func.count()).select_from(User).where(User.active)),
        "max_companies": db.scalar(select(func.count()).select_from(Company)),
        "max_warehouses": db.scalar(select(func.count()).select_from(Warehouse)),
        "max_pos": db.scalar(select(func.count()).select_from(PosRegister)),
    }
    out["history"] = [
        {"plan_name": x.plan.name, "plan_code": x.plan.code, "start_date": x.start_date.isoformat(),
         "end_date": x.end_date.isoformat(), "period": x.period, "amount": str(x.amount), "is_trial": x.is_trial}
        for x in sorted(st.tenant.subscriptions, key=lambda x: x.start_date, reverse=True)
    ]
    return out


@router.get("/companies")
def companies(ctx: TenantContext = Depends(get_tenant_ctx)):
    rows = ctx.db.scalars(select(Company).order_by(Company.name))
    return [{"id": str(c.id), "name": c.name, "vat_number": c.vat_number, "city": c.city} for c in rows]


@router.get("/warehouses")
def warehouses(ctx: TenantContext = Depends(get_tenant_ctx)):
    rows = ctx.db.scalars(select(Warehouse).order_by(Warehouse.code))
    return [{"id": str(w.id), "code": w.code, "name": w.name} for w in rows]


# ---------------------------------------------------------------- utenti


@router.get("/users")
def list_users(ctx: TenantContext = Depends(require_role("amministratore"))):
    return {
        "max_users": ctx.state.limits["max_users"],
        "roles": ROLES,
        "me": str(ctx.user.id),
        "users": [
            {"id": str(u.id), "email": u.email, "full_name": u.full_name, "role": u.role, "active": u.active,
             "pending_activation": u.password_hash is None, "must_change_password": u.must_change_password}
            for u in ctx.db.scalars(select(User).order_by(User.full_name))
        ],
    }


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    role: str = "vendite"


@router.post("/users", status_code=201)
def create_user(body: UserCreate, ctx: TenantContext = Depends(require_role("amministratore"))):
    if body.role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ruolo non valido")
    active_users = ctx.db.scalar(select(func.count()).select_from(User).where(User.active))
    if active_users >= ctx.state.limits["max_users"]:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "limite_utenti", "message": f"Il tuo pacchetto consente al massimo {ctx.state.limits['max_users']} utenti."},
        )
    user = User(tenant_id=ctx.tenant_id, email=body.email.lower(), full_name=body.full_name, role=body.role,
                activation_token=random_token())
    ctx.db.add(user)
    try:
        ctx.db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esiste già un utente con questa email") from None
    audit(ctx.db, "user", "creazione", user.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          admin_id=ctx.impersonated_by, after={"email": user.email, "role": user.role})
    link = f"{get_settings().public_url}/attiva?token={user.activation_token}"
    tpl = ctx.db.get(EmailTemplate, "attivazione_utente")
    if tpl:
        values = {"nome": user.full_name, "ragione_sociale": ctx.state.tenant.name, "link_attivazione": link}
        try:
            send_email([user.email], logic.render_placeholders(tpl.subject, values),
                       logic.render_placeholders(tpl.body, values))
        except Exception:
            pass
    return {"id": str(user.id), "activation_link": link}


class UserUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None
    active: bool | None = None


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserUpdate, ctx: TenantContext = Depends(require_role("amministratore"))):
    user = ctx.db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utente non trovato")
    data = body.model_dump(exclude_unset=True)
    if "role" in data and data["role"] not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ruolo non valido")
    if user.id == ctx.user.id and (data.get("active") is False or data.get("role", "amministratore") != "amministratore"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Non puoi disattivare o declassare te stesso")
    if data.get("active") and not user.active:
        active_users = ctx.db.scalar(select(func.count()).select_from(User).where(User.active))
        if active_users >= ctx.state.limits["max_users"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "limite_utenti", "message": "Limite utenti raggiunto."})
    for k, v in data.items():
        setattr(user, k, v)
    audit(ctx.db, "user", "modifica", user.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          admin_id=ctx.impersonated_by, after={k: str(v) for k, v in data.items()})
    return {"ok": True}


class UserPasswordIn(BaseModel):
    password: str | None = None  # vuota: la genera BluBeauty
    send_email: bool = True


@router.post("/users/{user_id}/password")
def set_user_password(user_id: uuid.UUID, body: UserPasswordIn, ctx: TenantContext = Depends(require_role("amministratore"))):
    """Password provvisoria per un altro utente dell'azienda: da cambiare al primo accesso, la si vede solo qui."""
    from app.auth import accounts
    user = ctx.db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Utente non trovato")
    if user.id == ctx.user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Per la tua password usa «Cambia password»")
    password = accounts.set_temporary_password(ctx.db, user, body.password)
    audit(ctx.db, "user", "password provvisoria", user.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          admin_id=ctx.impersonated_by)
    sent = accounts.send_credentials(ctx.db, user, ctx.state.tenant.name, password) if body.send_email else False
    return {"username": user.email, "password": password, "email_sent": sent}


# ---------------------------------------------------------------- verifica moduli
# Punto di controllo usato dal frontend e dai test: ogni router delle fasi successive
# userà la stessa dipendenza require_module(...).


@router.get("/modules/{module}/check")
def module_check(module: str, ctx: TenantContext = Depends(get_tenant_ctx)):
    if module not in logic.MODULES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modulo sconosciuto")
    require_module(module)(ctx)
    return {"module": module, "enabled": True}


# ---------------------------------------------------------------- dati azienda e layout di stampa

COMPANY_FIELDS = ["name", "vat_number", "tax_code", "tax_regime", "address", "zip_code", "city", "province", "pec",
                  "email", "phone", "website", "iban", "bank_name", "rea_office", "rea_number", "share_capital",
                  "sole_shareholder", "in_liquidation"]
DEFAULT_PRINT = {"primary_color": "#2340a8", "footer": "", "header_note": "", "show_bank": True, "logo_position": "sinistra"}


def _company_out(c: Company) -> dict:
    out = {f: (str(getattr(c, f)) if f == "share_capital" and getattr(c, f) is not None else getattr(c, f)) for f in COMPANY_FIELDS}
    out.update({"id": str(c.id), "print_settings": {**DEFAULT_PRINT, **(c.print_settings or {})},
                "logo_url": media.urls(c.logo_file)["url"] if c.logo_file else None})
    return out


def _company(ctx: TenantContext, company_id: uuid.UUID | None = None) -> Company:
    c = ctx.db.get(Company, company_id) if company_id else ctx.db.scalar(select(Company).order_by(Company.name))
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ragione sociale non trovata")
    return c


@router.get("/intestazione")
def print_header(company_id: uuid.UUID | None = None, ctx: TenantContext = Depends(get_tenant_ctx)):
    """Dati e layout usati da tutte le stampe (cataloghi, listini, preventivi, ordini, DDT, fatture)."""
    return _company_out(_company(ctx, company_id))


class CompanyIn(BaseModel):
    name: str
    vat_number: str | None = None
    tax_code: str | None = None
    tax_regime: str = "RF01"
    address: str | None = None
    zip_code: str | None = None
    city: str | None = None
    province: str | None = None
    pec: str | None = None
    email: str | None = None
    phone: str | None = None
    website: str | None = None
    iban: str | None = None
    bank_name: str | None = None
    rea_office: str | None = None
    rea_number: str | None = None
    share_capital: Decimal | None = None
    sole_shareholder: str | None = Field(None, pattern="^(SU|SM)?$")
    in_liquidation: bool = False
    print_settings: dict = {}


@router.put("/azienda/{company_id}")
def update_company(company_id: uuid.UUID, body: CompanyIn, ctx: TenantContext = Depends(require_role("amministratore"))):
    c = _company(ctx, company_id)
    for k, v in body.model_dump(exclude={"print_settings"}).items():
        setattr(c, k, v if k in ("name", "in_liquidation") else (v or None))
    ps = {k: v for k, v in body.print_settings.items() if k in DEFAULT_PRINT}
    c.print_settings = {**DEFAULT_PRINT, **ps}
    audit(ctx.db, "company", "modifica", c.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id)
    return _company_out(c)


@router.post("/azienda/{company_id}/logo")
async def upload_logo(company_id: uuid.UUID, file: UploadFile = File(...), ctx: TenantContext = Depends(require_role("amministratore"))):
    c = _company(ctx, company_id)
    old = c.logo_file
    c.logo_file = media.save_image(await file.read())
    if old:
        media.delete_image(old)
    return _company_out(c)


@router.delete("/azienda/{company_id}/logo")
def delete_logo(company_id: uuid.UUID, ctx: TenantContext = Depends(require_role("amministratore"))):
    c = _company(ctx, company_id)
    if c.logo_file:
        media.delete_image(c.logo_file)
    c.logo_file = None
    return _company_out(c)
