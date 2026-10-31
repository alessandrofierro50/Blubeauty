"""API del magazzino: /api/magazzino/...  (modulo "magazzino")."""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.anagrafiche import tabular
from app.anagrafiche.models import AppSetting, Brand, Category, Item, ItemBarcode, ItemVariant, Party
from app.core.deps import TenantContext, require_module
from app.core.models import Company, Warehouse
from app.magazzino import inventory, service
from app.magazzino.models import (
    InventoryCount,
    InventorySession,
    Lot,
    Serial,
    StockBalance,
    StockMovement,
    Store,
)
from app.saas.service import audit

router = APIRouter(prefix="/api/magazzino", tags=["magazzino"])
reader = require_module("magazzino")


def writer(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role in ("cassa", "contabilita"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo può solo consultare il magazzino")
    return ctx


def counter(ctx: TenantContext = Depends(reader)) -> TenantContext:
    """Contare l'inventario è permesso a tutti i ruoli operativi (anche alla cassa)."""
    return ctx


def s(v):
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _ctx(ctx: TenantContext, **kw) -> service.Ctx:
    return service.Ctx(tenant_id=ctx.tenant_id, user_id=ctx.user.id, **kw)


# ====================================================================== magazzini e punti vendita


@router.get("/magazzini")
def list_warehouses(ctx: TenantContext = Depends(reader)):
    stores = ctx.db.scalars(select(Store)).all()
    out = []
    for w in ctx.db.scalars(select(Warehouse).order_by(Warehouse.code)):
        out.append({"id": str(w.id), "code": w.code, "name": w.name, "company_id": str(w.company_id),
                    "stores": [st.name for st in stores if st.warehouse_id == w.id]})
    return {"rows": out, "max_warehouses": ctx.state.limits["max_warehouses"]}


class WarehouseIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)


@router.post("/magazzini", status_code=201)
def create_warehouse(body: WarehouseIn, ctx: TenantContext = Depends(writer)):
    n = ctx.db.scalar(select(func.count()).select_from(Warehouse))
    if n >= ctx.state.limits["max_warehouses"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "limite_magazzini",
                            "message": f"Il tuo pacchetto consente {ctx.state.limits['max_warehouses']} magazzini."})
    company = ctx.db.scalar(select(Company).order_by(Company.name))
    w = Warehouse(tenant_id=ctx.tenant_id, company_id=company.id, code=body.code.strip().upper(), name=body.name)
    ctx.db.add(w)
    ctx.db.flush()
    return {"id": str(w.id), "code": w.code, "name": w.name}


@router.put("/magazzini/{wh_id}")
def update_warehouse(wh_id: uuid.UUID, body: WarehouseIn, ctx: TenantContext = Depends(writer)):
    w = ctx.db.get(Warehouse, wh_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Magazzino non trovato")
    w.code, w.name = body.code.strip().upper(), body.name
    return {"ok": True}


STORE_FIELDS = ["code", "name", "address", "zip_code", "city", "province", "phone", "warehouse_id", "active"]


class StoreIn(BaseModel):
    code: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=120)
    address: str | None = None
    zip_code: str | None = None
    city: str | None = None
    province: str | None = None
    phone: str | None = None
    warehouse_id: uuid.UUID | None = None  # vuoto = crea un magazzino dedicato
    active: bool = True


@router.get("/punti-vendita")
def list_stores(ctx: TenantContext = Depends(reader)):
    whs = {w.id: w for w in ctx.db.scalars(select(Warehouse))}
    rows = ctx.db.scalars(select(Store).order_by(Store.code)).all()
    shared = {w: sum(1 for r in rows if r.warehouse_id == w) for w in whs}
    return [{**{f: s(getattr(r, f)) for f in STORE_FIELDS}, "id": str(r.id),
             "warehouse_name": whs[r.warehouse_id].name if r.warehouse_id in whs else None,
             "shared_warehouse": shared.get(r.warehouse_id, 0) > 1} for r in rows]


