"""Password provvisorie, link per reimpostare la password e limite di tentativi (contro gli abusi delle pagine pubbliche).

- La password provvisoria si legge solo quando nasce (creazione dell'azienda, rigenerazione, prova gratuita):
  nel database resta solo l'impronta, e al primo accesso va cambiata.
- Il link "password dimenticata" vale un'ora; nel database c'è solo il suo SHA-256.
"""

import hashlib
import secrets
import string
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.core.config import get_settings

RESET_MINUTES = 60
_ALPHABET = "".join(c for c in string.ascii_letters + string.digits if c not in "0OoIl1")
_memory: dict[str, list[float]] = {}


def temporary_password(length: int = 12) -> str:
    """Leggibile (niente 0/O, 1/l/I) e con almeno una maiuscola, una minuscola e una cifra."""
    while True:
        p = "".join(secrets.choice(_ALPHABET) for _ in range(length))
        if any(c.isupper() for c in p) and any(c.islower() for c in p) and any(c.isdigit() for c in p):
            return p


def check_strength(password: str) -> None:
    if len(password) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La password deve avere almeno 8 caratteri")
    if password.isdigit() or password.isalpha():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Usa lettere e numeri insieme")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_reset() -> tuple[str, str, datetime]:
    """(token da mandare nel link, impronta da salvare, scadenza)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token), datetime.now(timezone.utc) + timedelta(minutes=RESET_MINUTES)


def rate_limit(key: str, limit: int, seconds: int) -> None:
    """Al massimo `limit` richieste ogni `seconds` per chiave (IP, email…). Redis se c'è, altrimenti in memoria."""
    if not get_settings().rate_limits:
        return
    try:
        import redis
        r = redis.Redis.from_url(get_settings().redis_url, socket_timeout=1)
        k = f"rl:{key}"
        n = r.incr(k)
        if n == 1:
            r.expire(k, seconds)
        if n > limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Troppe richieste: riprova più tardi")
        return
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001  Redis non raggiungibile: limite nel processo
        now = time.time()
        hits = [t for t in _memory.get(key, []) if t > now - seconds]
        if len(hits) >= limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Troppe richieste: riprova più tardi") from None
        _memory[key] = [*hits, now]


def client_ip(request) -> str:
    """IP del visitatore: uvicorn lo ricava già dalle intestazioni dei proxy (nginx, Caddy)."""
    return request.client.host if request.client else "?"
