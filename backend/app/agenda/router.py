"""API dell'agenda (modulo `agenda`): impostazioni, operatori, risorse, servizi, clienti, appuntamenti, incasso."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.agenda import service as svc
from app.agenda.models import (AgendaResource, AgendaService, AgendaServiceCategory, AgendaServiceResource,
                               AgendaServiceStaff, AgendaStaff, Appointment, ClientProfile, TechnicalCard)
from app.anagrafiche.models import Party
from app.core.deps import TenantContext, require_module
from app.marketing.models import Message

router = APIRouter(prefix="/api/agenda", tags=["agenda"])
reader = require_module("agenda")
STAFF_ROLES = ("amministratore", "amministrazione", "vendite", "cassa")


def writer(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può modificare l'agenda")
    return ctx


def admin(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role not in ("amministratore", "amministrazione"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo l'amministratore può modificare queste impostazioni")
    return ctx


def s(v):
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _get(ctx: TenantContext, model, obj_id):
    o = ctx.db.get(model, obj_id)
    if o is None:
        raise HTTPException(404, "Non trovato")
    return o


# ------------------------------------------------------------------------------------------------- impostazioni
class SettingsIn(BaseModel):
    salon_name: str = Field("", max_length=120)
    opening_hours: dict
    slot_minutes: int = Field(15, ge=5, le=60)
    online_enabled: bool = True
    online_lead_minutes: int = Field(60, ge=0, le=7 * 24 * 60)
    online_max_days: int = Field(60, ge=1, le=365)
    cancel_hours: int = Field(24, ge=0, le=7 * 24)
    welcome_text: str | None = Field(None, max_length=1000)
    register_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    slug: str | None = Field(None, max_length=60)


def _hours_ok(h: dict) -> dict:
    out = {}
    for k, ranges in (h or {}).items():
        if k not in svc.DAY_KEYS:
            raise HTTPException(422, f"Giorno non valido: {k}")
        clean = []
        for a, b in ranges or []:
            try:
                ta, tb = datetime.strptime(a, "%H:%M"), datetime.strptime(b, "%H:%M")
            except ValueError as exc:
                raise HTTPException(422, f"Orario non valido: {a}-{b}") from exc
            if tb <= ta:
                raise HTTPException(422, f"Orario non valido: {a}-{b}")
            clean.append([a, b])
        if clean:
            out[k] = clean
    return out


def settings_out(ctx: TenantContext) -> dict:
    c = svc.settings(ctx.db, ctx.tenant_id)
    page = svc.booking_page(ctx.db, ctx.tenant_id)
    return {"salon_name": c.salon_name, "display_name": svc.salon_name(ctx.db, ctx.tenant_id), "opening_hours": c.opening_hours,
            "slot_minutes": c.slot_minutes, "online_enabled": c.online_enabled, "online_lead_minutes": c.online_lead_minutes,
            "online_max_days": c.online_max_days, "cancel_hours": c.cancel_hours, "welcome_text": c.welcome_text,
            "register_id": s(c.register_id), "department_id": s(c.department_id), "slug": page.slug,
            "booking_url": svc.public_link(ctx.db, ctx.tenant_id)}


@router.get("/impostazioni")
def get_settings_(ctx: TenantContext = Depends(reader)):
    return settings_out(ctx)


@router.put("/impostazioni")
def put_settings(body: SettingsIn, ctx: TenantContext = Depends(admin)):
    c = svc.settings(ctx.db, ctx.tenant_id)
    data = body.model_dump(exclude={"slug"})
    data["opening_hours"] = _hours_ok(body.opening_hours)
    for k, v in data.items():
        setattr(c, k, v)
    if body.slug:
        svc.set_slug(ctx.db, ctx.tenant_id, body.slug)
    ctx.db.flush()
    return settings_out(ctx)


# ---------------------------------------------------------------------------------------------- operatori e risorse
class StaffIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=60)
    last_name: str = Field("", max_length=60)
    color: str = Field("#2340a8", pattern=r"^#[0-9a-fA-F]{6}$")
    active: bool = True
    bookable_online: bool = True
    sort_order: int = 0
    working_hours: dict = {}
    working_hours_b: dict = {}  # settimane alterne: orario della settimana B (vuoto = sempre uguale)
    alt_week_a: date | None = None  # un giorno di una settimana A
    user_id: uuid.UUID | None = None


def staff_out(st: AgendaStaff) -> dict:
    return {"id": str(st.id), "first_name": st.first_name, "last_name": st.last_name, "color": st.color, "active": st.active,
            "bookable_online": st.bookable_online, "sort_order": st.sort_order, "working_hours": st.working_hours or {},
            "working_hours_b": st.working_hours_b or {}, "alt_week_a": st.alt_week_a.isoformat() if st.alt_week_a else None,
            "user_id": s(st.user_id)}


def _staff_data(body: StaffIn) -> dict:
    data = body.model_dump() | {"working_hours": _hours_ok(body.working_hours), "working_hours_b": _hours_ok(body.working_hours_b)}
    if data["working_hours_b"] and not data["alt_week_a"]:
        raise HTTPException(422, "Settimane alterne: indica un giorno della settimana A")
    if not data["working_hours_b"]:
        data["alt_week_a"] = None
    return data


@router.get("/operatori")
def list_staff(ctx: TenantContext = Depends(reader)):
    return [staff_out(x) for x in ctx.db.scalars(select(AgendaStaff).order_by(AgendaStaff.sort_order, AgendaStaff.first_name))]


@router.post("/operatori", status_code=201)
def create_staff(body: StaffIn, ctx: TenantContext = Depends(admin)):
    st = AgendaStaff(tenant_id=ctx.tenant_id, **_staff_data(body))
    ctx.db.add(st)
    ctx.db.flush()
    return staff_out(st)


@router.put("/operatori/{staff_id}")
def update_staff(staff_id: uuid.UUID, body: StaffIn, ctx: TenantContext = Depends(admin)):
    st = _get(ctx, AgendaStaff, staff_id)
    for k, v in _staff_data(body).items():
        setattr(st, k, v)
    ctx.db.flush()
    return staff_out(st)


# ----------------------------------------------------------------------------------------------- turni e assenze
class AbsenceIn(BaseModel):
    staff_id: uuid.UUID | None = None  # vuoto = chiusura del salone
    kind: str = Field(pattern="^(ferie|malattia|permesso|orario|chiusura)$")
    date_from: date
    date_to: date
    hours: list[list[str]] = []
    note: str | None = Field(None, max_length=200)


def _ranges_ok(ranges: list) -> list:
    return _hours_ok({"mon": ranges}).get("mon", []) if ranges else []


@router.get("/turni")
def shifts(dal: date, giorni: int = Query(14, ge=1, le=62), ctx: TenantContext = Depends(reader)):
    """Turni effettivi per operatore e giorno (settimana, settimane alterne, ferie, permessi, chiusure) e assenze del periodo."""
    cfg = svc.settings(ctx.db, ctx.tenant_id)
    days = [dal + timedelta(days=i) for i in range(giorni)]
    absences = svc.absences_between(ctx.db, days[0], days[-1])
    staff = [x for x in ctx.db.scalars(select(AgendaStaff).order_by(AgendaStaff.sort_order, AgendaStaff.first_name)) if x.active]
    return {
        "days": [d.isoformat() for d in days],
        "staff": [staff_out(x) for x in staff],
        "plan": {str(st.id): {d.isoformat(): svc.day_plan(cfg, st, d, absences) for d in days} for st in staff},
        "closures": {d.isoformat(): next((svc.absence_out(a) for a in absences if a.staff_id is None and a.date_from <= d <= a.date_to), None)
                     for d in days},
        "absences": [svc.absence_out(a) for a in absences],
        "kinds": svc.ABSENCE_KINDS,
    }


@router.get("/orari")
def day_hours(giorno: date, ctx: TenantContext = Depends(reader)):
    """Orario effettivo di ogni operatore in un giorno, per l'agenda."""
    cfg = svc.settings(ctx.db, ctx.tenant_id)
    absences = svc.absences_between(ctx.db, giorno, giorno)
    return {str(st.id): svc.day_plan(cfg, st, giorno, absences) for st in ctx.db.scalars(select(AgendaStaff))}


