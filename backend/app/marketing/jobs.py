"""Job pianificati dei messaggi automatici (Celery beat, vedi app/tasks/worker.py).

- Ogni ora: promemoria degli appuntamenti (modulo agenda), N ore prima, una sola volta per appuntamento.
- Ogni mattina: richiamo dopo il servizio, auguri di compleanno, clienti persi (modulo marketing, solo con consenso).
Ogni messaggio ha una `dedupe_key`: anche se il job gira due volte, al cliente arriva un solo messaggio.
"""

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agenda import service as agenda
from app.agenda.models import AgendaService, Appointment, AppointmentItem, ClientProfile
from app.anagrafiche.models import Party
from app.marketing import service as msg

log = logging.getLogger(__name__)


def reminders(db: Session, tenant_id, at: datetime | None = None) -> int:
    """Promemoria per gli appuntamenti che iniziano entro `offset` ore (prenotati almeno 12 ore prima)."""
    a = msg.automation(db, tenant_id, "promemoria")
    if not a.enabled:
        return 0
    at = at or agenda.now()
    hours = a.offset or 24
    rows = db.scalars(select(Appointment).where(
        Appointment.status.in_(("prenotato", "confermato")), Appointment.reminder_sent_at.is_(None),
        Appointment.starts_at > at, Appointment.starts_at <= at + timedelta(hours=hours))).all()
    sent = 0
    for appt in rows:
        appt.reminder_sent_at = at
        if appt.starts_at - appt.created_at < timedelta(hours=12):
            continue  # prenotato all'ultimo momento: basta la conferma
        party = db.get(Party, appt.party_id) if appt.party_id else None
        if msg.send_automatic(db, tenant_id, "promemoria", party, agenda.message_values(db, tenant_id, appt),
                              appointment_id=appt.id, dedupe_key=f"promemoria:{appt.id}"):
            sent += 1
    db.flush()
    return sent


def _consenting(db: Session) -> dict:
    return {p.party_id: p for p in db.scalars(select(ClientProfile).where(ClientProfile.marketing_consent_at.is_not(None)))}


def daily_marketing(db: Session, tenant_id, on: date) -> dict:
    out = {"richiamo": 0, "compleanno": 0, "clienti_persi": 0}
    consent = _consenting(db)
    link = agenda.public_link(db, tenant_id)
    salon = agenda.salon_name(db, tenant_id)
    base = {"salone": salon, "link": link}

    # compleanno (una volta l'anno)
    if msg.automation(db, tenant_id, "compleanno").enabled:
        for pid, prof in consent.items():
            if prof.birth_date and (prof.birth_date.month, prof.birth_date.day) == (on.month, on.day):
                if msg.send_automatic(db, tenant_id, "compleanno", db.get(Party, pid), base, dedupe_key=f"compleanno:{on.year}:{pid}"):
                    out["compleanno"] += 1

    # richiamo: N giorni dopo un servizio pagato (giorni del servizio o dell'automatico), se non ha già un appuntamento futuro
    auto = msg.automation(db, tenant_id, "richiamo")
    if auto.enabled:
        future = set(db.scalars(select(Appointment.party_id).where(Appointment.starts_at > agenda.now(),
                                                                   Appointment.status.in_(agenda.ACTIVE))))
        for svc in db.scalars(select(AgendaService).where(AgendaService.recall_days.is_not(None))):
            days = svc.recall_days or auto.offset or 35
            day0 = agenda.at(on - timedelta(days=days), "00:00")
            items = db.execute(select(AppointmentItem, Appointment.party_id).join(Appointment, Appointment.id == AppointmentItem.appointment_id)
                               .where(AppointmentItem.service_id == svc.id, Appointment.status == "pagato",
                                      AppointmentItem.starts_at >= day0, AppointmentItem.starts_at < day0 + timedelta(days=1))).all()
            for it, pid in items:
                if pid in consent and pid not in future:
                    vals = base | {"servizio": svc.name.lower(), "giorni": max(1, round(days / 7))}
                    if msg.send_automatic(db, tenant_id, "richiamo", db.get(Party, pid), vals, dedupe_key=f"richiamo:{it.id}"):
                        out["richiamo"] += 1

    # clienti persi: ultima visita esattamente `offset` giorni fa
    auto = msg.automation(db, tenant_id, "clienti_persi")
    if auto.enabled:
        days = auto.offset or 60
        last = db.execute(select(Appointment.party_id, func.max(Appointment.starts_at))
                          .where(Appointment.status.in_(("pagato", "concluso"))).group_by(Appointment.party_id)).all()
        for pid, when in last:
            if pid in consent and agenda.local(when).date() == on - timedelta(days=days):
                if msg.send_automatic(db, tenant_id, "clienti_persi", db.get(Party, pid), base,
                                      dedupe_key=f"clienti_persi:{pid}:{on.isoformat()}"):
                    out["clienti_persi"] += 1
    db.flush()
    return out


