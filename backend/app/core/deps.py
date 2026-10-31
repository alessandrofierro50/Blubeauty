import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db, set_tenant
from app.core.models import SuperAdmin, User
from app.core.security import decode_token
from app.saas.logic import MODULES, blocked_code
from app.saas.service import TenantState, load_tenant, tenant_state

bearer = HTTPBearer(auto_error=False)

READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def _payload(creds: HTTPAuthorizationCredentials | None, scope: str) -> dict:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Accesso richiesto")
    try:
        payload = decode_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione scaduta o non valida") from None
    if payload.get("scope") != scope:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Accesso non consentito")
    return payload


def get_admin(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> SuperAdmin:
    payload = _payload(creds, "admin")
    admin = db.get(SuperAdmin, uuid.UUID(payload["sub"]))
    if admin is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Amministratore non trovato")
    # credenziali cambiate dalla Console: le sessioni aperte prima non valgono più
    if payload.get("ver", 0) != (admin.token_version or 0):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione scaduta o non valida")
    return admin


@dataclass
class TenantContext:
    user: User
    state: TenantState
    db: Session
    impersonated_by: uuid.UUID | None = None

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.user.tenant_id


PASSWORD_CHANGE_PATHS = {"/api/auth/me", "/api/auth/password", "/api/app/status"}
# Sempre permesse, anche in sola lettura e con l'abbonamento sospeso o la prova scaduta (standard comune §3):
# chi sono, cambio password, stato e pagina «Abbonamento» con i contatti per rinnovare.
SUBSCRIPTION_PATHS = PASSWORD_CHANGE_PATHS | {"/api/app/abbonamento"}
# Pagamenti online (comune/pagamenti.md): chi è scaduto o sospeso deve poter pagare per riattivarsi.
PAYMENT_PREFIX = "/api/app/pagamenti/"


def subscription_path(path: str) -> bool:
    return path in SUBSCRIPTION_PATHS or path.startswith(PAYMENT_PREFIX)

BLOCKED_MESSAGES = {
    "abbonamento_sospeso": "Abbonamento sospeso o scaduto. Contatta l'assistenza per rinnovarlo.",
    "prova_scaduta": "Il periodo di prova è terminato. Contattaci per attivare l'abbonamento: i tuoi dati sono al sicuro.",
}


def get_tenant_ctx(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> TenantContext:
    payload = _payload(creds, "user")
    tenant_id = uuid.UUID(payload["tid"])
    set_tenant(db, tenant_id)
    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Utente non attivo")
    tenant = load_tenant(db, tenant_id)
    state = tenant_state(tenant)

    path = request.url.path
    if state.access == "none" and not subscription_path(path):
        code = blocked_code(state.status)
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, {"code": code, "message": BLOCKED_MESSAGES[code]})
    if state.access == "readonly" and request.method not in READ_METHODS and not subscription_path(path):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            {"code": "sola_lettura", "message": "Abbonamento scaduto: il gestionale è in sola lettura."},
        )
    imp = payload.get("imp")
    if imp:  # impersonificazione: decade anche lei se le credenziali del super amministratore cambiano
        admin = db.get(SuperAdmin, uuid.UUID(imp))
        if admin is None or payload.get("ver", 0) != (admin.token_version or 0):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessione scaduta o non valida")
    # password provvisoria (qualunque l'abbia creata): finché non la cambia, l'utente può solo leggere chi è e cambiarla.
    # Il blocco è qui e non solo nel frontend, perché /cassa e /giro sono fuori dal layout che mostra il cambio obbligatorio.
    if user.must_change_password and not imp and request.url.path not in PASSWORD_CHANGE_PATHS:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            {"code": "cambio_password", "message": "Prima di continuare scegli una password tua al posto di quella provvisoria."},
        )
    return TenantContext(user=user, state=state, db=db, impersonated_by=uuid.UUID(imp) if imp else None)


def require_module(module: str):
    """Blocca lato server le funzioni dei moduli non inclusi nel pacchetto del cliente."""
    if module not in MODULES:
        raise ValueError(f"Modulo sconosciuto: {module}")

    def checker(ctx: TenantContext = Depends(get_tenant_ctx)) -> TenantContext:
        if module not in ctx.state.modules:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                {
                    "code": "modulo_non_incluso",
                    "module": module,
                    "message": f"«{MODULES[module]}» è disponibile in un pacchetto superiore.",
                },
            )
        return ctx

    return checker


def require_role(*roles: str):
    def checker(ctx: TenantContext = Depends(get_tenant_ctx)) -> TenantContext:
        if ctx.user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permesso insufficiente")
        return ctx

    return checker
