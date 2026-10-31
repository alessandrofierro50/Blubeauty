"""Prenotazione online PUBBLICA (/prenota/<slug>): il cliente prenota e disdice da solo dallo smartphone.

Nessun login: dallo slug (tabella di sistema `booking_pages`) si ricava l'azienda, si verifica che l'abbonamento
sia attivo e che il pacchetto includa l'agenda, poi si imposta il tenant per la RLS. Limiti di richieste per IP.
Il link personale dell'appuntamento contiene un token casuale lungo (non indovinabile).
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agenda import service as svc
from app.agenda.models import AgendaService, AgendaServiceCategory, AgendaStaff, Appointment, BookingPage
from app.anagrafiche.models import Party
from app.auth.passwords import rate_limit
from app.core.db import get_db, set_tenant
from app.saas.service import load_tenant, tenant_state

router = APIRouter(prefix="/api/prenota", tags=["prenotazione online"])


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def _open(db: Session, slug: str) -> uuid.UUID:
    page = db.get(BookingPage, slug.lower())
    if page is None:
        raise HTTPException(404, "Pagina di prenotazione non trovata")
    tenant = load_tenant(db, page.tenant_id)
    st = tenant_state(tenant) if tenant else None
    if st is None or st.access != "full" or "agenda" not in st.modules:
        raise HTTPException(404, "La prenotazione online di questo salone non è attiva")
    set_tenant(db, page.tenant_id)
    if not svc.settings(db, page.tenant_id).online_enabled:
        raise HTTPException(404, "La prenotazione online di questo salone non è attiva")
    return page.tenant_id


@router.get("/{slug}")
def page(slug: str, request: Request, db: Session = Depends(get_db)):
    rate_limit(f"prenota:pagina:{_ip(request)}", 120, 60)
    tid = _open(db, slug)
    from app.core.models import Company
    co = db.scalar(select(Company).order_by(Company.name))
    cfg = svc.settings(db, tid)
    cats = {c.id: c.name for c in db.scalars(select(AgendaServiceCategory))}
    order = {c.id: c.sort_order for c in db.scalars(select(AgendaServiceCategory))}
    services = db.scalars(select(AgendaService).where(AgendaService.active.is_(True), AgendaService.bookable_online.is_(True))
                          .order_by(AgendaService.sort_order, AgendaService.name)).all()
    staff = db.scalars(select(AgendaStaff).where(AgendaStaff.active.is_(True), AgendaStaff.bookable_online.is_(True))
                       .order_by(AgendaStaff.sort_order, AgendaStaff.first_name)).all()
    services = sorted(services, key=lambda x: (order.get(x.category_id, 999), x.sort_order, x.name))
    return {
        "name": svc.salon_name(db, tid), "slug": slug.lower(),
        "address": ", ".join(x for x in [co.address if co else None, co.city if co else None] if x),
        "phone": co.phone if co else None, "welcome_text": cfg.welcome_text, "cancel_hours": cfg.cancel_hours,
        "max_days": cfg.online_max_days, "opening_hours": cfg.opening_hours,
        "services": [{"id": str(x.id), "name": x.name, "description": x.description, "category": cats.get(x.category_id, "Altro"),
                      "price": str(x.price), "duration_min": x.duration_min,
                      "staff_ids": [str(link.staff_id) for link in x.staff_links]} for x in services],
        "staff": [{"id": str(st.id), "first_name": st.first_name, "color": st.color} for st in staff],
    }


@router.get("/{slug}/orari")
def slots(slug: str, service_id: uuid.UUID, day: date, request: Request, staff_id: uuid.UUID | None = None,
          db: Session = Depends(get_db)):
    rate_limit(f"prenota:orari:{_ip(request)}", 120, 60)
    tid = _open(db, slug)
    x = db.get(AgendaService, service_id)
    if x is None:
        raise HTTPException(404, "Servizio non trovato")
    return [s["time"] for s in svc.available_slots(db, tid, x, day, staff_id, online=True)]


class BookingIn(BaseModel):
    service_id: uuid.UUID
    staff_id: uuid.UUID | None = None
    day: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    phone: str = Field(min_length=6, max_length=30)
    privacy: bool
    marketing: bool = False
    notes: str | None = Field(None, max_length=500)
    website: str | None = None  # campo trappola per i bot (deve restare vuoto)


@router.post("/{slug}/prenotazioni", status_code=201)
def book(slug: str, body: BookingIn, request: Request, db: Session = Depends(get_db)):
    rate_limit(f"prenota:invio:{_ip(request)}", 10, 3600)
    if body.website:
        raise HTTPException(422, "Richiesta non valida")
    if not body.privacy:
        raise HTTPException(422, "Serve il consenso privacy per prenotare")
    tid = _open(db, slug)
    party = svc.client_by_phone(db, tid, body.first_name, body.last_name, body.phone, body.marketing)
    a = svc.book(db, tid, party=party, start=svc.at(body.day, body.time),
                 items=[{"service_id": body.service_id, "staff_id": body.staff_id}], channel="online", notes=body.notes,
                 created_by="Prenotazione online", online=True)
    return {"token": a.public_token, "url": svc.public_link(db, tid, a.public_token)}


def _by_token(db: Session, slug: str, token: str) -> tuple[uuid.UUID, Appointment]:
    tid = _open(db, slug)
    a = db.scalar(select(Appointment).where(Appointment.public_token == token))
    if a is None or a.tenant_id != tid:
        raise HTTPException(404, "Appuntamento non trovato")
    return tid, a


@router.get("/{slug}/a/{token}")
def my_appointment(slug: str, token: str, request: Request, db: Session = Depends(get_db)):
    rate_limit(f"prenota:link:{_ip(request)}", 60, 60)
    tid, a = _by_token(db, slug, token)
    party = db.get(Party, a.party_id) if a.party_id else None
    staff = {st.id: st.first_name for st in db.scalars(select(AgendaStaff))}
    return {"salon": svc.salon_name(db, tid), "client_first_name": party.first_name if party else None,
            "starts_at": a.starts_at.isoformat(), "ends_at": a.ends_at.isoformat(), "status": a.status,
            "can_cancel": svc.can_client_cancel(db, tid, a), "cancel_hours": svc.settings(db, tid).cancel_hours,
            "past": a.starts_at < datetime.now(svc.TZ),
            "items": [{"service": db.get(AgendaService, i.service_id).name, "staff": staff.get(i.staff_id),
                       "price": str(i.price)} for i in a.items],
            "total": str(sum((i.price for i in a.items), Decimal(0)))}


@router.post("/{slug}/a/{token}/disdici")
def cancel(slug: str, token: str, request: Request, db: Session = Depends(get_db)):
    rate_limit(f"prenota:disdetta:{_ip(request)}", 20, 3600)
    tid, a = _by_token(db, slug, token)
    svc.cancel(db, tid, a, by_client=True)
    return my_appointment(slug, token, request, db)
