"""Solleciti di pagamento: proposta per cliente, invio email (singolo, massivo, automatico), testo per WhatsApp."""

import html
import logging
import re
import urllib.parse
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Party
from app.core import mailer
from app.core.models import Company
from app.documenti.models import Document
from app.scadenzario import service as due
from app.scadenzario.models import Installment, PaymentReminder

log = logging.getLogger(__name__)
LEVELS = {1: "Promemoria cortese", 2: "Secondo sollecito", 3: "Diffida"}


def eur(v: Decimal) -> str:
    q = f"{Decimal(v):,.2f}"
    return q.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def overdue_by_party(db: Session, on: date, party_ids: list | None = None) -> dict:
    stmt = select(Installment).where(Installment.direction == "attiva", Installment.status != "pagata",
                                     Installment.due_date < on, Installment.party_id.is_not(None))
    if party_ids:
        stmt = stmt.where(Installment.party_id.in_(party_ids))
    out: dict = defaultdict(list)
    for i in db.scalars(stmt.order_by(Installment.due_date)):
        if due.residual(i) > 0:
            out[i.party_id].append(i)
    return out


def target_level(days_late: int, thresholds: list[int]) -> int:
    return sum(1 for t in thresholds[:3] if days_late >= int(t))


def proposal(db: Session, tenant_id, on: date) -> list[dict]:
    cfg = due.settings(db, tenant_id)
    groups = overdue_by_party(db, on)
    parties = {p.id: p for p in db.scalars(select(Party).where(Party.id.in_(list(groups))))} if groups else {}
    last = {}
    if groups:
        for r in db.scalars(select(PaymentReminder).where(PaymentReminder.party_id.in_(list(groups)), PaymentReminder.status == "inviato")
                            .order_by(PaymentReminder.sent_at)):
            last[r.party_id] = r
    out = []
    for pid, rows in groups.items():
        p = parties.get(pid)
        days = max((on - i.due_date).days for i in rows)
        current = max(i.reminder_level for i in rows)
        target = target_level(days, cfg["days"])
        out.append({
            "party_id": str(pid), "name": p.name if p else "", "email": (p.email or p.pec) if p else None,
            "phone": (p.mobile or p.phone) if p else None, "total": str(sum((due.residual(i) for i in rows), Decimal(0))),
            "count": len(rows), "days_late": days, "oldest_due": rows[0].due_date.isoformat(), "current_level": current,
            "suggested_level": min(max(current + 1, 1), 3), "due_now": target > current,
            "unpaid": sum(1 for i in rows if i.unpaid),
            "last_reminder": {"level": last[pid].level, "at": last[pid].sent_at.isoformat(), "channel": last[pid].channel} if pid in last else None,
            "installments": [{"id": str(i.id), "description": i.description, "due_date": i.due_date.isoformat(),
                              "residual": str(due.residual(i)), "days_late": (on - i.due_date).days, "unpaid": i.unpaid,
                              "document_id": str(i.document_id) if i.document_id else None} for i in rows],
        })
    out.sort(key=lambda r: (-r["days_late"], r["name"]))
    return out


def _context(db: Session, party: Party, rows: list[Installment], on: date) -> dict:
    company = db.scalar(select(Company).order_by(Company.name))
    total = sum((due.residual(i) for i in rows), Decimal(0))
    docs = {}
    for i in rows:
        if i.document_id and i.document_id not in docs:
            docs[i.document_id] = db.get(Document, i.document_id)
    table = ["<table style='border-collapse:collapse;font-size:14px;margin:8px 0'>",
             "<tr style='background:#eef3fd'><th align='left' style='padding:6px 10px'>Documento</th>"
             "<th align='left' style='padding:6px 10px'>Scadenza</th><th align='right' style='padding:6px 10px'>Da saldare</th></tr>"]
    for i in rows:
        table.append(f"<tr><td style='padding:5px 10px;border-bottom:1px solid #e5e9f0'>{html.escape(i.description.split(' – ')[0])}"
                     f"{' – rata ' + str(i.seq) + '/' + str(i.total_seq) if i.total_seq > 1 else ''}</td>"
                     f"<td style='padding:5px 10px;border-bottom:1px solid #e5e9f0'>{i.due_date.strftime('%d/%m/%Y')}</td>"
                     f"<td align='right' style='padding:5px 10px;border-bottom:1px solid #e5e9f0'>{eur(due.residual(i))}</td></tr>")
    table.append("</table>")
    return {
        "cliente": html.escape(party.name), "azienda": html.escape(company.name if company else ""),
        "totale": eur(total), "elenco": "".join(table), "giorni": str(max((on - i.due_date).days for i in rows)),
        "iban": html.escape(company.iban) if company and company.iban else "indicato in fattura",
        "documenti": ", ".join(re.sub(r" – .*", "", i.description) for i in rows),
    }


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(template: str, ctx: dict) -> str:
    return template.format_map(_Safe(ctx))