def _tenants(session_factory, on: date, module: str) -> list:
    from app.core.models import Tenant
    from app.saas.service import tenant_state
    db = session_factory()
    try:
        return [t.id for t in db.scalars(select(Tenant)) if (st := tenant_state(t, on)).access == "full" and module in st.modules]
    finally:
        db.close()


def _each(session_factory, on: date, module: str, fn) -> dict:
    from app.core.db import set_tenant
    result = {}
    for tid in _tenants(session_factory, on, module):
        db = session_factory()
        try:
            set_tenant(db, tid)
            r = fn(db, tid)
            db.commit()
            if r:
                result[str(tid)] = r
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("Messaggi automatici: errore per l'azienda %s", tid)
            result[str(tid)] = "errore"
        finally:
            db.close()
    return result


def run_reminders(session_factory, on: date) -> dict:
    return _each(session_factory, on, "agenda", lambda db, tid: reminders(db, tid))


def run_daily_marketing(session_factory, on: date) -> dict:
    return _each(session_factory, on, "marketing", lambda db, tid: daily_marketing(db, tid, on))


def prepaid_expiry(db: Session, tenant_id, on: date) -> int:
    """Buoni con credito e pacchetti con sedute che scadono entro N giorni (automatico «prepagato_scadenza»)."""
    from app.prepagati import service as pp
    from app.prepagati.models import ClientPackage, GiftVoucher
    a = msg.automation(db, tenant_id, "prepagato_scadenza")
    if not a.enabled:
        return 0
    until, n = on + timedelta(days=a.offset or 30), 0
    for v in db.scalars(select(GiftVoucher).where(GiftVoucher.status == "attivo", GiftVoucher.balance > 0,
                                                  GiftVoucher.expires_on.between(on, until))):
        party = pp.voucher_party(db, v)
        if party is not None and pp.notify(db, tenant_id, "prepagato_scadenza", party,
                                           {"cosa": f"il tuo buono regalo {v.code}", "data": v.expires_on.strftime("%d/%m/%Y"),
                                            "resta": f"hai ancora {pp.fmt_eur(v.balance)} € da usare"}, dedupe_key=f"scadenza:{v.id}"):
            n += 1
    cps = list(db.scalars(select(ClientPackage).where(ClientPackage.status == "attivo", ClientPackage.expires_on.between(on, until))))
    used = pp.used_counts(db, [c.id for c in cps])
    for cp in cps:
        left = sum(x["sessions"] - used.get((cp.id, x["service_id"]), 0) for x in cp.items)
        if left > 0 and pp.notify(db, tenant_id, "prepagato_scadenza", db.get(Party, cp.party_id),
                                  {"cosa": f"il tuo pacchetto «{cp.name}»", "data": cp.expires_on.strftime("%d/%m/%Y"),
                                   "resta": f"ti restano {left} sedute"}, dedupe_key=f"scadenza:{cp.id}"):
            n += 1
    return n


def run_prepaid_expiry(session_factory, on: date) -> dict:
    return _each(session_factory, on, "pos", lambda db, tid: prepaid_expiry(db, tid, on))