@router.post("/turni/assenze", status_code=201)
def create_absence(body: AbsenceIn, ctx: TenantContext = Depends(admin)):
    ab = svc.save_absence(ctx.db, ctx.tenant_id, staff_id=body.staff_id, kind=body.kind, date_from=body.date_from,
                          date_to=body.date_to, hours=_ranges_ok(body.hours), note=body.note)
    return {"absence": svc.absence_out(ab), "conflicts": svc.absence_conflicts(ctx.db, ctx.tenant_id, ab)}


@router.put("/turni/assenze/{absence_id}")
def update_absence(absence_id: uuid.UUID, body: AbsenceIn, ctx: TenantContext = Depends(admin)):
    ab = svc.save_absence(ctx.db, ctx.tenant_id, staff_id=body.staff_id, kind=body.kind, date_from=body.date_from,
                          date_to=body.date_to, hours=_ranges_ok(body.hours), note=body.note, absence_id=absence_id)
    return {"absence": svc.absence_out(ab), "conflicts": svc.absence_conflicts(ctx.db, ctx.tenant_id, ab)}


@router.delete("/turni/assenze/{absence_id}", status_code=204)
def remove_absence(absence_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    svc.delete_absence(ctx.db, absence_id)


class ResourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field("cabina", pattern="^(cabina|postazione|lavatesta|macchinario)$")
    active: bool = True


@router.get("/risorse")
def list_resources(ctx: TenantContext = Depends(reader)):
    return [{"id": str(r.id), "name": r.name, "kind": r.kind, "active": r.active}
            for r in ctx.db.scalars(select(AgendaResource).order_by(AgendaResource.name))]


@router.post("/risorse", status_code=201)
def create_resource(body: ResourceIn, ctx: TenantContext = Depends(admin)):
    r = AgendaResource(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(r)
    ctx.db.flush()
    return {"id": str(r.id), **body.model_dump()}


@router.put("/risorse/{res_id}")
def update_resource(res_id: uuid.UUID, body: ResourceIn, ctx: TenantContext = Depends(admin)):
    r = _get(ctx, AgendaResource, res_id)
    for k, v in body.model_dump().items():
        setattr(r, k, v)
    return {"id": str(r.id), **body.model_dump()}


# ---------------------------------------------------------------------------------------------------- servizi
class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    sort_order: int = 0


@router.get("/categorie")
def list_categories(ctx: TenantContext = Depends(reader)):
    return [{"id": str(c.id), "name": c.name, "sort_order": c.sort_order}
            for c in ctx.db.scalars(select(AgendaServiceCategory).order_by(AgendaServiceCategory.sort_order, AgendaServiceCategory.name))]


@router.post("/categorie", status_code=201)
def create_category(body: CategoryIn, ctx: TenantContext = Depends(admin)):
    c = AgendaServiceCategory(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(c)
    ctx.db.flush()
    return {"id": str(c.id), **body.model_dump()}


class ServiceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    category_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=2000)
    price: Decimal = Field(ge=0)
    vat_rate_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    duration_min: int = Field(ge=5, le=600)
    processing_start_min: int | None = Field(None, ge=0)
    processing_min: int | None = Field(None, ge=0)
    bookable_online: bool = True
    active: bool = True
    sort_order: int = 0
    recall_days: int | None = Field(None, ge=1, le=365)
    staff_ids: list[uuid.UUID] = []
    resource_ids: list[uuid.UUID] = []


def service_out(x: AgendaService) -> dict:
    return {"id": str(x.id), "name": x.name, "category_id": s(x.category_id), "description": x.description, "price": s(x.price),
            "vat_rate_id": s(x.vat_rate_id), "department_id": s(x.department_id), "duration_min": x.duration_min,
            "processing_start_min": x.processing_start_min, "processing_min": x.processing_min,
            "bookable_online": x.bookable_online, "active": x.active, "sort_order": x.sort_order, "recall_days": x.recall_days,
            "staff_ids": [str(link.staff_id) for link in x.staff_links],
            "resource_ids": [str(link.resource_id) for link in x.resource_links]}


def _apply_service(ctx: TenantContext, x: AgendaService, body: ServiceIn) -> None:
    if body.processing_min and (body.processing_start_min or 0) + body.processing_min > body.duration_min:
        raise HTTPException(422, "Il tempo di posa deve stare dentro la durata del servizio")
    for k, v in body.model_dump(exclude={"staff_ids", "resource_ids"}).items():
        setattr(x, k, v)
    x.staff_links = [AgendaServiceStaff(tenant_id=ctx.tenant_id, staff_id=i) for i in dict.fromkeys(body.staff_ids)]
    x.resource_links = [AgendaServiceResource(tenant_id=ctx.tenant_id, resource_id=i) for i in dict.fromkeys(body.resource_ids)]


@router.get("/servizi")
def list_services(ctx: TenantContext = Depends(reader)):
    return [service_out(x) for x in ctx.db.scalars(select(AgendaService).order_by(AgendaService.sort_order, AgendaService.name))]


@router.post("/servizi", status_code=201)
def create_service(body: ServiceIn, ctx: TenantContext = Depends(admin)):
    x = AgendaService(tenant_id=ctx.tenant_id)
    _apply_service(ctx, x, body)
    ctx.db.add(x)
    ctx.db.flush()
    return service_out(x)


@router.put("/servizi/{service_id}")
def update_service(service_id: uuid.UUID, body: ServiceIn, ctx: TenantContext = Depends(admin)):
    x = _get(ctx, AgendaService, service_id)
    _apply_service(ctx, x, body)
    ctx.db.flush()
    return service_out(x)


# ------------------------------------------------------------------------------------------------------ clienti
class ClientIn(BaseModel):
    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    mobile: str | None = Field(None, max_length=40)
    email: str | None = Field(None, max_length=200)
    birth_date: date | None = None
    privacy: bool = True
    marketing: bool = False
    notes: str | None = None
    referred_by: uuid.UUID | None = None  # «porta un'amica»: chi l'ha presentata


def client_row(p: Party, prof: ClientProfile | None) -> dict:
    return {"id": str(p.id), "code": p.code, "name": p.name, "first_name": p.first_name, "last_name": p.last_name,
            "mobile": p.mobile or p.phone, "email": p.email, "tax_code": p.tax_code, "vat_number": p.vat_number,
            "address": p.address, "zip_code": p.zip_code, "city": p.city, "province": p.province, "sdi_code": p.sdi_code, "pec": p.pec,
            "privacy": bool(prof and prof.privacy_consent_at), "marketing": bool(prof and prof.marketing_consent_at),
            "privacy_at": s(prof.privacy_consent_at) if prof else None, "marketing_at": s(prof.marketing_consent_at) if prof else None,
            "birth_date": s(prof.birth_date) if prof else None, "loyalty_points": prof.loyalty_points if prof else 0,
            "notes": prof.notes if prof else None}


@router.get("/clienti")
def list_clients(q: str | None = None, limit: int = Query(100, le=500), ctx: TenantContext = Depends(reader)):
    stmt = (select(Party, ClientProfile).outerjoin(ClientProfile, ClientProfile.party_id == Party.id)
            .where(Party.is_customer.is_(True), Party.active.is_(True)).order_by(Party.name).limit(limit))
    if q and q.strip():
        t = f"%{q.strip()}%"
        stmt = stmt.where(or_(Party.name.ilike(t), Party.mobile.ilike(t), Party.phone.ilike(t), Party.email.ilike(t)))
    return [client_row(p, prof) for p, prof in ctx.db.execute(stmt).all()]


@router.post("/clienti", status_code=201)
def create_client(body: ClientIn, ctx: TenantContext = Depends(writer)):
    p = svc.new_client(ctx.db, ctx.tenant_id, body.first_name, body.last_name, body.mobile, body.email, body.privacy, body.marketing)
    prof = svc.profile(ctx.db, ctx.tenant_id, p)
    prof.birth_date, prof.notes = body.birth_date, body.notes
    if body.referred_by and ctx.db.get(Party, body.referred_by):
        prof.referred_by_party_id = body.referred_by
    ctx.db.flush()
    return client_row(p, prof)


class ConsentIn(BaseModel):
    referred_by: uuid.UUID | None = None
    privacy: bool | None = None
    marketing: bool | None = None
    birth_date: date | None = None
    notes: str | None = None


@router.patch("/clienti/{party_id}")
def update_client_profile(party_id: uuid.UUID, body: ConsentIn, ctx: TenantContext = Depends(writer)):
    p = _get(ctx, Party, party_id)
    prof = svc.profile(ctx.db, ctx.tenant_id, p)
    if body.privacy is not None:
        prof.privacy_consent_at = (prof.privacy_consent_at or svc.now()) if body.privacy else None
    if body.marketing is not None:
        prof.marketing_consent_at = (prof.marketing_consent_at or svc.now()) if body.marketing else None
    if "birth_date" in body.model_fields_set:
        prof.birth_date = body.birth_date
    if "notes" in body.model_fields_set:
        prof.notes = body.notes
    if "referred_by" in body.model_fields_set and body.referred_by != p.id:
        prof.referred_by_party_id = body.referred_by
    ctx.db.flush()
    return client_row(p, prof)


def card_out(c: TechnicalCard) -> dict:
    return {"id": str(c.id), "kind": c.kind, "title": c.title, "data": c.data, "notes": c.notes, "signed_at": s(c.signed_at),
            "created_at": s(c.created_at), "created_by": c.created_by}


@router.get("/clienti/{party_id}")
def client_detail(party_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    p = _get(ctx, Party, party_id)
    prof = ctx.db.scalar(select(ClientProfile).where(ClientProfile.party_id == p.id))
    cards = ctx.db.scalars(select(TechnicalCard).where(TechnicalCard.party_id == p.id).order_by(TechnicalCard.created_at.desc()))
    appts = ctx.db.scalars(select(Appointment).where(Appointment.party_id == p.id).order_by(Appointment.starts_at.desc()).limit(50))
    msgs = ctx.db.scalars(select(Message).where(Message.party_id == p.id).order_by(Message.created_at.desc()).limit(30))
    from app.marketing import loyalty
    loyalty_out = None
    if "marketing" in ctx.state.modules:
        pts = loyalty.balance(ctx.db, p.id)
        c = loyalty.card(ctx.db, p.id)
        moves = ctx.db.scalars(select(loyalty.LoyaltyMove).where(loyalty.LoyaltyMove.party_id == p.id)
                               .order_by(loyalty.LoyaltyMove.created_at.desc()).limit(20))
        ref = ctx.db.get(Party, prof.referred_by_party_id) if prof and prof.referred_by_party_id else None
        loyalty_out = {"points": pts, "card": c.number if c else None, "next": loyalty.next_reward(ctx.db, ctx.tenant_id, pts),
                       "referred_by": {"id": str(ref.id), "name": ref.name} if ref else None,
                       "rewards": [{"id": str(r.id), "name": r.name, "points": r.points, "available": r.points <= pts, "kind": r.kind,
                                     "value": r.value, "service_id": str(r.service_id) if r.service_id else None}
                                   for r in loyalty.rewards(ctx.db, ctx.tenant_id)],
                       "moves": [{"points": m.points, "reason": m.reason, "note": m.note, "created_at": s(m.created_at)} for m in moves]}
    return {**client_row(p, prof), "loyalty": loyalty_out, "cards": [card_out(c) for c in cards],
            "appointments": [appointment_out(ctx, a) for a in appts],
            "messages": [message_out(m) for m in reversed(list(msgs))]}


class CardIn(BaseModel):
    kind: str = Field(pattern="^(colore|trattamento|anamnesi|consenso)$")
    title: str = Field(min_length=1, max_length=120)
    data: dict = {}
    notes: str | None = None
    signed: bool = False


@router.post("/clienti/{party_id}/schede", status_code=201)
def add_card(party_id: uuid.UUID, body: CardIn, ctx: TenantContext = Depends(writer)):
    p = _get(ctx, Party, party_id)
    c = TechnicalCard(tenant_id=ctx.tenant_id, party_id=p.id, kind=body.kind, title=body.title,
                      data={str(k)[:60]: str(v)[:500] for k, v in body.data.items()}, notes=body.notes,
                      signed_at=svc.now() if body.signed else None, created_by=ctx.user.full_name)
    ctx.db.add(c)
    ctx.db.flush()
    return card_out(c)


# ------------------------------------------------------------------------------------------------- appuntamenti
def message_out(m: Message) -> dict:
    return {"id": str(m.id), "kind": m.kind, "channel": m.channel, "to": m.to, "body": m.body, "status": m.status,
            "inbound": m.inbound, "created_at": s(m.created_at), "error": m.error}


def appointment_out(ctx: TenantContext, a: Appointment, full: bool = False) -> dict:
    party = ctx.db.get(Party, a.party_id) if a.party_id else None
    items = []
    for i in a.items:
        x = ctx.db.get(AgendaService, i.service_id)
        items.append({"id": str(i.id), "service_id": str(i.service_id), "service": x.name, "staff_id": s(i.staff_id),
                      "resource_id": s(i.resource_id), "starts_at": s(i.starts_at), "ends_at": s(i.ends_at), "price": s(i.price),
                      "processing_start_min": i.processing_start_min, "processing_min": i.processing_min})
    out = {"id": str(a.id), "party_id": s(a.party_id), "client": party.name if party else None,
           "client_mobile": (party.mobile or party.phone) if party else None, "starts_at": s(a.starts_at), "ends_at": s(a.ends_at),
           "status": a.status, "channel": a.channel, "notes": a.notes, "document_id": s(a.document_id),
           "total": s(sum((i.price for i in a.items), Decimal(0))), "items": items}
    if full:
        out["messages"] = [message_out(m) for m in ctx.db.scalars(
            select(Message).where(Message.appointment_id == a.id).order_by(Message.created_at))]
        out["public_url"] = svc.public_link(ctx.db, ctx.tenant_id, a.public_token)
        if a.document_id:
            from app.documenti.models import Document
            d = ctx.db.get(Document, a.document_id)
            out["document"] = {"id": str(d.id), "doc_type": d.doc_type, "number": d.number, "date": s(d.doc_date),
                               "total": s(d.total), "rt": (d.fiscal or {}).get("rt")}
    return out


@router.get("/appuntamenti")
def list_appointments(day: date | None = None, days: int = Query(1, ge=1, le=31), party_id: uuid.UUID | None = None,
                      ctx: TenantContext = Depends(reader)):
    day = day or datetime.now(svc.TZ).date()
    start = svc.at(day, "00:00")
    stmt = (select(Appointment).where(Appointment.starts_at >= start, Appointment.starts_at < start + timedelta(days=days))
            .order_by(Appointment.starts_at))
    if party_id:
        stmt = stmt.where(Appointment.party_id == party_id)
    return [appointment_out(ctx, a) for a in ctx.db.scalars(stmt)]


@router.get("/disponibilita")
def slots(service_id: uuid.UUID, day: date, staff_id: uuid.UUID | None = None, ctx: TenantContext = Depends(reader)):
    x = _get(ctx, AgendaService, service_id)
    return svc.available_slots(ctx.db, ctx.tenant_id, x, day, staff_id, online=False)


class ItemIn(BaseModel):
    service_id: uuid.UUID
    staff_id: uuid.UUID | None = None
    price: Decimal | None = Field(None, ge=0)


class AppointmentIn(BaseModel):
    party_id: uuid.UUID | None = None
    day: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    items: list[ItemIn] = Field(min_length=1, max_length=10)
    channel: str = "salone"
    notes: str | None = Field(None, max_length=1000)
    force: bool = False  # inserisce anche se l'orario è occupato (solo amministratore)


@router.post("/appuntamenti", status_code=201)
def create_appointment(body: AppointmentIn, ctx: TenantContext = Depends(writer)):
    party = _get(ctx, Party, body.party_id) if body.party_id else None
    if body.force and ctx.user.role not in ("amministratore", "amministrazione"):
        raise HTTPException(403, "Solo l'amministratore può forzare un orario occupato")
    a = svc.book(ctx.db, ctx.tenant_id, party=party, start=svc.at(body.day, body.time),
                 items=[i.model_dump() for i in body.items], channel=body.channel, notes=body.notes,
                 created_by=ctx.user.full_name, check=not body.force)
    return appointment_out(ctx, a, full=True)


@router.get("/appuntamenti/{appt_id}")
def get_appointment(appt_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    return appointment_out(ctx, _get(ctx, Appointment, appt_id), full=True)


class StatusIn(BaseModel):
    status: str


@router.post("/appuntamenti/{appt_id}/stato")
def change_status(appt_id: uuid.UUID, body: StatusIn, ctx: TenantContext = Depends(writer)):
    a = _get(ctx, Appointment, appt_id)
    svc.set_status(ctx.db, a, body.status)
    return appointment_out(ctx, a, full=True)


class MoveIn(BaseModel):
    day: date
    time: str = Field(pattern=r"^\d{2}:\d{2}$")
    staff_id: uuid.UUID | None = None


@router.post("/appuntamenti/{appt_id}/sposta")
def move_appointment(appt_id: uuid.UUID, body: MoveIn, ctx: TenantContext = Depends(writer)):
    a = _get(ctx, Appointment, appt_id)
    svc.move(ctx.db, ctx.tenant_id, a, svc.at(body.day, body.time), body.staff_id)
    return appointment_out(ctx, a, full=True)


@router.post("/appuntamenti/{appt_id}/disdici")
def cancel_appointment(appt_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    a = _get(ctx, Appointment, appt_id)
    svc.cancel(ctx.db, ctx.tenant_id, a, by_client=False)
    return appointment_out(ctx, a, full=True)


class PaymentIn(BaseModel):
    method: str
    amount: Decimal


class ProductIn(BaseModel):
    item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: Decimal = Field(Decimal(1), gt=0)
    unit_price_gross: Decimal = Field(ge=0)


class CheckoutIn(BaseModel):
    register_id: uuid.UUID | None = None
    payments: list[PaymentIn] = Field(min_length=1)
    invoice: bool = False
    products: list[ProductIn] = []
    discount: Decimal | None = Field(None, ge=0)
    lottery_code: str | None = Field(None, max_length=8)
    rt_result: dict | None = None
    reward_id: uuid.UUID | None = None  # premio fedeltà riscattato
    nonfiscal_reason: str | None = Field(None, max_length=120)  # ricevuta non fiscale al posto dello scontrino


@router.post("/appuntamenti/{appt_id}/incassa")
def checkout(appt_id: uuid.UUID, body: CheckoutIn, ctx: TenantContext = Depends(writer)):
    """Incasso dalla cassa: documento commerciale sul registratore (BluBeauty Agent) o fattura già incassata."""
    if "pos" not in ctx.state.modules:
        raise HTTPException(403, {"code": "modulo_non_incluso", "module": "pos",
                                  "message": "La cassa con registratore telematico è nel pacchetto Salone."})
    a = _get(ctx, Appointment, appt_id)
    if body.invoice and a.party_id:  # dati di fatturazione: privati con codice fiscale, aziende con P.IVA
        p = ctx.db.get(Party, a.party_id)
        if not (p.tax_code or p.vat_number) or not (p.address and p.zip_code and p.city):
            raise HTTPException(422, {"code": "dati_fatturazione", "message":
                                      "Per la fattura completa codice fiscale (o P.IVA) e indirizzo del cliente."})
    d, change, replay = svc.checkout(
        ctx.db, ctx.tenant_id, a, ctx.user.id, register_id=body.register_id,
        payments=[{"method": p.method, "amount": str(p.amount)} for p in body.payments], invoice=body.invoice,
        products=[p.model_dump(mode="json") for p in body.products], discount=body.discount,
        lottery_code=body.lottery_code, rt_result=body.rt_result, marketing="marketing" in ctx.state.modules, reward_id=body.reward_id,
        nonfiscal_reason=body.nonfiscal_reason)
    from app.pos import service as pos
    return {"appointment": appointment_out(ctx, a, full=True), "receipt": pos.receipt_out(ctx.db, d),
            "change": s(change), "replayed": replay}


@router.get("/riepilogo")
def summary(ctx: TenantContext = Depends(reader)):
    """Numeri del giorno per la Home."""
    today = datetime.now(svc.TZ).date()
    start = svc.at(today, "00:00")
    appts = ctx.db.scalars(select(Appointment).where(Appointment.starts_at >= start,
                                                     Appointment.starts_at < start + timedelta(days=1))).all()
    live = [a for a in appts if a.status in svc.ACTIVE]
    since = svc.now() - timedelta(days=30)
    online = ctx.db.scalar(select(func.count()).select_from(Appointment).where(Appointment.channel == "online",
                                                                               Appointment.created_at >= since))
    return {"today": len(live), "expected": s(sum((i.price for a in live for i in a.items), Decimal(0))),
            "online_30": online or 0, "to_collect": len([a for a in live if a.status != "pagato"]),
            "booking_url": svc.public_link(ctx.db, ctx.tenant_id)}


# ---------------------------------------------------------------------------------------- ricevuta non fiscale
@router.get("/appuntamenti/{appt_id}/ricevuta")
def receipt_preview(appt_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    """Righe della ricevuta non fiscale (per l'anteprima e la stampa dal browser su una termica da 80 mm)."""
    from app.agenda import receipt
    return receipt.build(ctx.db, ctx.tenant_id, _get(ctx, Appointment, appt_id), "marketing" in ctx.state.modules)


class PrintIn(BaseModel):
    where: str = Field("termica", pattern="^(termica|registratore)$")
    register_id: uuid.UUID | None = None


@router.post("/appuntamenti/{appt_id}/ricevuta")
def receipt_print(appt_id: uuid.UUID, body: PrintIn, ctx: TenantContext = Depends(writer)):
    """Stampa la ricevuta NON fiscale sulla termica da 80 mm o sul registratore telematico (documento non fiscale),
    tramite BluBeauty Agent sul computer della cassa."""
    from app.agenda import receipt
    from app.periferiche import service as per
    from app.pos.models import PosRegister
    if "periferiche" not in ctx.state.modules:
        raise HTTPException(403, {"code": "modulo_non_incluso", "module": "periferiche",
                                  "message": "Stampanti e registratore sono nel pacchetto Salone."})
    a = _get(ctx, Appointment, appt_id)
    cfg = svc.settings(ctx.db, ctx.tenant_id)
    reg_id = body.register_id or cfg.register_id
    reg = ctx.db.get(PosRegister, reg_id) if reg_id else None
    if reg is None:
        raise HTTPException(422, "Scegli la cassa predefinita in Impostazioni agenda")
    dev = per.register_device(ctx.db, reg, "printer" if body.where == "termica" else "rt")
    if dev is None:
        raise HTTPException(422, "Alla cassa non è collegata una stampante termica" if body.where == "termica"
                            else "Alla cassa non è collegato un registratore telematico")
    payload = receipt.build(ctx.db, ctx.tenant_id, a, "marketing" in ctx.state.modules)
    job = per.enqueue(ctx.db, dev, "print.text" if body.where == "termica" else "rt.nonfiscal", payload,
                      document_id=a.document_id, user_id=ctx.user.id)
    return {"job_id": str(job.id), "device": dev.name}