def send(db: Session, tenant_id, party_id, level: int | None, on: date, user_id=None, automatic: bool = False) -> PaymentReminder:
    party = db.get(Party, party_id)
    rows = overdue_by_party(db, on, [party_id]).get(party_id, [])
    if not rows:
        raise due.fail(f"{party.name if party else 'Il cliente'} non ha scadenze scadute da sollecitare")
    level = level or min(max(max(i.reminder_level for i in rows) + 1, 1), 3)
    cfg = due.settings(db, tenant_id)
    tpl = cfg["templates"].get(str(level)) or due.DEFAULT_SETTINGS["templates"][str(level)]
    ctx = _context(db, party, rows, on)
    subject = re.sub(r"<[^>]+>", "", render(tpl["subject"], ctx))
    body = render(tpl["body"], ctx)
    to = [x for x in {(party.email or "").strip(), (party.pec or "").strip() if not party.email else ""} if x]
    r = PaymentReminder(tenant_id=tenant_id, party_id=party.id, level=level, channel="email", recipients=to, subject=subject[:200],
                        total=sum((due.residual(i) for i in rows), Decimal(0)), installment_ids=[i.id for i in rows],
                        automatic=automatic, sent_by=user_id)
    try:
        if not to:
            raise ValueError("Il cliente non ha un indirizzo email")
        wrapper = ("<div style='font-family:Arial,sans-serif;color:#1b2b45;max-width:620px;margin:auto;"
                   "border-top:4px solid #2340a8;padding:20px'>" + body + "</div>")
        mailer.send_email(to, subject, wrapper)
        r.status = "inviato"
        now = datetime.now(timezone.utc)
        for i in rows:
            i.reminder_level = max(i.reminder_level, level)
            i.last_reminder_at = now
    except Exception as exc:  # noqa: BLE001 - l'errore resta nel registro dei solleciti
        r.status, r.error = "errore", str(exc)[:500]
    db.add(r)
    db.flush()
    return r


def whatsapp(db: Session, tenant_id, party_id, level: int | None, on: date, user_id=None) -> dict:
    """Testo precompilato e link wa.me: l'invio lo conferma l'utente dal proprio WhatsApp."""
    party = db.get(Party, party_id)
    rows = overdue_by_party(db, on, [party_id]).get(party_id, [])
    if not rows:
        raise due.fail("Nessuna scadenza scaduta da sollecitare")
    level = level or min(max(max(i.reminder_level for i in rows) + 1, 1), 3)
    ctx = {k: html.unescape(v) for k, v in _context(db, party, rows, on).items() if k != "elenco"}
    text = render(due.settings(db, tenant_id)["whatsapp"], ctx)
    phone = re.sub(r"\D", "", party.mobile or party.phone or "")
    if phone and not phone.startswith("39") and len(phone) <= 10:
        phone = "39" + phone
    now = datetime.now(timezone.utc)
    for i in rows:
        i.reminder_level = max(i.reminder_level, level)
        i.last_reminder_at = now
    db.add(PaymentReminder(tenant_id=tenant_id, party_id=party.id, level=level, channel="whatsapp", recipients=[phone] if phone else [],
                           subject="WhatsApp", total=sum((due.residual(i) for i in rows), Decimal(0)),
                           installment_ids=[i.id for i in rows], sent_by=user_id))
    db.flush()
    return {"phone": phone or None, "text": text,
            "url": f"https://wa.me/{phone}?text={urllib.parse.quote(text)}" if phone else f"https://wa.me/?text={urllib.parse.quote(text)}"}


def run_automatic(db: Session, tenant_id, on: date) -> list[PaymentReminder]:
    """Invio automatico: per ogni cliente, il livello che i giorni di ritardo raggiungono e non è ancora stato inviato."""
    cfg = due.settings(db, tenant_id)
    if not cfg.get("auto"):
        return []
    sent = []
    for pid, rows in overdue_by_party(db, on).items():
        days = max((on - i.due_date).days for i in rows)
        target = target_level(days, cfg["days"])
        current = max(i.reminder_level for i in rows)
        if target > current:
            sent.append(send(db, tenant_id, pid, target, on, automatic=True))
    return sent


def run_all_tenants(session_factory, on: date) -> dict:
    """Job giornaliero: un'azienda per transazione."""
    from app.core.db import set_tenant
    from app.core.models import Tenant
    from app.saas.service import tenant_state

    db = session_factory()
    try:
        tenants = [t.id for t in db.scalars(select(Tenant))
                   if (st := tenant_state(t, on)).access == "full" and "scadenzario" in st.modules]
    finally:
        db.close()
    result = {}
    for tid in tenants:
        db = session_factory()
        try:
            set_tenant(db, tid)
            sent = run_automatic(db, tid, on)
            db.commit()
            if sent:
                result[str(tid)] = len(sent)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("Solleciti automatici: errore per l'azienda %s", tid)
            result[str(tid)] = "errore"
        finally:
            db.close()
    return result