@router.post("/punti-vendita", status_code=201)
def create_store(body: StoreIn, ctx: TenantContext = Depends(writer)):
    company = ctx.db.scalar(select(Company).order_by(Company.name))
    data = body.model_dump()
    if data["warehouse_id"] is None:
        wh = create_warehouse(WarehouseIn(code=f"MAG-{body.code.upper()}"[:20], name=f"Magazzino {body.name}"[:120]), ctx)
        data["warehouse_id"] = uuid.UUID(wh["id"])
    elif ctx.db.get(Warehouse, data["warehouse_id"]) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Magazzino inesistente")
    data["code"] = data["code"].strip().upper()
    st = Store(tenant_id=ctx.tenant_id, company_id=company.id, **data)
    ctx.db.add(st)
    try:
        ctx.db.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_409_CONFLICT, "Codice punto vendita già esistente") from None
    return {"id": str(st.id)}


@router.put("/punti-vendita/{store_id}")
def update_store(store_id: uuid.UUID, body: StoreIn, ctx: TenantContext = Depends(writer)):
    st = ctx.db.get(Store, store_id)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Punto vendita non trovato")
    data = body.model_dump()
    if data["warehouse_id"] is None:
        data["warehouse_id"] = st.warehouse_id
    for k, v in data.items():
        setattr(st, k, v.strip().upper() if k == "code" else v)
    return {"ok": True}


# ====================================================================== impostazioni


@router.get("/impostazioni")
def get_policy(ctx: TenantContext = Depends(reader)):
    return {"allow_negative": service.allow_negative(ctx.db, ctx.tenant_id)}


class PolicyIn(BaseModel):
    allow_negative: bool


@router.put("/impostazioni")
def set_policy(body: PolicyIn, ctx: TenantContext = Depends(writer)):
    st = ctx.db.get(AppSetting, (ctx.tenant_id, "stock_policy"))
    if st:
        st.value = {**(st.value or {}), "allow_negative": body.allow_negative}
    else:
        ctx.db.add(AppSetting(tenant_id=ctx.tenant_id, key="stock_policy", value={"allow_negative": body.allow_negative}))
    return body


# ====================================================================== giacenze


@router.get("/giacenze")
def stock_list(
    q: str | None = None,
    warehouse_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    filtro: str = Query("tutti", pattern="^(tutti|sotto_scorta|esauriti|negativi|disponibili)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(reader),
):
    db = ctx.db
    stmt = select(Item).where(Item.active, Item.stock_managed, Item.item_type == "articolo", Item.is_kit.is_(False))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Item.code.ilike(like), Item.description.ilike(like),
                              Item.id.in_(select(ItemBarcode.item_id).where(ItemBarcode.barcode == q.strip()))))
    if category_id:
        stmt = stmt.where(or_(Item.category_id == category_id, Item.category_id.in_(select(Category.id).where(Category.parent_id == category_id))))
    items = db.scalars(stmt.order_by(Item.code)).all()
    stock = service.stock_by_key(db, [i.id for i in items], warehouse_id)
    per_item: dict = {}
    for (item_id, _v, _l), (oh, rs, od) in stock.items():
        a = per_item.setdefault(item_id, [Decimal(0), Decimal(0), Decimal(0)])
        a[0] += oh
        a[1] += rs
        a[2] += od
    cats = {c.id: c.name for c in db.scalars(select(Category))}
    rows = []
    for it in items:
        oh, rs, od = per_item.get(it.id, [Decimal(0)] * 3)
        avail = oh - rs
        under = it.min_stock is not None and oh < Decimal(it.min_stock)
        if filtro == "sotto_scorta" and not under:
            continue
        if filtro == "esauriti" and oh > 0:
            continue
        if filtro == "negativi" and oh >= 0:
            continue
        if filtro == "disponibili" and avail <= 0:
            continue
        rows.append({"id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
                     "category": cats.get(it.category_id), "location": it.location, "on_hand": s(oh), "reserved": s(rs),
                     "ordered": s(od), "available": s(avail), "min_stock": s(it.min_stock), "under_min": under,
                     "value": s((oh * Decimal(it.avg_cost or 0)).quantize(Decimal("0.01"))) if oh > 0 else "0.00",
                     "has_variants": it.has_variants, "lot_managed": it.lot_managed, "serial_managed": it.serial_managed})
    total_value = sum(Decimal(r["value"]) for r in rows)
    start = (page - 1) * page_size
    return {"total": len(rows), "page": page, "page_size": page_size, "stock_value": s(total_value),
            "rows": rows[start:start + page_size]}


