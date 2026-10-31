"""Agenda di BluBeauty: unico punto che scrive operatori, servizi, appuntamenti, schede clienti e pagine di prenotazione.

Regole principali
- Disponibilità: orari del salone (o dell'operatore), appuntamenti esistenti, risorse richieste (cabine/macchinari)
  e tempi di posa: durante la posa l'operatore è libero (può servire un altro cliente), la risorsa no.
- Prenotazione online: anticipo minimo e giorni massimi da `agenda_settings`; il cliente si riconosce dal cellulare.
- Disdetta del cliente dal link personale fino a `cancel_hours` ore prima; dopo deve chiamare il salone.
- Incasso: lo scontrino passa da `app.pos.service.create_sale` (documento commerciale sul registratore telematico
  tramite BluBeauty Agent) oppure, se si fattura, diventa una fattura già incassata (poi eventuale invio allo SDI
  con il modulo `fatturapa`). `client_uuid` deriva dall'appuntamento: un doppio clic non fa due scontrini.
"""

import re
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agenda.models import (AgendaResource, AgendaService, AgendaSettings, AgendaStaff, Appointment, AppointmentItem,
                               BookingPage, ClientProfile)
from app.anagrafiche.models import Party
from app.core.config import get_settings
from app.marketing import service as msg

TZ = ZoneInfo("Europe/Rome")
DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
ACTIVE = ("prenotato", "confermato", "arrivato", "concluso", "pagato")  # occupano l'agenda
STATUSES = ACTIVE + ("disdetto", "non_presentato")
DEFAULT_HOURS = {d: [["09:00", "19:30"]] for d in ("tue", "wed", "thu", "fri")} | {"sat": [["08:30", "18:00"]]}


def fail(msg_: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg_)


def now() -> datetime:
    return datetime.now(timezone.utc)


def local(d: datetime) -> datetime:
    return d.astimezone(TZ)


def at(day: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(h, m), TZ)


def fmt_time(d: datetime) -> str:
    return local(d).strftime("%H:%M")


MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
          "novembre", "dicembre"]
WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def fmt_date(d: datetime | date) -> str:
    x = local(d) if isinstance(d, datetime) else d
    return f"{WEEKDAYS[x.weekday()]} {x.day} {MONTHS[x.month - 1]}"


# --------------------------------------------------------------------------------------------- impostazioni e pagina
def settings(db: Session, tenant_id) -> AgendaSettings:
    s = db.get(AgendaSettings, tenant_id)
    if s is None:
        s = AgendaSettings(tenant_id=tenant_id, opening_hours=DEFAULT_HOURS, slot_minutes=15, online_enabled=True,
                           online_lead_minutes=60, online_max_days=60, cancel_hours=24, salon_name="")
        db.add(s)
        db.flush()
    return s


def salon_name(db: Session, tenant_id) -> str:
    s = settings(db, tenant_id)
    if s.salon_name:
        return s.salon_name
    from app.core.models import Company
    co = db.scalar(select(Company).order_by(Company.name))
    return co.name if co else "Il salone"


def slugify(text: str) -> str:
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:50] or "salone"


def booking_page(db: Session, tenant_id, create: bool = True) -> BookingPage | None:
    """Indirizzo pubblico della prenotazione (/prenota/<slug>), creato dal nome del salone alla prima richiesta."""
    p = db.scalar(select(BookingPage).where(BookingPage.tenant_id == tenant_id))
    if p is None and create:
        base = slugify(salon_name(db, tenant_id))
        slug, n = base, 1
        while db.get(BookingPage, slug) is not None:
            n += 1
            slug = f"{base}-{n}"
        p = BookingPage(slug=slug, tenant_id=tenant_id)
        db.add(p)
        db.flush()
    return p


def set_slug(db: Session, tenant_id, slug: str) -> BookingPage:
    slug = slugify(slug)
    if len(slug) < 3:
        raise fail("L'indirizzo deve avere almeno 3 caratteri")
    other = db.get(BookingPage, slug)
    if other is not None and other.tenant_id != tenant_id:
        raise fail("Questo indirizzo è già usato da un altro salone", status.HTTP_409_CONFLICT)
    cur = booking_page(db, tenant_id, create=False)
    if cur is not None and cur.slug != slug:
        db.delete(cur)
        db.flush()
    if cur is None or cur.slug != slug:
        cur = BookingPage(slug=slug, tenant_id=tenant_id)
        db.add(cur)
        db.flush()
    return cur


