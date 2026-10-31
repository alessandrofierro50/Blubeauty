import secrets
import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
import pyotp

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str | None) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(
    subject: uuid.UUID,
    scope: str,
    minutes: int,
    tenant_id: uuid.UUID | None = None,
    impersonated_by: uuid.UUID | None = None,
    version: int | None = None,
) -> str:
    """scope: 'admin' per il super amministratore, 'user' per gli utenti delle aziende."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(subject),
        "scope": scope,
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    if tenant_id:
        payload["tid"] = str(tenant_id)
    if impersonated_by:
        payload["imp"] = str(impersonated_by)
    if version is not None:
        payload["ver"] = version  # super amministratore: confrontata con SuperAdmin.token_version
    return jwt.encode(payload, get_settings().secret_key, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=[ALGORITHM])


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=get_settings().brand_name)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def random_token() -> str:
    return secrets.token_urlsafe(32)