@router.get("/giacenze/{item_id}")
def stock_detail(item_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    """Scheda di magazzino: per magazzino, griglia varianti, lotti, matricole e ultimi movimenti."""
    db = ctx.db
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    whs = {w.id: w for w in db.scalars(select(Warehouse).order_by(Warehouse.code))}
    variants = db.scalars(select(ItemVariant).where(ItemVariant.item_id == item_id).order_by(ItemVariant.code)).all()
    lots = {l.id: l for l in db.scalars(select(Lot).where(Lot.item_id == item_id))}
    bals = db.scalars(select(StockBalance).where(StockBalance.item_id == item_id)).all()

    by_wh = {}
    for b in bals:
        a = by_wh.setdefault(b.warehouse_id, [Decimal(0), Decimal(0), Decimal(0)])
        a[0] += b.on_hand
        a[1] += b.reserved
        a[2] += b.ordered
    warehouses = [{"warehouse_id": str(w), "name": whs[w].name, "on_hand": s(v[0]), "reserved": s(v[1]),
                   "ordered": s(v[2]), "available": s(v[0] - v[1])} for w, v in by_wh.items() if w in whs]

    grid = None
    if variants:
        cells: dict = {}
        for b in bals:
            if b.variant_id:
                c = cells.setdefault(str(b.variant_id), {})
                c[str(b.warehouse_id)] = s(Decimal(c.get(str(b.warehouse_id), 0)) + Decimal(b.on_hand))
        grid = {"variants": [{"id": str(v.id), "code": v.code, "size": v.size, "color": v.color, "format": v.format,
                              "active": v.active, "stock": cells.get(str(v.id), {})} for v in variants]}

    lot_rows = []
    for b in bals:
        if b.lot_id and Decimal(b.on_hand) != 0:
            lot = lots[b.lot_id]
            lot_rows.append({"lot_id": str(lot.id), "lot_number": lot.lot_number, "expiry_date": s(lot.expiry_date),
                             "warehouse": whs[b.warehouse_id].name if b.warehouse_id in whs else None,
                             "variant_id": s(b.variant_id), "on_hand": s(b.on_hand)})
    lot_rows.sort(key=lambda r: (r["expiry_date"] or "9999", r["lot_number"]))

    serials = []
    if it.serial_managed:
        for sr in db.scalars(select(Serial).where(Serial.item_id == item_id).order_by(Serial.serial_number)):
            serials.append({"serial_number": sr.serial_number, "status": sr.status,
                            "warehouse": whs[sr.warehouse_id].name if sr.warehouse_id in whs else None,
                            "sale_date": s(sr.sale_date), "warranty_until": s(sr.warranty_until)})

    moves = movements_list(item_id=item_id, warehouse_id=None, reason=None, date_from=None, date_to=None,
                           operation_id=None, page=1, page_size=30, ctx=ctx)["rows"]
    return {"item": {"id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
                     "min_stock": s(it.min_stock), "avg_cost": s(it.avg_cost), "last_cost": s(it.last_cost),
                     "lot_managed": it.lot_managed, "serial_managed": it.serial_managed, "has_variants": it.has_variants,
                     "location": it.location},
            "warehouses": warehouses, "all_warehouses": [{"id": str(w.id), "name": w.name} for w in whs.values()],
            "grid": grid, "lots": lot_rows, "serials": serials, "movements": moves}


# ====================================================================== movimenti


class LineIn(BaseModel):
    item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: Decimal = Field(gt=0)  # sempre positiva: il segno lo dà l'operazione
    unit_cost: Decimal | None = None
    lot_number: str | None = None
    expiry_date: date | None = None
    serials: list[str] = []


class OperationIn(BaseModel):
    kind: str = Field(pattern="^(carico|scarico|rettifica_piu|rettifica_meno|scarto|omaggio)$")
    warehouse_id: uuid.UUID
    when: date | None = None  # data dell'operazione (vuota = oggi)
    party_id: uuid.UUID | None = None
    reference: str | None = None
    lines: list[LineIn] = Field(min_length=1)


KIND_MAP = {"carico": ("carico", 1), "scarico": ("scarico", -1), "rettifica_piu": ("rettifica", 1),
            "rettifica_meno": ("rettifica", -1), "scarto": ("scarto", -1), "omaggio": ("omaggio", -1)}


def _moved_at(d: date | None) -> datetime | None:
    if d is None or d == date.today():
        return None
    return datetime.combine(d, time(12, 0)).astimezone()


@router.post("/movimenti", status_code=201)
def create_operation(body: OperationIn, ctx: TenantContext = Depends(writer)):
    """Carico, scarico o rettifica manuale con più righe (tutte o nessuna)."""
    if ctx.db.get(Warehouse, body.warehouse_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Magazzino inesistente")
    reason, sign = KIND_MAP[body.kind]
    c = _ctx(ctx, moved_at=_moved_at(body.when), party_id=body.party_id, reference=body.reference)
    n = 0
    for ln in body.lines:
        n += len(service.apply_line(ctx.db, c, warehouse_id=body.warehouse_id, item_id=ln.item_id,
                                    qty=ln.quantity * sign, reason=reason, variant_id=ln.variant_id,
                                    lot_number=ln.lot_number, expiry_date=ln.expiry_date, serials=ln.serials,
                                    unit_cost=ln.unit_cost))
    audit(ctx.db, "stock", body.kind, c.operation_id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          admin_id=ctx.impersonated_by, after={"righe": len(body.lines), "movimenti": n})
    return {"operation_id": str(c.operation_id), "movements": n}


class TransferIn(BaseModel):
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    when: date | None = None  # data dell'operazione (vuota = oggi)
    reference: str | None = None
    lines: list[LineIn] = Field(min_length=1)


@router.post("/trasferimenti", status_code=201)
def create_transfer(body: TransferIn, ctx: TenantContext = Depends(writer)):
    for w in (body.from_warehouse_id, body.to_warehouse_id):
        if ctx.db.get(Warehouse, w) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Magazzino inesistente")
    c = _ctx(ctx, moved_at=_moved_at(body.when), reference=body.reference)
    n = 0
    for ln in body.lines:
        n += len(service.transfer(ctx.db, c, from_wh=body.from_warehouse_id, to_wh=body.to_warehouse_id,
                                  item_id=ln.item_id, qty=ln.quantity, variant_id=ln.variant_id,
                                  lot_number=ln.lot_number, serials=ln.serials))
    return {"operation_id": str(c.operation_id), "movements": n}


@router.get("/movimenti")
def movements_list(
    item_id: uuid.UUID | None = None,
    warehouse_id: uuid.UUID | None = None,
    reason: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    operation_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(reader),
):
    db = ctx.db
    stmt = select(StockMovement)
    if item_id:
        stmt = stmt.where(StockMovement.item_id == item_id)
    if warehouse_id:
        stmt = stmt.where(StockMovement.warehouse_id == warehouse_id)
    if reason:
        stmt = stmt.where(StockMovement.reason == reason)
    if operation_id:
        stmt = stmt.where(StockMovement.operation_id == operation_id)
    if date_from:
        stmt = stmt.where(StockMovement.moved_at >= datetime.combine(date_from, time.min).astimezone())
    if date_to:
        stmt = stmt.where(StockMovement.moved_at < datetime.combine(date_to + timedelta(days=1), time.min).astimezone())
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(StockMovement.moved_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({r.item_id for r in rows})))} if rows else {}
    variants = {v.id: v.code for v in db.scalars(select(ItemVariant).where(ItemVariant.id.in_({r.variant_id for r in rows if r.variant_id})))} if rows else {}
    lots = {l.id: l.lot_number for l in db.scalars(select(Lot).where(Lot.id.in_({r.lot_id for r in rows if r.lot_id})))} if rows else {}
    serials = {x.id: x.serial_number for x in db.scalars(select(Serial).where(Serial.id.in_({r.serial_id for r in rows if r.serial_id})))} if rows else {}
    whs = {w.id: w.name for w in db.scalars(select(Warehouse))}
    parties = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_({r.party_id for r in rows if r.party_id})))} if rows else {}
    return {"total": total, "page": page, "page_size": page_size, "rows": [{
        "id": str(m.id), "moved_at": m.moved_at.isoformat(), "warehouse": whs.get(m.warehouse_id),
        "item_id": str(m.item_id), "code": items[m.item_id].code if m.item_id in items else None,
        "description": items[m.item_id].description if m.item_id in items else None,
        "variant_code": variants.get(m.variant_id), "lot_number": lots.get(m.lot_id), "serial_number": serials.get(m.serial_id),
        "quantity": s(m.quantity), "unit_cost": s(m.unit_cost), "reason": m.reason,
        "reason_label": service.REASONS.get(m.reason, (m.reason,))[0], "party": parties.get(m.party_id),
        "reference": m.reference, "operation_id": str(m.operation_id)} for m in rows]}