def public_link(db: Session, tenant_id, token: str | None = None) -> str:
    base = get_settings().public_url.rstrip("/")
    slug = booking_page(db, tenant_id).slug
    return f"{base}/prenota/{slug}" + (f"/a/{token}" if token else "")


# --------------------------------------------------------------------------------------------------- disponibilità
@dataclass
class Shape:
    duration_min: int
    processing_start_min: int | None = None
    processing_min: int | None = None


def staff_segments(start: datetime, s: Shape) -> list[tuple[datetime, datetime]]:
    """Intervalli in cui l'operatore è impegnato: il tempo di posa resta libero."""
    end = start + timedelta(minutes=s.duration_min)
    if s.processing_start_min is None or not s.processing_min:
        return [(start, end)]
    p0 = start + timedelta(minutes=s.processing_start_min)
    p1 = p0 + timedelta(minutes=s.processing_min)
    return [seg for seg in ((start, p0), (p1, end)) if seg[1] > seg[0]]


def _overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _windows(hours: dict, day: date) -> list[tuple[datetime, datetime]]:
    return [(at(day, a), at(day, b)) for a, b in (hours or {}).get(DAY_KEYS[day.weekday()], [])]


def _busy(db: Session, day_start: datetime, day_end: datetime, exclude_id=None):
    stmt = (select(AppointmentItem, Appointment.status)
            .join(Appointment, Appointment.id == AppointmentItem.appointment_id)
            .where(AppointmentItem.starts_at < day_end, AppointmentItem.ends_at > day_start, Appointment.status.in_(ACTIVE)))
    if exclude_id:
        stmt = stmt.where(Appointment.id != exclude_id)
    by_staff: dict = {}
    by_res: dict = {}
    for it, _st in db.execute(stmt).all():
        if it.staff_id:
            minutes = int((it.ends_at - it.starts_at).total_seconds() // 60)
            by_staff.setdefault(it.staff_id, []).extend(
                staff_segments(it.starts_at, Shape(minutes, it.processing_start_min, it.processing_min)))
        if it.resource_id:
            by_res.setdefault(it.resource_id, []).append((it.starts_at, it.ends_at))
    return by_staff, by_res


def _eligible_staff(db: Session, service: AgendaService, staff_id=None, online: bool = False) -> list[AgendaStaff]:
    ids = {link.staff_id for link in service.staff_links}
    q = select(AgendaStaff).where(AgendaStaff.active.is_(True)).order_by(AgendaStaff.sort_order, AgendaStaff.first_name)
    out = [s for s in db.scalars(q) if s.id in ids and (staff_id is None or s.id == staff_id)]
    return [s for s in out if s.bookable_online] if online else out


def _free_resource(service: AgendaService, by_res: dict, seg: tuple) -> uuid.UUID | None | bool:
    """Id della risorsa libera, None se il servizio non ne richiede, False se sono tutte occupate."""
    if not service.resource_links:
        return None
    for link in service.resource_links:
        if not any(_overlap(b, seg) for b in by_res.get(link.resource_id, [])):
            return link.resource_id
    return False


def _staff_free(db, cfg, st: AgendaStaff, day: date, segs: list, whole: tuple, by_staff: dict) -> bool:
    hours = st.working_hours or cfg.opening_hours
    if not any(w[0] <= whole[0] and whole[1] <= w[1] for w in _windows(hours, day)):
        return False
    return not any(_overlap(b, s) for b in by_staff.get(st.id, []) for s in segs)


def available_slots(db: Session, tenant_id, service: AgendaService, day: date, staff_id=None, online: bool = False,
                    exclude_appointment_id=None) -> list[dict]:
    cfg = settings(db, tenant_id)
    if online:
        if not cfg.online_enabled or not service.bookable_online or not service.active:
            return []
        today = datetime.now(TZ).date()
        if day < today or day > today + timedelta(days=cfg.online_max_days):
            return []
    staff = _eligible_staff(db, service, staff_id, online)
    if not staff:
        return []
    day_start, day_end = at(day, "00:00"), at(day, "00:00") + timedelta(days=1)
    by_staff, by_res = _busy(db, day_start, day_end, exclude_appointment_id)
    earliest = now() + timedelta(minutes=cfg.online_lead_minutes if online else 0)
    step = timedelta(minutes=max(5, cfg.slot_minutes or 15))
    shape = Shape(service.duration_min, service.processing_start_min, service.processing_min)
    hours_union = []
    for st in staff:
        hours_union += _windows(st.working_hours or cfg.opening_hours, day)
    if not hours_union:
        return []
    first, last = min(w[0] for w in hours_union), max(w[1] for w in hours_union)
    out, t = [], first
    while t + timedelta(minutes=service.duration_min) <= last:
        whole = (t, t + timedelta(minutes=service.duration_min))
        if t >= earliest and _free_resource(service, by_res, whole) is not False:
            segs = staff_segments(t, shape)
            free = [str(st.id) for st in staff if _staff_free(db, cfg, st, day, segs, whole, by_staff)]
            if free:
                out.append({"time": fmt_time(t), "staff_ids": free})
        t += step
    return out


# ------------------------------------------------------------------------------------------------------ clienti
def profile(db: Session, tenant_id, party: Party) -> ClientProfile:
    p = db.scalar(select(ClientProfile).where(ClientProfile.party_id == party.id))
    if p is None:
        p = ClientProfile(tenant_id=tenant_id, party_id=party.id, loyalty_points=0)
        db.add(p)
        db.flush()
    return p


def new_client(db: Session, tenant_id, first_name: str, last_name: str, phone: str | None, email: str | None = None,
               privacy: bool = True, marketing: bool = False) -> Party:
    from app.anagrafiche.router import next_code
    party = Party(tenant_id=tenant_id, code=next_code(db, Party, "CL"), is_customer=True, person_type="privato",
                  first_name=first_name.strip()[:80], last_name=last_name.strip()[:80],
                  name=f"{last_name.strip()} {first_name.strip()}"[:200], mobile=(phone or "").strip()[:40] or None,
                  email=(email or "").strip()[:200] or None, country="IT", custom={}, active=True)
    db.add(party)
    db.flush()
    p = profile(db, tenant_id, party)
    p.privacy_consent_at = now() if privacy else None
    p.marketing_consent_at = now() if marketing else None
    db.flush()
    return party


def client_by_phone(db: Session, tenant_id, first_name: str, last_name: str, phone: str, marketing: bool) -> Party:
    """Prenotazione online: il cliente si riconosce dal cellulare; se è nuovo si crea l'anagrafica."""
    norm = msg.normalize_phone(phone)
    if not norm:
        raise fail("Numero di cellulare non valido")
    for party in db.scalars(select(Party).where(Party.is_customer.is_(True), (Party.mobile.is_not(None)) | (Party.phone.is_not(None)))):
        if norm in (msg.normalize_phone(party.mobile), msg.normalize_phone(party.phone)):
            prof = profile(db, tenant_id, party)
            prof.privacy_consent_at = prof.privacy_consent_at or now()
            if marketing and prof.marketing_consent_at is None:
                prof.marketing_consent_at = now()
            return party
    return new_client(db, tenant_id, first_name, last_name, norm, privacy=True, marketing=marketing)


# -------------------------------------------------------------------------------------------------- appuntamenti
def _service(db: Session, service_id) -> AgendaService:
    s = db.get(AgendaService, uuid.UUID(str(service_id)))
    if s is None or not s.active:
        raise fail("Servizio non trovato")
    return s


def book(db: Session, tenant_id, *, party: Party | None, start: datetime, items: list[dict], channel: str,
         notes: str | None = None, created_by: str | None = None, online: bool = False, check: bool = True) -> Appointment:
    """Crea l'appuntamento. `items` = [{"service_id", "staff_id"?}] in sequenza dall'orario di inizio.

    Ogni servizio verifica operatore (fuori dalla posa) e risorsa liberi; senza operatore indicato prende il primo libero.
    """
    if not items:
        raise fail("Scegli almeno un servizio")
    if channel not in ("salone", "online", "telefono", "whatsapp"):
        raise fail("Canale non valido")
    cfg = settings(db, tenant_id)
    day = local(start).date()
    by_staff, by_res = _busy(db, at(day, "00:00"), at(day, "00:00") + timedelta(days=2))
    appt = Appointment(tenant_id=tenant_id, party_id=party.id if party else None, starts_at=start, ends_at=start,
                       status="confermato" if online else "prenotato", channel=channel, notes=(notes or None),
                       public_token=secrets.token_urlsafe(24), created_by=created_by)
    t = start
    names = []
    for it in items:
        svc = _service(db, it["service_id"])
        shape = Shape(svc.duration_min, svc.processing_start_min, svc.processing_min)
        whole = (t, t + timedelta(minutes=svc.duration_min))
        segs = staff_segments(t, shape)
        wanted = uuid.UUID(str(it["staff_id"])) if it.get("staff_id") else None
        staff = _eligible_staff(db, svc, wanted, online)
        if wanted and not staff:
            raise fail("Questo operatore non esegue il servizio scelto")
        chosen = next((s for s in staff if not check or _staff_free(db, cfg, s, day, segs, whole, by_staff)), None)
        if chosen is None:
            raise fail(f"{svc.name}: l'orario delle {fmt_time(t)} non è più disponibile", status.HTTP_409_CONFLICT)
        res = _free_resource(svc, by_res, whole)
        if res is False:
            if check:
                raise fail(f"{svc.name}: nessuna cabina libera alle {fmt_time(t)}", status.HTTP_409_CONFLICT)
            res = svc.resource_links[0].resource_id
        if check and online and t < now() + timedelta(minutes=cfg.online_lead_minutes):
            raise fail("Orario troppo vicino: scegline uno più avanti", status.HTTP_409_CONFLICT)
        price = Decimal(str(it["price"])) if it.get("price") not in (None, "") else svc.price
        appt.items.append(AppointmentItem(tenant_id=tenant_id, service_id=svc.id, staff_id=chosen.id, resource_id=res or None,
                                          starts_at=whole[0], ends_at=whole[1], price=price,
                                          processing_start_min=svc.processing_start_min, processing_min=svc.processing_min))
        by_staff.setdefault(chosen.id, []).extend(segs)  # i servizi successivi dello stesso appuntamento lo vedono occupato
        if res:
            by_res.setdefault(res, []).append(whole)
        names.append(svc.name)
        t = whole[1]
    appt.ends_at = t
    db.add(appt)
    db.flush()
    if party is not None:
        msg.send_automatic(db, tenant_id, "conferma", party, message_values(db, tenant_id, appt, ", ".join(names)),
                           appointment_id=appt.id, dedupe_key=f"conferma:{appt.id}")
    return appt


def service_names(db: Session, appt: Appointment) -> str:
    return ", ".join(db.get(AgendaService, i.service_id).name for i in appt.items)


def message_values(db: Session, tenant_id, appt: Appointment, services: str | None = None) -> dict:
    return {"salone": salon_name(db, tenant_id), "data": fmt_date(appt.starts_at), "ora": fmt_time(appt.starts_at),
            "servizio": services if services is not None else service_names(db, appt),
            "link": public_link(db, tenant_id, appt.public_token)}


def can_client_cancel(db: Session, tenant_id, appt: Appointment) -> bool:
    cfg = settings(db, tenant_id)
    return appt.status in ("prenotato", "confermato") and now() < appt.starts_at - timedelta(hours=cfg.cancel_hours)


def cancel(db: Session, tenant_id, appt: Appointment, by_client: bool) -> Appointment:
    if appt.status == "disdetto":
        return appt
    if appt.status not in ("prenotato", "confermato", "arrivato"):
        raise fail("Questo appuntamento non si può più disdire", status.HTTP_409_CONFLICT)
    if by_client and not can_client_cancel(db, tenant_id, appt):
        cfg = settings(db, tenant_id)
        raise fail(f"La disdetta online è possibile fino a {cfg.cancel_hours} ore prima: chiama il salone.",
                   status.HTTP_409_CONFLICT)
    appt.status, appt.cancelled_at, appt.cancelled_by = "disdetto", now(), "cliente" if by_client else "salone"
    db.flush()
    party = db.get(Party, appt.party_id) if appt.party_id else None
    values = message_values(db, tenant_id, appt) | {"link": public_link(db, tenant_id)}
    msg.send_automatic(db, tenant_id, "disdetta", party, values, appointment_id=appt.id, dedupe_key=f"disdetta:{appt.id}")
    return appt


TRANSITIONS = {
    "prenotato": {"confermato", "arrivato", "non_presentato"},
    "confermato": {"arrivato", "non_presentato", "prenotato"},
    "arrivato": {"concluso", "confermato"},
    "concluso": {"arrivato"},
}


def set_status(db: Session, appt: Appointment, new: str) -> Appointment:
    if new not in TRANSITIONS.get(appt.status, set()):
        raise fail(f"Da «{appt.status}» non si passa a «{new}»", status.HTTP_409_CONFLICT)
    appt.status = new
    db.flush()
    return appt


def move(db: Session, tenant_id, appt: Appointment, start: datetime, staff_id=None) -> Appointment:
    """Sposta l'appuntamento (stessi servizi), verificando di nuovo la disponibilità."""
    if appt.status not in ("prenotato", "confermato"):
        raise fail("Si spostano solo gli appuntamenti non ancora iniziati", status.HTTP_409_CONFLICT)
    items = [{"service_id": i.service_id, "staff_id": staff_id or i.staff_id, "price": i.price} for i in appt.items]
    old = list(appt.items)
    for i in old:
        appt.items.remove(i)
    db.flush()
    try:
        cfg = settings(db, tenant_id)
        day = local(start).date()
        by_staff, by_res = _busy(db, at(day, "00:00"), at(day, "00:00") + timedelta(days=2), exclude_id=appt.id)
        t = start
        for it in items:
            svc = _service(db, it["service_id"])
            whole = (t, t + timedelta(minutes=svc.duration_min))
            segs = staff_segments(t, Shape(svc.duration_min, svc.processing_start_min, svc.processing_min))
            st = db.get(AgendaStaff, it["staff_id"]) if it["staff_id"] else None
            if st is None or not _staff_free(db, cfg, st, day, segs, whole, by_staff):
                raise fail(f"{svc.name}: operatore non libero alle {fmt_time(t)}", status.HTTP_409_CONFLICT)
            res = _free_resource(svc, by_res, whole)
            if res is False:
                raise fail(f"{svc.name}: nessuna cabina libera alle {fmt_time(t)}", status.HTTP_409_CONFLICT)
            appt.items.append(AppointmentItem(tenant_id=tenant_id, service_id=svc.id, staff_id=st.id, resource_id=res or None,
                                              starts_at=whole[0], ends_at=whole[1], price=it["price"],
                                              processing_start_min=svc.processing_start_min, processing_min=svc.processing_min))
            by_staff.setdefault(st.id, []).extend(segs)
            t = whole[1]
        appt.starts_at, appt.ends_at = start, t
        appt.reminder_sent_at = None
        db.flush()
    except HTTPException:
        db.rollback()
        raise
    return appt


# ---------------------------------------------------------------------------------------------------------- cassa
def checkout(db: Session, tenant_id, appt: Appointment, user_id, *, register_id, payments: list[dict],
             invoice: bool = False, products: list[dict] | None = None, discount: Decimal | None = None,
             lottery_code: str | None = None, rt_result: dict | None = None, marketing: bool = False, reward_id=None):
    """Incasso dell'appuntamento dalla cassa: scontrino (documento commerciale sul registratore) o fattura."""
    from app.documenti.models import Document
    from app.pos import service as pos
    from app.pos.models import PosRegister

    if appt.document_id:
        d = db.get(Document, appt.document_id)
        return d, Decimal(str((d.fiscal or {}).get("change") or 0)), True
    if appt.status in ("disdetto", "non_presentato"):
        raise fail("L'appuntamento è stato disdetto", status.HTTP_409_CONFLICT)
    cfg = settings(db, tenant_id)
    reg = db.get(PosRegister, uuid.UUID(str(register_id))) if register_id else (db.get(PosRegister, cfg.register_id) if cfg.register_id else None)
    if reg is None:
        raise fail("Scegli la cassa (Impostazioni › Agenda › Cassa predefinita)")
    party = db.get(Party, appt.party_id) if appt.party_id else None
    if invoice and party is None:
        raise fail("Per la fattura serve il cliente")
    from app.marketing import loyalty
    reward = loyalty.check_redeem(db, tenant_id, party, reward_id) if reward_id and marketing else None
    total_discount = Decimal(str(discount or 0))
    if reward is not None:
        services_total = sum((i.price for i in appt.items), Decimal(0))
        total_discount += loyalty.reward_discount(db, reward, services_total - total_discount,
                                                  {i.service_id: i.price for i in appt.items})
    if total_discount > 0:
        apply_discount(appt, total_discount)
    lines = []
    for it in appt.items:
        svc = db.get(AgendaService, it.service_id)
        dep = svc.department_id or cfg.department_id
        lines.append({"description": svc.name, "quantity": "1", "unit_price_gross": str(it.price),
                      "vat_rate_id": str(svc.vat_rate_id) if svc.vat_rate_id else None,
                      "department_id": str(dep) if dep else None, "price_source": "Agenda"})
    for p in products or []:
        lines.append({"item_id": str(p["item_id"]), "variant_id": p.get("variant_id"), "quantity": str(p.get("quantity") or 1),
                      "unit_price_gross": str(p["unit_price_gross"]), "price_source": "Agenda"})
    body = {
        "client_uuid": str(uuid.uuid5(uuid.NAMESPACE_URL, f"blubeauty:appuntamento:{appt.id}")),
        "lines": lines,
        "payments": payments,
        "customer_id": str(party.id) if party else None,
        "invoice_party_id": str(party.id) if invoice else None,
        "lottery_code": lottery_code,
        "rt_result": rt_result,
    }
    d, change, replay = pos.create_sale(db, reg, user_id, body)
    appt.document_id, appt.status = d.id, "pagato"
    if party is not None and not replay and marketing:
        before = loyalty.balance(db, party.id)
        if reward is not None:
            loyalty.add(db, tenant_id, party, -reward.points, "premio", dedupe_key=f"premio:{appt.id}", reward_id=reward.id,
                        appointment_id=appt.id, document_id=d.id, note=reward.name)
        loyalty.earn_on_payment(db, tenant_id, party, Decimal(str(d.total)), appointment_id=appt.id, document_id=d.id)
        after = loyalty.balance(db, party.id)
        crossed = [r for r in loyalty.rewards(db, tenant_id) if before - (reward.points if reward else 0) < r.points <= after]
        if crossed:
            msg.send_automatic(db, tenant_id, "premio", party,
                               {"salone": salon_name(db, tenant_id), "punti": after, "premio": crossed[-1].name,
                                "link": public_link(db, tenant_id)}, appointment_id=appt.id, dedupe_key=f"premio:{appt.id}")
        ms = msg.settings(db, tenant_id)
        msg.send_automatic(db, tenant_id, "grazie", party,
                           {"salone": salon_name(db, tenant_id), "recensione": ms.review_url or public_link(db, tenant_id)},
                           appointment_id=appt.id, dedupe_key=f"grazie:{appt.id}")
    db.flush()
    return d, change, replay


def apply_discount(appt: Appointment, discount: Decimal) -> None:
    """Sconto sul totale ripartito in proporzione sui prezzi dei servizi (al centesimo, il resto sull'ultimo)."""
    total = sum((i.price for i in appt.items), Decimal(0))
    discount = min(Decimal(str(discount)), total)
    if discount <= 0 or total <= 0:
        return
    left = discount
    for n, it in enumerate(appt.items):
        cut = left if n == len(appt.items) - 1 else (it.price * discount / total).quantize(Decimal("0.01"))
        it.price -= cut
        left -= cut
