"""Credenziali e recupero password per gli utenti delle aziende e per il super amministratore.

Le risposte alle richieste di recupero sono sempre uguali (anche se l'email non esiste): così non si può usare la
pagina per scoprire quali indirizzi sono registrati."""

import html
import logging
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import passwords
from app.core.config import get_settings
from app.core.db import set_tenant
from app.core.mailer import send_email
from app.core.models import EmailTemplate, SuperAdmin, User
from app.core.security import hash_password
from app.saas import logic
from app.saas.service import audit

log = logging.getLogger(__name__)


def send_template(db: Session, code: str, to: str, values: dict, raw: dict | None = None,
                  attachments: list[tuple[str, bytes, str]] | None = None) -> bool:
    """Email da modello del pannello; i valori sono "puliti" (un nome inserito da un modulo pubblico non diventa HTML).
    `raw`: blocchi HTML preparati dal programma (non escapati); se il modello salvato non ha il segnaposto, il blocco
    si aggiunge in fondo (così funziona anche con i modelli già personalizzati nel pannello)."""
    tpl = db.get(EmailTemplate, code)
    if tpl is None:  # modello non ancora caricato nel pannello: si usa quello predefinito
        from app.saas.defaults import DEFAULT_TEMPLATES
        d = next((t for t in DEFAULT_TEMPLATES if t["code"] == code), None)
        if d is None:
            log.warning("Modello email %s mancante", code)
            return False
        tpl = EmailTemplate(**d)
    safe = {k: html.escape(str(v)) for k, v in values.items()}
    body = tpl.body
    for k, v in (raw or {}).items():
        body = body.replace("{" + k + "}", v) if "{" + k + "}" in body else body + v
    try:
        send_email([to], logic.render_placeholders(tpl.subject, values), logic.render_placeholders(body, safe), attachments)
        return True
    except Exception:  # noqa: BLE001  l'operazione resta valida: le credenziali si possono rimandare dal pannello
        log.exception("Invio email %s a %s non riuscito", code, to)
        return False


def set_temporary_password(db: Session, user: User, password: str | None = None) -> str:
    """Password provvisoria (scelta o generata): da cambiare al primo accesso. Restituisce la password in chiaro."""
    password = (password or "").strip() or passwords.temporary_password()
    passwords.check_strength(password)
    user.password_hash = hash_password(password)
    user.must_change_password = True
    user.activation_token = None
    user.reset_token_hash = user.reset_expires_at = None
    return password


def send_credentials(db: Session, user: User, company: str, password: str, period: str = "",
                     terms_version: str | None = None) -> bool:
    """Credenziali con password provvisoria. Con `terms_version` (prova dal sito) aggiunge il link ai termini accettati
    e allega il PDF scaricato da TERMS_PDF_URL; se il download non riesce l'email parte col solo link."""
    raw, attachments = {"termini": ""}, None
    if terms_version:
        url = terms_link(terms_version)
        raw["termini"] = (f'<p>Hai accettato i <a href="{html.escape(url)}">termini di utilizzo</a> '
                          f"(versione {html.escape(terms_version)}): li trovi anche in allegato.</p>")
        pdf = terms_pdf()
        if pdf:
            attachments = [(f"termini-di-utilizzo-v{terms_version}.pdf", pdf, "application/pdf")]
        else:
            raw["termini"] = raw["termini"].replace(": li trovi anche in allegato", "")
    return send_template(db, "credenziali_accesso", user.email, {
        "nome": user.full_name, "ragione_sociale": company, "email": user.email, "password": password,
        "link_accesso": f"{get_settings().public_url.rstrip('/')}/login", "periodo": period,
    }, raw=raw, attachments=attachments)


def terms_link(version: str) -> str:
    url = get_settings().terms_url.strip() or f"{get_settings().website_url.rstrip('/')}/termini/"
    return f"{url}{'&' if '?' in url else '?'}v={version}"


def terms_pdf() -> bytes | None:
    """PDF dei termini scaricato al momento dell'invio (timeout breve). None se non configurato o non raggiungibile."""
    return fetch_pdf(get_settings().terms_pdf_url)


def fetch_pdf(url: str) -> bytes | None:
    """Scarica un PDF (timeout 10 s). None se l'indirizzo è vuoto o il file non arriva."""
    url = (url or "").strip()
    if not url:
        return None
    try:
        r = httpx.get(url, timeout=10, follow_redirects=True)
        r.raise_for_status()
        if not r.content.startswith(b"%PDF"):
            raise ValueError("il file scaricato non è un PDF")
        return r.content
    except Exception as e:  # noqa: BLE001
        log.warning("PDF non scaricato da %s (%s): email senza allegato", url, e)
        return None


# ---------------------------------------------------------------- utenti delle aziende


def request_user_reset(db: Session, email: str) -> None:
    row = db.execute(text("SELECT * FROM auth_find_user(:e)"), {"e": email.strip()}).mappings().first()
    if row is None or not row["active"]:
        return
    set_tenant(db, row["tenant_id"])
    user = db.get(User, row["id"])
    token, digest, expires = passwords.new_reset()
    user.reset_token_hash, user.reset_expires_at = digest, expires
    audit(db, "user", "richiesta recupero password", user.id, tenant_id=user.tenant_id, user_id=user.id)
    send_template(db, "recupero_password", user.email, {
        "nome": user.full_name, "minuti": passwords.RESET_MINUTES,
        "link_reimposta": f"{get_settings().public_url.rstrip('/')}/reimposta-password?token={token}"})


def reset_user(db: Session, token: str, password: str) -> User:
    row = db.execute(text("SELECT * FROM auth_find_reset(:h)"), {"h": passwords.token_hash(token)}).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link non valido o scaduto: richiedine uno nuovo")
    passwords.check_strength(password)
    set_tenant(db, row["tenant_id"])
    user = db.get(User, row["id"])
    user.password_hash = hash_password(password)
    user.must_change_password = False
    user.activation_token = None
    user.reset_token_hash = user.reset_expires_at = None
    audit(db, "user", "password reimpostata", user.id, tenant_id=user.tenant_id, user_id=user.id)
    return user


# ---------------------------------------------------------------- super amministratore


def request_admin_reset(db: Session, email: str) -> None:
    admin = db.scalar(select(SuperAdmin).where(func.lower(SuperAdmin.email) == email.strip().lower()))
    if admin is None:
        return
    token, digest, expires = passwords.new_reset()
    admin.reset_token_hash, admin.reset_expires_at = digest, expires
    audit(db, "super_admin", "richiesta recupero password", admin.id, admin_id=admin.id)
    send_template(db, "recupero_password", admin.email, {
        "nome": "amministratore", "minuti": passwords.RESET_MINUTES,
        "link_reimposta": f"{get_settings().public_url.rstrip('/')}/admin/reimposta-password?token={token}"})


def reset_admin(db: Session, token: str, password: str) -> SuperAdmin:
    admin = db.scalar(select(SuperAdmin).where(SuperAdmin.reset_token_hash == passwords.token_hash(token),
                                               SuperAdmin.reset_expires_at > datetime.now(timezone.utc)))
    if admin is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Link non valido o scaduto: richiedine uno nuovo")
    check_admin_strength(password)
    admin.password_hash = hash_password(password)
    admin.reset_token_hash = admin.reset_expires_at = None
    audit(db, "super_admin", "password reimpostata", admin.id, admin_id=admin.id)
    return admin


def check_admin_strength(password: str) -> None:
    """Il super amministratore vede tutte le aziende: almeno 12 caratteri."""
    if len(password) < 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La password dell'amministratore deve avere almeno 12 caratteri")
    passwords.check_strength(password)