# ====================================================================== lotti e matricole


@router.get("/lotti")
def lots_list(entro_giorni: int | None = None, item_id: uuid.UUID | None = None, ctx: TenantContext = Depends(reader)):
    """Lotti con giacenza, ordinati per scadenza. entro_giorni filtra quelli in scadenza (e già scaduti)."""
    db = ctx.db
    stmt = select(StockBalance, Lot, Item).join(Lot, Lot.id == StockBalance.lot_id).join(Item, Item.id == StockBalance.item_id) \
        .where(StockBalance.on_hand > 0)
    if item_id:
        stmt = stmt.where(StockBalance.item_id == item_id)
    if entro_giorni is not None:
        stmt = stmt.where(Lot.expiry_date <= date.today() + timedelta(days=entro_giorni))
    whs = {w.id: w.name for w in db.scalars(select(Warehouse))}
    today = date.today()
    out = []
    for b, lot, it in db.execute(stmt.order_by(Lot.expiry_date.asc().nulls_last())):
        days = (lot.expiry_date - today).days if lot.expiry_date else None
        out.append({"item_id": str(it.id), "code": it.code, "description": it.description, "lot_number": lot.lot_number,
                    "expiry_date": s(lot.expiry_date), "days_left": days, "warehouse": whs.get(b.warehouse_id),
                    "on_hand": s(b.on_hand), "unit": it.unit,
                    "state": None if days is None else "scaduto" if days < 0 else "in_scadenza" if days <= 7 else "ok"})
    return out


