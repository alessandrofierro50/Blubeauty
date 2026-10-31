"""API tentata vendita: /api/tentata/...  (modulo extra "tentata_vendita").

Ruoli: l'agente vede e usa solo il proprio furgone e i propri giri e non vede i costi; amministrazione e vendite
pianificano furgoni e giri; il magazzino carica e verifica i rientri."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.anagrafiche.models import Party
from app.core.config import get_settings
from app.core.db import new_session, set_tenant
from app.core.deps import TenantContext, require_module
from app.core.models import User
from app.documenti.models import Document
from app.saas.service import audit
from app.tentata import pdf
from app.tentata import service as tv
from app.tentata.models import Van, VanCollection, VanRouteStop, VanTrip

router = APIRouter(prefix="/api/tentata", tags=["tentata vendita"])
public = APIRouter(prefix="/api/tentata", tags=["tentata vendita"])
module = require_module("tentata_vendita")
PLANNERS = ("amministratore", "amministrazione", "vendite")
WAREHOUSE = ("amministratore", "amministrazione", "magazzino")


def user(ctx: TenantContext = Depends(module)) -> TenantContext:
    if ctx.user.role in ("cassa", "contabilita"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non usa la tentata vendita")
    return ctx


def planner(ctx: TenantContext = Depends(module)) -> TenantContext:
    if ctx.user.role not in PLANNERS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo amministrazione e vendite gestiscono furgoni e giri")
    return ctx


def is_agent(ctx: TenantContext) -> bool:
    return ctx.user.role == "agente"


def _van(ctx: TenantContext, van_id) -> Van:
    v = ctx.db.get(Van, van_id)
    if v is None or (is_agent(ctx) and v.agent_id != ctx.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Furgone non trovato")
    return v


def _trip(ctx: TenantContext, trip_id) -> VanTrip:
    t = ctx.db.get(VanTrip, trip_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Giro non trovato")
    _van(ctx, t.van_id)
    return t


def _can(ctx: TenantContext, roles: tuple, msg: str) -> None:
    if ctx.user.role not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg)


# ====================================================================== furgoni e giro clienti


class VanIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=60)
    vehicle: str | None = Field(None, max_length=60)
    plate: str | None = Field(None, max_length=12)
    series: str = Field(min_length=1, max_length=10)
    warehouse_id: uuid.UUID | None = None
    home_warehouse_id: uuid.UUID | None = None
    agent_id: uuid.UUID | None = None
    max_discount: Decimal = Field(Decimal(0), ge=0, le=100)
    allowed_docs: list[str] = ["DDT", "FTI", "ORC", "NC"]
    cash_account_id: uuid.UUID | None = None
    blind_count: bool = True
    active: bool = True
    notes: str | None = None


@router.get("/furgoni")
def list_vans(ctx: TenantContext = Depends(user)):
    q = select(Van).order_by(Van.code)
    if is_agent(ctx):
        q = q.where(Van.agent_id == ctx.user.id)
    out = []
    for v in ctx.db.scalars(q):
        o = tv.van_out(ctx.db, v)
        open_trip = ctx.db.scalar(select(VanTrip).where(VanTrip.van_id == v.id, VanTrip.status != "chiuso").order_by(VanTrip.trip_date.desc()))
        o["open_trip"] = tv.trip_out(ctx.db, open_trip, brief=True) if open_trip else None
        o["route_count"] = len(tv.route_for(ctx.db, v))
        out.append(o)
    return out


@router.get("/opzioni")
def options(ctx: TenantContext = Depends(user)):
    """Dati per i moduli dell'ufficio: agenti, magazzini, conti cassa, tipi di documento, motivi delle differenze."""
    from app.core.models import Warehouse
    from app.scadenzario.models import FinancialAccount
    return {
        "agents": [{"value": str(u.id), "label": u.full_name, "role": u.role} for u in ctx.db.scalars(
            select(User).where(User.active, User.role.in_(("agente", "vendite"))).order_by(User.full_name))],
        "warehouses": [{"value": str(w.id), "label": f"{w.code} · {w.name}"} for w in ctx.db.scalars(select(Warehouse).order_by(Warehouse.code))],
        "accounts": [{"value": str(a.id), "label": a.name, "kind": a.kind} for a in ctx.db.scalars(
            select(FinancialAccount).where(FinancialAccount.active).order_by(FinancialAccount.name))],
        "doc_kinds": [{"value": k, "label": v} for k, v in tv.DOC_KINDS.items()],
        "reasons": [{"value": k, "label": v} for k, v in tv.REASONS.items()],
        "methods": [{"value": k, "label": v[0]} for k, v in tv.METHODS.items()],
        "weekdays": tv.WEEKDAYS,
    }


