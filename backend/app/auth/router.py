"""Accesso degli utenti delle aziende clienti: /api/auth/..."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth import accounts, passwords
from app.core.config import get_settings
from app.core.db import get_db, set_tenant
from app.core.deps import TenantContext, get_tenant_ctx
from app.core.models import User
from app.core.security import create_token, hash_password, verify_password
from app.saas.service import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    passwords.rate_limit(f"login:{passwords.client_ip(request)}", 30, 600)
    row = db.execute(text("SELECT * FROM auth_find_user(:e)"), {"e": body.email}).mappings().first()
    if row is None or not row["active"] or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email o password errate")
    # Il login resta permesso anche con l'abbonamento sospeso o la prova scaduta: il gestionale mostra solo
    # la pagina «Abbonamento» (gli altri servizi rispondono 402, vedi get_tenant_ctx).
    token = create_token(row["id"], "user", get_settings().access_token_minutes, tenant_id=row["tenant_id"])
    return {"token": token}


class ActivateIn(BaseModel):
    token: str
    password: str = Field(min_length=8)


@router.post("/activate")
def activate(body: ActivateIn, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM auth_find_activation(:t)"), {"t": body.token}).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link di attivazione non valido o già usato")
    set_tenant(db, row["tenant_id"])
    user = db.get(User, row["id"])
    passwords.check_strength(body.password)
    user.password_hash = hash_password(body.password)
    user.activation_token = None
    user.must_change_password = False
    audit(db, "user", "attivazione", user.id, tenant_id=user.tenant_id, user_id=user.id)
    token = create_token(user.id, "user", get_settings().access_token_minutes, tenant_id=user.tenant_id)
    return {"token": token}


@router.get("/me")
def me(ctx: TenantContext = Depends(get_tenant_ctx)):
    t = ctx.state.tenant
    return {
        "user": {"id": str(ctx.user.id), "email": ctx.user.email, "full_name": ctx.user.full_name,
                 "role": ctx.user.role, "must_change_password": ctx.user.must_change_password and ctx.impersonated_by is None},
        "tenant": {"id": str(t.id), "name": t.name, "sector": t.sector},
        "subscription": ctx.state.to_dict(),
        "impersonated": ctx.impersonated_by is not None,
    }


class PasswordChange(BaseModel):
    current: str
    new: str = Field(min_length=8)


@router.post("/password")
def change_password(body: PasswordChange, ctx: TenantContext = Depends(get_tenant_ctx)):
    if not verify_password(body.current, ctx.user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Password attuale errata")
    if body.current == body.new:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La nuova password deve essere diversa da quella attuale")
    passwords.check_strength(body.new)
    ctx.user.password_hash = hash_password(body.new)
    ctx.user.must_change_password = False
    audit(ctx.db, "user", "cambio password", ctx.user.id, tenant_id=ctx.user.tenant_id, user_id=ctx.user.id)
    return {"ok": True}


class ForgotIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)


@router.post("/password-dimenticata")
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    """Manda il link per reimpostare la password. Risponde sempre allo stesso modo, anche se l'email non esiste."""
    passwords.rate_limit(f"forgot:{passwords.client_ip(request)}", 5, 900)
    passwords.rate_limit(f"forgot:{body.email.strip().lower()}", 3, 900)
    accounts.request_user_reset(db, body.email)
    return {"ok": True, "message": "Se l'indirizzo è registrato, riceverai un'email con il link per reimpostare la password."}


class ResetIn(BaseModel):
    token: str = Field(min_length=10)
    password: str = Field(min_length=8)


@router.post("/reimposta-password")
def reset(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    passwords.rate_limit(f"reset:{passwords.client_ip(request)}", 10, 900)
    user = accounts.reset_user(db, body.token, body.password)
    token = create_token(user.id, "user", get_settings().access_token_minutes, tenant_id=user.tenant_id)
    return {"token": token}