@router.get("/matricole")
def serial_search(q: str = Query(min_length=2), ctx: TenantContext = Depends(reader)):
    """Ricerca matricola: storia completa del pezzo (acquisto, vendita, garanzia)."""
    db = ctx.db
    whs = {w.id: w.name for w in db.scalars(select(Warehouse))}
    out = []
    for sr in db.scalars(select(Serial).where(Serial.serial_number.ilike(f"%{q.strip()}%")).limit(50)):
        it = db.get(Item, sr.item_id)
        moves = db.scalars(select(StockMovement).where(StockMovement.serial_id == sr.id).order_by(StockMovement.moved_at)).all()
        out.append({"serial_number": sr.serial_number, "status": sr.status, "item_id": str(it.id), "code": it.code,
                    "description": it.description, "warehouse": whs.get(sr.warehouse_id),
                    "supplier": db.get(Party, sr.supplier_id).name if sr.supplier_id else None,
                    "purchase_date": s(sr.purchase_date), "customer": db.get(Party, sr.customer_id).name if sr.customer_id else None,
                    "sale_date": s(sr.sale_date), "warranty_until": s(sr.warranty_until),
                    "in_warranty": bool(sr.warranty_until and sr.warranty_until >= date.today()),
                    "history": [{"moved_at": m.moved_at.isoformat(), "reason": service.REASONS.get(m.reason, (m.reason,))[0],
                                 "quantity": s(m.quantity), "warehouse": whs.get(m.warehouse_id)} for m in moves]})
    return out


# ====================================================================== inventario


class SessionIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    warehouse_id: uuid.UUID
    category_ids: list[uuid.UUID] = []
    location_prefix: str | None = None
    zero_uncounted: bool = False
    notes: str | None = None


def _session_out(db: Session, x: InventorySession) -> dict:
    wh = db.get(Warehouse, x.warehouse_id)
    n = db.scalar(select(func.count()).select_from(InventoryCount).where(InventoryCount.session_id == x.id))
    return {"id": str(x.id), "name": x.name, "warehouse_id": str(x.warehouse_id), "warehouse": wh.name if wh else None,
            "status": x.status, "category_ids": [str(c) for c in x.category_ids or []], "location_prefix": x.location_prefix,
            "zero_uncounted": x.zero_uncounted, "notes": x.notes, "opened_at": x.opened_at.isoformat(),
            "closed_at": s(x.closed_at), "counts": n, "operation_id": s(x.operation_id)}


def _session(db: Session, sid: uuid.UUID, open_only: bool = False) -> InventorySession:
    x = db.get(InventorySession, sid)
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Inventario non trovato")
    if open_only and x.status != "aperto":
        raise HTTPException(status.HTTP_409_CONFLICT, "L'inventario è già chiuso")
    return x


@router.get("/inventari")
def sessions_list(ctx: TenantContext = Depends(counter)):
    return [_session_out(ctx.db, x) for x in ctx.db.scalars(select(InventorySession).order_by(InventorySession.opened_at.desc()))]