@router.post("/furgoni", status_code=201)
def create_van(body: VanIn, ctx: TenantContext = Depends(planner)):
    v = tv.create_van(ctx.db, ctx.tenant_id, body.model_dump(mode="json"))
    audit(ctx.db, "furgone", "creato", v.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after={"code": v.code})
    return tv.van_out(ctx.db, v)


@router.get("/furgoni/{van_id}")
def get_van(van_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    v = _van(ctx, van_id)
    return {**tv.van_out(ctx.db, v), "stock": tv.van_stock(ctx.db, v)}


@router.put("/furgoni/{van_id}")
def update_van(van_id: uuid.UUID, body: VanIn, ctx: TenantContext = Depends(planner)):
    v = _van(ctx, van_id)
    data = body.model_dump(mode="json", exclude={"code", "series", "warehouse_id"})
    tv.update_van(ctx.db, v, data)
    return tv.van_out(ctx.db, v)


class RouteStopIn(BaseModel):
    party_id: uuid.UUID
    weekdays: list[int] = []
    notes: str | None = None


@router.get("/furgoni/{van_id}/giro-clienti")
def get_route(van_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    v = _van(ctx, van_id)
    stops = tv.route_for(ctx.db, v)
    parties = {p.id: p for p in ctx.db.scalars(select(Party).where(Party.id.in_([s.party_id for s in stops])))} if stops else {}
    return [{"party_id": str(s.party_id), "name": parties[s.party_id].name, "city": parties[s.party_id].city,
             "address": parties[s.party_id].address, "weekdays": s.weekdays, "notes": s.notes} for s in stops if s.party_id in parties]


@router.put("/furgoni/{van_id}/giro-clienti")
def put_route(van_id: uuid.UUID, body: list[RouteStopIn], ctx: TenantContext = Depends(planner)):
    v = _van(ctx, van_id)
    tv.save_route(ctx.db, v, [b.model_dump(mode="json") for b in body])
    return get_route(van_id, ctx)


# ====================================================================== giri


class TripIn(BaseModel):
    van_id: uuid.UUID
    trip_date: date
    party_ids: list[uuid.UUID] | None = None


@router.get("/giri")
def list_trips(day: date | None = None, date_from: date | None = None, date_to: date | None = None, van_id: uuid.UUID | None = None,
               status_: str | None = Query(None, alias="status"), ctx: TenantContext = Depends(user)):
    q = select(VanTrip).order_by(VanTrip.trip_date.desc(), VanTrip.created_at.desc())
    if day:
        q = q.where(VanTrip.trip_date == day)
    else:
        q = q.where(VanTrip.trip_date >= (date_from or tv.recent_trip_start()), VanTrip.trip_date <= (date_to or date.today() + timedelta(days=30)))
    if van_id:
        q = q.where(VanTrip.van_id == van_id)
    if status_:
        q = q.where(VanTrip.status == status_)
    if is_agent(ctx):
        q = q.join(Van, Van.id == VanTrip.van_id).where(Van.agent_id == ctx.user.id)
    out = []
    for t in ctx.db.scalars(q.limit(300)):
        o = tv.trip_out(ctx.db, t, brief=True)
        o["summary"] = tv.summary(ctx.db, t)
        out.append(o)
    return out


@router.post("/giri", status_code=201)
def create_trip(body: TripIn, ctx: TenantContext = Depends(user)):
    v = _van(ctx, body.van_id)
    if not is_agent(ctx):
        _can(ctx, PLANNERS + ("magazzino",), "Non puoi creare giri")
    t = tv.create_trip(ctx.db, v, body.trip_date, ctx.user.id, [str(p) for p in body.party_ids] if body.party_ids is not None else None)
    return tv.trip_out(ctx.db, t)


@router.get("/giri/{trip_id}")
def get_trip(trip_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    out = tv.trip_out(ctx.db, t)
    out["documents"] = [tv.doc_out(ctx.db, d) for d in tv.trip_documents(ctx.db, t)]
    out["collections"] = [tv.collection_out(ctx.db, c) for c in ctx.db.scalars(
        select(VanCollection).where(VanCollection.trip_id == t.id).order_by(VanCollection.collected_at))]
    return out


class StopsIn(BaseModel):
    stops: list[dict]


@router.put("/giri/{trip_id}/clienti")
def put_stops(trip_id: uuid.UUID, body: StopsIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    tv.set_stops(ctx.db, t, body.stops)
    return tv.trip_out(ctx.db, t)


@router.delete("/giri/{trip_id}", status_code=204)
def delete_trip(trip_id: uuid.UUID, ctx: TenantContext = Depends(planner)):
    t = _trip(ctx, trip_id)
    if t.status != "preparazione" or t.load_operations:
        raise HTTPException(status.HTTP_409_CONFLICT, "Si possono eliminare solo i giri non ancora caricati né partiti")
    ctx.db.delete(t)


@router.get("/giri/{trip_id}/proposta-carico")
def load_proposal(trip_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    return tv.load_proposal(ctx.db, t)


class LoadLine(BaseModel):
    item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0)
    lot_number: str | None = None
    serials: list[str] | None = None


class LoadIn(BaseModel):
    lines: list[LoadLine]


@router.post("/giri/{trip_id}/carico")
def load(trip_id: uuid.UUID, body: LoadIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    _can(ctx, WAREHOUSE + ("vendite",), "Il carico lo fa il magazzino")
    tv.load(ctx.db, t, ctx.user.id, [ln.model_dump(mode="json") for ln in body.lines])
    return {"trip": tv.trip_out(ctx.db, t, brief=True), "lines": tv.load_lines(ctx.db, t)}


@router.get("/giri/{trip_id}/carico")
def loaded(trip_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    van = ctx.db.get(Van, t.van_id)
    return {"trip": tv.trip_out(ctx.db, t, brief=True), "van": tv.van_out(ctx.db, van), "lines": tv.load_lines(ctx.db, t),
            "on_van": tv.van_stock(ctx.db, van)}


class StartIn(BaseModel):
    km_start: int | None = Field(None, ge=0)


@router.post("/giri/{trip_id}/partenza")
def start(trip_id: uuid.UUID, body: StartIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    tv.start(ctx.db, t, body.km_start)
    return tv.trip_out(ctx.db, t, brief=True)


@router.get("/giri/{trip_id}/pacchetto")
def package(trip_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    return tv.package(ctx.db, t)


# ====================================================================== documenti e incassi dell'agente


class DocLine(BaseModel):
    item_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=500)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Decimal(0)
    discount: Decimal | None = Field(None, ge=0, le=100)
    lot_number: str | None = None
    serials: list[str] | None = None
    origin_line_id: uuid.UUID | None = None
    vat_rate_id: uuid.UUID | None = None
    price_source: str | None = None
    notes: str | None = None


class Signature(BaseModel):
    signer_name: str | None = Field(None, max_length=120)
    signature_png: str | None = None
    signed_at: str | None = None
    lat: float | None = None
    lon: float | None = None
    accuracy: float | None = None


class CollectionIn(BaseModel):
    client_uuid: uuid.UUID | None = None
    party_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    installment_ids: list[uuid.UUID] | None = None
    method: str
    amount: Decimal = Field(gt=0)
    check_info: str | None = Field(None, max_length=120)
    signature: Signature | None = None


class AgentDocIn(BaseModel):
    client_uuid: uuid.UUID
    doc_type: str
    party_id: uuid.UUID
    doc_date: date | None = None
    destination_id: uuid.UUID | None = None
    payment_term_id: uuid.UUID | None = None
    lines: list[DocLine]
    notes: str | None = None
    reference: str | None = None
    delivery: Signature | None = None
    collection: CollectionIn | None = None
    credit_warning: str | None = None


@router.post("/giri/{trip_id}/documenti")
def create_document(trip_id: uuid.UUID, body: AgentDocIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    data = body.model_dump(mode="json")
    try:
        with ctx.db.begin_nested():
            d, replay = tv.create_document(ctx.db, t, ctx.user, data, is_agent(ctx))
    except IntegrityError:  # lo stesso documento arrivato due volte in parallelo dalla coda
        d = ctx.db.scalar(select(Document).where(Document.client_uuid == body.client_uuid))
        if d is None:
            raise
        replay = True
    return {**tv.doc_out(ctx.db, d), "replayed": replay}


@router.post("/giri/{trip_id}/incassi")
def collect(trip_id: uuid.UUID, body: CollectionIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    try:
        with ctx.db.begin_nested():
            c, replay = tv.collect(ctx.db, t, ctx.user, body.model_dump(mode="json"))
    except IntegrityError:
        c = ctx.db.scalar(select(VanCollection).where(VanCollection.client_uuid == body.client_uuid))
        if c is None:
            raise
        replay = True
    return {**tv.collection_out(ctx.db, c), "replayed": replay}


class VisitIn(BaseModel):
    party_id: uuid.UUID
    notes: str | None = Field(None, max_length=200)


@router.post("/giri/{trip_id}/visite")
def visit(trip_id: uuid.UUID, body: VisitIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    tv.mark_visit(ctx.db, t, body.party_id, body.notes)
    return {"ok": True}


def _doc(ctx: TenantContext, doc_id) -> Document:
    d = ctx.db.get(Document, doc_id)
    if d is None or d.direction != "vendita":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento non trovato")
    if is_agent(ctx):
        t = ctx.db.get(VanTrip, d.van_trip_id) if d.van_trip_id else None
        if t is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento non trovato")
        _van(ctx, t.van_id)
    return d


@router.get("/documenti/{doc_id}/pdf")
def doc_pdf(doc_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    d = _doc(ctx, doc_id)
    return Response(pdf.document_pdf(ctx.db, d), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{pdf.file_name(d)}"'})


class SendIn(BaseModel):
    channel: str = Field(pattern="^(email|whatsapp)$")
    to: str | None = Field(None, max_length=200)
    client_uuid: uuid.UUID | None = None  # per non rimandare due volte dalla coda


def public_link(d: Document) -> str:
    token = jwt.encode({"t": str(d.tenant_id), "d": str(d.id), "k": "doc",
                        "exp": datetime.now(timezone.utc) + timedelta(days=60)}, get_settings().secret_key, algorithm="HS256")
    return f"{get_settings().public_url.rstrip('/')}/api/tentata/pdf/{token}"


@router.post("/documenti/{doc_id}/invia")
def send(doc_id: uuid.UUID, body: SendIn, ctx: TenantContext = Depends(user)):
    """Email con il PDF firmato in allegato, oppure link sicuro al PDF da mandare su WhatsApp (messaggio precompilato)."""
    d = _doc(ctx, doc_id)
    party = ctx.db.get(Party, d.party_id)
    sent = list((d.delivery or {}).get("sent", []))
    if body.client_uuid and any(s.get("client_uuid") == str(body.client_uuid) for s in sent):
        prev = next(s for s in sent if s.get("client_uuid") == str(body.client_uuid))
        return {"ok": True, "replayed": True, **prev}
    from app.core.models import Company
    company = ctx.db.scalar(select(Company).order_by(Company.name))
    label = tv.doc_label(d)
    entry = {"channel": body.channel, "at": datetime.now().astimezone().isoformat(), "by": ctx.user.full_name,
             "client_uuid": str(body.client_uuid) if body.client_uuid else None}
    if body.channel == "email":
        to = (body.to or (party.email if party else None) or "").strip()
        if "@" not in to:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica l'indirizzo email del cliente")
        from app.core.mailer import send_email
        html = (f"<p>Gentile cliente,</p><p>in allegato {label} del {d.doc_date.strftime('%d/%m/%Y')} "
                f"firmato alla consegna.</p><p>Cordiali saluti<br>{company.name if company else ''}</p>")
        try:
            send_email([to], f"{label} – {company.name if company else ''}", html,
                       attachments=[(pdf.file_name(d), pdf.document_pdf(ctx.db, d), "application/pdf")])
        except Exception as e:  # noqa: BLE001
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Email non inviata: {e}") from None
        entry["to"] = to
    else:
        phone = "".join(ch for ch in (body.to or (party.mobile or party.phone if party else "") or "") if ch.isdigit())
        if phone.startswith("00"):
            phone = phone[2:]
        if len(phone) == 10 and phone.startswith("3"):
            phone = "39" + phone
        if len(phone) < 8:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica il numero di cellulare del cliente")
        link = public_link(d)
        text = (f"Buongiorno, ecco {label} del {d.doc_date.strftime('%d/%m/%Y')} firmato alla consegna: {link}"
                f"\n{company.name if company else ''}")
        from urllib.parse import quote
        entry.update({"to": phone, "url": f"https://wa.me/{phone}?text={quote(text)}"})
    d.delivery = {**(d.delivery or {}), "sent": [*sent, entry]}
    return {"ok": True, **entry}


@public.get("/pdf/{token}")
def public_pdf(token: str):
    """PDF aperto dal cliente dal link ricevuto su WhatsApp (link firmato, valido 60 giorni)."""
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        if data.get("k") != "doc":
            raise ValueError
        tid, did = uuid.UUID(data["t"]), uuid.UUID(data["d"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link non valido o scaduto") from None
    db = new_session()
    try:
        set_tenant(db, tid)
        d = db.get(Document, did)
        if d is None or d.status == "annullato":
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento non disponibile")
        content = pdf.document_pdf(db, d)
        name = pdf.file_name(d)
        db.rollback()
    finally:
        db.close()
    return Response(content, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"',
                                                                     "Cache-Control": "private, no-store"})


# ====================================================================== rientro e verifica


class ReturnIn(BaseModel):
    km_end: int | None = Field(None, ge=0)
    cash: dict[str, Decimal] = {}
    counts: list[dict] = []
    notes: str | None = None
    signature: Signature | None = None


@router.post("/giri/{trip_id}/rientro")
def declare_return(trip_id: uuid.UUID, body: ReturnIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    tv.declare_return(ctx.db, t, ctx.user, body.model_dump(mode="json"))
    return tv.trip_out(ctx.db, t)


@router.get("/giri/{trip_id}/rientro")
def return_sheet(trip_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    """Righe del rientro. Conta alla cieca: finché il giro non è chiuso il magazziniere non vede le quantità attese
    (le vedono l'agente, che le ha dichiarate, e l'amministrazione)."""
    t = _trip(ctx, trip_id)
    van = ctx.db.get(Van, t.van_id)
    reveal = t.status == "chiuso" or not van.blind_count or ctx.user.role in ("agente", "amministratore", "amministrazione", "vendite")
    if t.status in ("preparazione", "in_corso"):
        rows = [{**r, "expected": r["quantity"]} for r in tv.van_stock(ctx.db, van)]
    else:
        rows = tv.return_rows(ctx.db, t, reveal)
    return {"trip": tv.trip_out(ctx.db, t), "van": tv.van_out(ctx.db, van), "rows": rows, "revealed": reveal,
            "loaded": tv.load_lines(ctx.db, t)}


class CheckIn(BaseModel):
    counts: list[dict]
    extra: list[dict] = []
    remaining: str = Field("rientra", pattern="^(rientra|resta)$")
    signatures: dict[str, Signature] = {}


@router.post("/giri/{trip_id}/verifica")
def check_return(trip_id: uuid.UUID, body: CheckIn, ctx: TenantContext = Depends(user)):
    t = _trip(ctx, trip_id)
    _can(ctx, WAREHOUSE, "La verifica del rientro la fa il magazzino")
    res = tv.check_return(ctx.db, t, ctx.user, body.model_dump(mode="json"))
    audit(ctx.db, "giro", "rientro verificato", t.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after=res)
    return {**res, "trip": tv.trip_out(ctx.db, t)}


# ====================================================================== riepilogo dell'ufficio


@router.get("/riepilogo")
def daily(day: date | None = None, ctx: TenantContext = Depends(planner)):
    """Situazione del giorno per agente: documenti arrivati, venduto, incassato, visite, km."""
    day = day or date.today()
    out = []
    for t in ctx.db.scalars(select(VanTrip).where(VanTrip.trip_date == day).order_by(VanTrip.created_at)):
        o = tv.trip_out(ctx.db, t, brief=True)
        o["summary"] = tv.summary(ctx.db, t)
        last = ctx.db.scalar(select(Document.created_at).where(Document.van_trip_id == t.id).order_by(Document.created_at.desc()))
        o["last_document_at"] = last.isoformat() if last else None
        out.append(o)
    return {"day": day.isoformat(), "trips": out}


@router.get("/clienti")
def search_customers(q: str = Query("", max_length=60), ctx: TenantContext = Depends(user)):
    """Ricerca clienti per aggiungerli al giro (l'agente vede solo quelli del proprio giro abituale)."""
    stmt = select(Party).where(Party.is_customer, Party.active).order_by(Party.name).limit(30)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Party.name.ilike(like) | Party.code.ilike(like) | Party.city.ilike(like) | Party.vat_number.ilike(like))
    if is_agent(ctx):
        vans = ctx.db.scalars(select(Van.id).where(Van.agent_id == ctx.user.id)).all()
        stmt = stmt.where(Party.id.in_(select(VanRouteStop.party_id).where(VanRouteStop.van_id.in_(vans))))
    return [{"id": str(p.id), "code": p.code, "name": p.name, "city": p.city, "address": p.address} for p in ctx.db.scalars(stmt)]
