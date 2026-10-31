import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import get_settings

log = logging.getLogger("blubeauty.mail")

# In sviluppo e nei test (SMTP non configurato) le email finiscono qui invece di partire.
OUTBOX: list[dict] = []


def sender() -> str:
    """Mittente mostrato: «BluBeauty · BluCode Informatica <info@blucodeinformatica.it>» (codificato se serve)."""
    s = get_settings()
    return formataddr((s.mail_from_name, s.smtp_from)) if s.mail_from_name else s.smtp_from


def send_email(to: list[str], subject: str, html: str, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    """Invia un'email HTML (con eventuali allegati: nome, contenuto, tipo MIME). Solleva un'eccezione se l'invio fallisce."""
    settings = get_settings()
    to = [t for t in to if t]
    if not to:
        raise ValueError("Nessun destinatario")
    if not settings.smtp_host:
        OUTBOX.append({"to": to, "subject": subject, "html": html, "attachments": [(n, len(b), t) for n, b, t in attachments or []]})
        log.info("SMTP non configurato, email non inviata: %s -> %s", subject, to)
        return

    msg = EmailMessage()
    msg["From"] = sender()
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content("Questo messaggio richiede un client email che supporti l'HTML.")
    msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        maintype, _, subtype = mime.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=name)

    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ssl.create_default_context()) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as s:
            if settings.smtp_tls:
                s.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