@router.post("/inventari", status_code=201)
def open_session(body: SessionIn, ctx: TenantContext = Depends(writer)):
    if ctx.db.get(Warehouse, body.warehouse_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Magazzino inesistente")
    x = InventorySession(tenant_id=ctx.tenant_id, created_by=ctx.user.id, **body.model_dump())
    ctx.db.add(x)
    ctx.db.flush()
    return _session_out(ctx.db, x)


@router.get("/inventari/{sid}")
def session_detail(sid: uuid.UUID, ctx: TenantContext = Depends(counter)):
    x = _session(ctx.db, sid)
    return {**_session_out(ctx.db, x), **inventory.summary(ctx.db, x)}


class CountIn(BaseModel):
    client_uuid: uuid.UUID
    item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: Decimal = Field(ge=0)
    lot_number: str | None = None
    expiry_date: date | None = None
    serial_number: str | None = None
    counted_at: datetime | None = None


@router.post("/inventari/{sid}/conteggi")
def add_counts(sid: uuid.UUID, body: list[CountIn], ctx: TenantContext = Depends(counter)):
    """Conteggi dallo smartphone (anche in blocco, quando torna la rete). Gli invii ripetuti vengono ignorati."""
    x = _session(ctx.db, sid, open_only=True)
    added = 0
    seen: set = set()
    for c in body:
        if c.client_uuid in seen or ctx.db.scalar(select(InventoryCount.id).where(InventoryCount.client_uuid == c.client_uuid)):
            continue
        seen.add(c.client_uuid)
        it = ctx.db.get(Item, c.item_id)
        if it is None:
            continue
        if it.serial_managed and not c.serial_number:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{it.code}: leggi la matricola")
        if it.lot_managed and not c.lot_number:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{it.code}: indica il lotto")
        cnt = InventoryCount(tenant_id=ctx.tenant_id, session_id=x.id, user_id=ctx.user.id, source="smartphone",
                             **c.model_dump(exclude={"counted_at"}))
        if it.serial_managed:
            cnt.quantity, cnt.serial_number = Decimal(1), c.serial_number.strip().upper()
        if c.lot_number:
            cnt.lot_number = c.lot_number.strip().upper()
        if c.counted_at:
            cnt.counted_at = c.counted_at
        ctx.db.add(cnt)
        added += 1
    ctx.db.flush()
    return {"added": added}


class ManualIn(BaseModel):
    item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    lot_number: str | None = None
    expiry_date: date | None = None
    quantity: Decimal = Field(ge=0)


@router.put("/inventari/{sid}/quantita")
def set_quantity(sid: uuid.UUID, body: list[ManualIn], ctx: TenantContext = Depends(writer)):
    """Correzione manuale dalla schermata di revisione: la quantità scritta sostituisce i conteggi di quella riga."""
    x = _session(ctx.db, sid, open_only=True)
    for m in body:
        lot = m.lot_number.strip().upper() if m.lot_number else None
        q = select(InventoryCount).where(InventoryCount.session_id == x.id, InventoryCount.item_id == m.item_id,
                                         InventoryCount.variant_id.is_(None) if m.variant_id is None else InventoryCount.variant_id == m.variant_id,
                                         InventoryCount.lot_number.is_(None) if lot is None else InventoryCount.lot_number == lot)
        for old in ctx.db.scalars(q):
            old.accepted = False
        ctx.db.add(InventoryCount(tenant_id=ctx.tenant_id, session_id=x.id, item_id=m.item_id, variant_id=m.variant_id,
                                  lot_number=lot, expiry_date=m.expiry_date, quantity=m.quantity,
                                  client_uuid=uuid.uuid4(), user_id=ctx.user.id, source="manuale", accepted=True))
    ctx.db.flush()
    return session_detail(sid, ctx)


class AcceptIn(BaseModel):
    count_ids: list[uuid.UUID]
    accepted: bool


@router.post("/inventari/{sid}/accetta")
def accept_counts(sid: uuid.UUID, body: AcceptIn, ctx: TenantContext = Depends(writer)):
    x = _session(ctx.db, sid, open_only=True)
    for c in ctx.db.scalars(select(InventoryCount).where(InventoryCount.session_id == x.id, InventoryCount.id.in_(body.count_ids))):
        c.accepted = body.accepted
    ctx.db.flush()
    return session_detail(sid, ctx)


@router.post("/inventari/{sid}/import")
async def import_counts(sid: uuid.UUID, file: UploadFile = File(...), ctx: TenantContext = Depends(writer)):
    """Import conteggi da Excel/CSV: colonne codice (o barcode), quantità, eventuali taglia/colore/variante, lotto, scadenza."""
    x = _session(ctx.db, sid, open_only=True)
    headers, rows = tabular.read_table(file.filename or "", await file.read())
    fields = {"code": ("Codice", ["codice", "cod", "articolo", "barcode", "ean", "codice a barre", "sku"]),
              "quantity": ("Quantità", ["quantita", "qta", "q ta", "qty", "contato", "pezzi", "giacenza"]),
              "variant": ("Variante", ["variante", "codice variante"]),
              "size": ("Taglia", ["taglia", "misura"]), "color": ("Colore", ["colore"]),
              "lot_number": ("Lotto", ["lotto", "lot"]), "expiry_date": ("Scadenza", ["scadenza", "data scadenza"])}
    mapping = tabular.suggest_mapping(headers, fields)
    if "code" not in mapping.values() or "quantity" not in mapping.values():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Servono almeno le colonne Codice e Quantità")
    from app.anagrafiche.router import _dec
    added, errors = 0, []
    for n, r in enumerate(tabular.apply_mapping(headers, rows, mapping), start=2):
        code = (r.get("code") or "").strip()
        it = ctx.db.scalar(select(Item).where(func.upper(Item.code) == code.upper()))
        variant_id = None
        if it is None:
            bc = ctx.db.scalar(select(ItemBarcode).where(ItemBarcode.barcode == code))
            it = ctx.db.get(Item, bc.item_id) if bc else None
            variant_id = bc.variant_id if bc else None
        if it is None:
            vv = ctx.db.scalar(select(ItemVariant).where(func.upper(ItemVariant.code) == code.upper()))
            it = ctx.db.get(Item, vv.item_id) if vv else None
            variant_id = vv.id if vv else None
        if it is None:
            errors.append(f"Riga {n}: articolo {code} non trovato")
            continue
        if it.has_variants and variant_id is None:
            vq = select(ItemVariant).where(ItemVariant.item_id == it.id)
            if r.get("variant"):
                vq = vq.where(func.upper(ItemVariant.code) == r["variant"].upper())
            else:
                if r.get("size"):
                    vq = vq.where(func.upper(ItemVariant.size) == r["size"].upper())
                if r.get("color"):
                    vq = vq.where(func.upper(ItemVariant.color) == r["color"].upper())
            found = ctx.db.scalars(vq).all()
            if len(found) != 1:
                errors.append(f"Riga {n}: variante di {it.code} non identificata")
                continue
            variant_id = found[0].id
        try:
            qty = _dec(r.get("quantity")) or Decimal(0)
            exp = date.fromisoformat(r["expiry_date"][:10]) if r.get("expiry_date") else None
        except ValueError as exc:
            errors.append(f"Riga {n}: {exc}")
            continue
        ctx.db.add(InventoryCount(tenant_id=ctx.tenant_id, session_id=x.id, item_id=it.id, variant_id=variant_id,
                                  lot_number=(r.get("lot_number") or "").upper() or None, expiry_date=exp, quantity=qty,
                                  client_uuid=uuid.uuid4(), user_id=ctx.user.id, source="import", accepted=True))
        added += 1
    ctx.db.flush()
    return {"added": added, "errors": errors[:100]}


class CloseIn(BaseModel):
    # False = inventario parziale: le righe non contate restano invariate; True = inventario concluso: si azzerano
    zero_uncounted: bool


@router.post("/inventari/{sid}/chiudi")
def close_session(sid: uuid.UUID, body: CloseIn, ctx: TenantContext = Depends(writer)):
    x = _session(ctx.db, sid, open_only=True)
    c = _ctx(ctx, reference=f"Inventario: {x.name}")
    n = inventory.close(ctx.db, c, x, body.zero_uncounted)
    audit(ctx.db, "inventory", "chiusura", x.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after={"rettifiche": n})
    return {**_session_out(ctx.db, x), "adjusted_rows": n}


@router.post("/inventari/{sid}/annulla")
def cancel_session(sid: uuid.UUID, ctx: TenantContext = Depends(writer)):
    x = _session(ctx.db, sid, open_only=True)
    x.status = "annullato"
    return _session_out(ctx.db, x)


@router.get("/cerca")
def scan_lookup(code: str, tutti: bool = False, ctx: TenantContext = Depends(counter)):
    """Lettura da fotocamera/scanner o ricerca testuale: restituisce articoli con varianti e dati utili al conteggio.
    Accetta codice a barre, QR (codice articolo o URL che lo contiene) o testo.
    `tutti`: anche servizi e kit (documenti di vendita e acquisto); senza, solo articoli a magazzino (conte, movimenti)."""
    db = ctx.db
    raw = code.strip()
    if "/" in raw:  # QR con URL: prende l'ultimo pezzo
        raw = raw.rstrip("/").split("/")[-1]
    bc = db.scalar(select(ItemBarcode).where(ItemBarcode.barcode == raw))
    items: list[Item] = []
    variant_hint = None
    if bc:
        items = [db.get(Item, bc.item_id)]
        variant_hint = bc.variant_id
    else:
        exact = db.scalar(select(Item).where(func.upper(Item.code) == raw.upper()))
        if exact:
            items = [exact]
        else:
            v = db.scalar(select(ItemVariant).where(func.upper(ItemVariant.code) == raw.upper()))
            if v:
                items, variant_hint = [db.get(Item, v.item_id)], v.id
            elif len(raw) >= 2:
                like = f"%{raw}%"
                q = select(Item).where(Item.active, or_(Item.code.ilike(like), Item.description.ilike(like)))
                if not tutti:
                    q = q.where(Item.stock_managed, Item.is_kit.is_(False))
                items = db.scalars(q.order_by(Item.description).limit(15)).all()
    out = []
    for it in items:
        variants = db.scalars(select(ItemVariant).where(ItemVariant.item_id == it.id, ItemVariant.active).order_by(ItemVariant.code)).all()
        out.append({"id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
                    "image": it.image_url, "lot_managed": it.lot_managed, "serial_managed": it.serial_managed,
                    "shelf_life_days": it.shelf_life_days, "location": it.location,
                    "variants": [{"id": str(v.id), "code": v.code, "size": v.size, "color": v.color} for v in variants],
                    "variant_id": str(variant_hint) if variant_hint and it.id == items[0].id else None})
    return out
