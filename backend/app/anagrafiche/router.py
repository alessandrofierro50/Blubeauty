"""API delle anagrafiche: /api/anagrafiche/...  (modulo "anagrafiche", incluso in tutti i pacchetti)."""

import csv
import io
import re
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.anagrafiche import pricing, tabular
from app.anagrafiche.bootstrap import FIELD_GROUPS
from app.anagrafiche.models import (
    AppSetting,
    Brand,
    Catalog,
    Category,
    CustomerCategory,
    CustomerPrice,
    CustomFieldDef,
    Item,
    ItemBarcode,
    ItemComponent,
    ItemAttachment,
    ItemImage,
    ItemPrice,
    ItemSupplier,
    ItemUnit,
    ItemVariant,
    Party,
    PartyAddress,
    PaymentTerm,
    PriceList,
    Promotion,
    Unit,
    VatRate,
)
from app.anagrafiche.price_engine import resolve_price
from app.anagrafiche.validators import make_internal_ean13, party_problems, valid_ean
from app.core import media
from app.core.deps import TenantContext, require_module
from app.saas.service import audit

router = APIRouter(prefix="/api/anagrafiche", tags=["anagrafiche"])

reader = require_module("anagrafiche")


def writer(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role == "cassa":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il ruolo cassa può solo consultare le anagrafiche")
    return ctx


def s(v: Any) -> Any:
    """Serializza Decimal e UUID in stringa, lascia il resto invariato."""
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    return v


def row(obj, fields: list[str]) -> dict:
    return {f: s(getattr(obj, f)) for f in fields}


def next_code(db: Session, model, prefix: str, width: int = 5) -> str:
    codes = db.scalars(select(model.code).where(model.code.like(f"{prefix}%"))).all()
    nums = [int(m.group(1)) for c in codes if (m := re.fullmatch(rf"{re.escape(prefix)}(\d+)", c))]
    return f"{prefix}{(max(nums) + 1 if nums else 1):0{width}d}"


def flush_or_conflict(db: Session, message: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, message) from exc


# ====================================================================== impostazioni


@router.get("/settings")
def get_settings_(ctx: TenantContext = Depends(reader)):
    groups = ctx.db.get(AppSetting, (ctx.tenant_id, "item_field_groups"))
    custom = ctx.db.scalars(select(CustomFieldDef).order_by(CustomFieldDef.entity, CustomFieldDef.sort_order)).all()
    return {
        "field_groups": groups.value if groups else {g: True for g in FIELD_GROUPS},
        "custom_fields": [row(c, ["id", "entity", "key", "label", "field_type", "options", "sort_order"]) for c in custom],
    }


class FieldGroupsIn(BaseModel):
    field_groups: dict[str, bool]


@router.put("/settings/field-groups")
def set_field_groups(body: FieldGroupsIn, ctx: TenantContext = Depends(writer)):
    value = {g: bool(body.field_groups.get(g, False)) for g in FIELD_GROUPS}
    setting = ctx.db.get(AppSetting, (ctx.tenant_id, "item_field_groups"))
    if setting:
        setting.value = value
    else:
        ctx.db.add(AppSetting(tenant_id=ctx.tenant_id, key="item_field_groups", value=value))
    return value


# ====================================================================== tabelle di supporto

# Per ogni tabella: modello, campi modificabili, ordinamento e controlli prima della cancellazione.
TABLES: dict[str, dict] = {
    "aliquote-iva": {"model": VatRate, "fields": ["code", "description", "rate", "nature", "legal_reference", "active"],
                     "order": VatRate.rate.desc(), "refs": [(Item, "vat_rate_id"), (Party, "vat_rate_id")]},
    "pagamenti": {"model": PaymentTerm, "fields": ["code", "description", "method", "installments", "end_of_month", "active"],
                  "order": PaymentTerm.code, "refs": [(Party, "payment_term_id")]},
    "unita-misura": {"model": Unit, "fields": ["code", "description", "decimals"], "order": Unit.code, "refs": []},
    "categorie": {"model": Category, "fields": ["name", "parent_id"], "order": Category.name,
                  "refs": [(Item, "category_id"), (Category, "parent_id")]},
    "marche": {"model": Brand, "fields": ["name"], "order": Brand.name, "refs": [(Item, "brand_id")]},
    "listini": {"model": PriceList, "fields": ["code", "name", "vat_included", "is_default", "markup_percent"],
                "order": PriceList.code, "refs": [(ItemPrice, "price_list_id"), (Party, "price_list_id")]},
    "categorie-clienti": {"model": CustomerCategory, "fields": ["name"], "order": CustomerCategory.name,
                          "refs": [(Party, "customer_category_id")]},
    "campi-personalizzati": {"model": CustomFieldDef, "fields": ["entity", "key", "label", "field_type", "options", "sort_order"],
                             "order": CustomFieldDef.sort_order, "refs": []},
}

DECIMAL_FIELDS = {"rate", "markup_percent"}


def _table(kind: str) -> dict:
    if kind not in TABLES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tabella sconosciuta")
    return TABLES[kind]


def _clean_table_value(field: str, value: Any) -> Any:
    if field in DECIMAL_FIELDS and value not in (None, ""):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Valore non valido per {field}") from None
    if field == "parent_id" and value:
        return uuid.UUID(str(value))
    if field in ("code", "key") and isinstance(value, str):
        return value.strip().upper() if field == "code" else re.sub(r"[^a-z0-9_]", "_", value.strip().lower())
    return None if value == "" else value


@router.get("/tabelle/{kind}")
def list_table(kind: str, ctx: TenantContext = Depends(reader)):
    t = _table(kind)
    rows = ctx.db.scalars(select(t["model"]).order_by(t["order"])).all()
    return [row(r, ["id", *t["fields"]]) for r in rows]


@router.post("/tabelle/{kind}", status_code=201)
def create_table_row(kind: str, body: dict, ctx: TenantContext = Depends(writer)):
    t = _table(kind)
    data = {f: _clean_table_value(f, body.get(f)) for f in t["fields"] if f in body}
    obj = t["model"](tenant_id=ctx.tenant_id, **data)
    if kind == "listini" and obj.is_default:
        for p in ctx.db.scalars(select(PriceList).where(PriceList.is_default)):
            p.is_default = False
    ctx.db.add(obj)
    flush_or_conflict(ctx.db, "Esiste già un elemento con questo codice")
    return row(obj, ["id", *t["fields"]])


@router.put("/tabelle/{kind}/{obj_id}")
def update_table_row(kind: str, obj_id: uuid.UUID, body: dict, ctx: TenantContext = Depends(writer)):
    t = _table(kind)
    obj = ctx.db.get(t["model"], obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Elemento non trovato")
    if kind == "listini" and body.get("is_default"):
        for p in ctx.db.scalars(select(PriceList).where(PriceList.is_default, PriceList.id != obj_id)):
            p.is_default = False
    for f in t["fields"]:
        if f in body:
            setattr(obj, f, _clean_table_value(f, body[f]))
    if kind == "categorie" and obj.parent_id == obj.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Una categoria non può essere figlia di sé stessa")
    flush_or_conflict(ctx.db, "Esiste già un elemento con questo codice")
    return row(obj, ["id", *t["fields"]])


@router.delete("/tabelle/{kind}/{obj_id}")
def delete_table_row(kind: str, obj_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    t = _table(kind)
    obj = ctx.db.get(t["model"], obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Elemento non trovato")
    for model, col in t["refs"]:
        used = ctx.db.scalar(select(func.count()).select_from(model).where(getattr(model, col) == obj_id))
        if used:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Non eliminabile: è usato in {used} anagrafiche. Puoi disattivarlo.")
    ctx.db.delete(obj)
    return {"ok": True}


# ====================================================================== articoli

ITEM_FIELDS = [
    "code", "description", "long_description", "notes", "item_type", "image_url", "category_id", "brand_id",
    "family", "line", "season", "tags", "unit", "weight_net", "weight_gross", "volume", "length", "width", "height",
    "vat_rate_id", "intrastat_code", "origin_country", "last_cost", "avg_cost", "standard_cost", "stock_managed",
    "lot_managed", "serial_managed", "shelf_life_days", "warranty_months", "min_stock", "max_stock", "reorder_point",
    "reorder_qty", "location", "preferred_supplier_id", "lead_time_days", "has_variants", "is_kit", "custom", "active",
    "plu", "pos_department_id", "sold_by_weight",
]


class VariantIn(BaseModel):
    id: uuid.UUID | None = None
    code: str
    size: str | None = None
    color: str | None = None
    format: str | None = None
    price_delta: Decimal | None = None
    active: bool = True


class BarcodeIn(BaseModel):
    barcode: str
    barcode_type: str = "EAN13"
    variant_code: str | None = None  # collega il codice alla variante (per codice variante)
    unit: str | None = None
    quantity: Decimal = Decimal(1)


class UnitIn(BaseModel):
    unit: str
    factor: Decimal = Field(gt=0)


class SupplierIn(BaseModel):
    supplier_id: uuid.UUID
    supplier_code: str | None = None
    last_cost: Decimal | None = None
    discount: Decimal | None = None
    min_order_qty: Decimal | None = None


class PriceIn(BaseModel):
    price_list_id: uuid.UUID
    min_qty: Decimal = Decimal(0)
    price: Decimal = Field(ge=0)
    discount1: Decimal | None = None
    discount2: Decimal | None = None
    discount3: Decimal | None = None


class ComponentIn(BaseModel):
    component_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class ItemIn(BaseModel):
    code: str | None = None  # vuoto = assegnato in automatico
    description: str = Field(min_length=1, max_length=200)
    long_description: str | None = None
    notes: str | None = None
    item_type: str = "articolo"
    image_url: str | None = None
    category_id: uuid.UUID | None = None
    brand_id: uuid.UUID | None = None
    family: str | None = None
    line: str | None = None
    season: str | None = None
    tags: list[str] = []
    unit: str = "PZ"
    weight_net: Decimal | None = None
    weight_gross: Decimal | None = None
    volume: Decimal | None = None
    length: Decimal | None = None
    width: Decimal | None = None
    height: Decimal | None = None
    vat_rate_id: uuid.UUID | None = None
    intrastat_code: str | None = None
    origin_country: str | None = None
    last_cost: Decimal | None = None
    avg_cost: Decimal | None = None
    standard_cost: Decimal | None = None
    stock_managed: bool = True
    lot_managed: bool = False
    serial_managed: bool = False
    shelf_life_days: int | None = None
    warranty_months: int | None = None
    plu: str | None = None
    pos_department_id: uuid.UUID | None = None
    sold_by_weight: bool = False
    min_stock: Decimal | None = None
    max_stock: Decimal | None = None
    reorder_point: Decimal | None = None
    reorder_qty: Decimal | None = None
    location: str | None = None
    preferred_supplier_id: uuid.UUID | None = None
    lead_time_days: int | None = None
    is_kit: bool = False
    custom: dict = {}
    active: bool = True
    variants: list[VariantIn] = []
    barcodes: list[BarcodeIn] = []
    units: list[UnitIn] = []
    suppliers: list[SupplierIn] = []
    prices: list[PriceIn] = []
    components: list[ComponentIn] = []


def _item_query():
    return select(Item).options(
        selectinload(Item.variants), selectinload(Item.barcodes), selectinload(Item.units),
        selectinload(Item.suppliers), selectinload(Item.prices),
        selectinload(Item.components).selectinload(ItemComponent.component),
    )


def _default_list(db: Session) -> PriceList | None:
    return db.scalar(select(PriceList).where(PriceList.is_default)) or db.scalar(select(PriceList).order_by(PriceList.code))


def _item_out(db: Session, item: Item) -> dict:
    out = row(item, ["id", *ITEM_FIELDS, "created_at", "updated_at"])
    out["created_at"] = item.created_at.isoformat() if item.created_at else None
    out["updated_at"] = item.updated_at.isoformat() if item.updated_at else None
    lists = {p.id: p for p in db.scalars(select(PriceList))}
    vat = db.get(VatRate, item.vat_rate_id) if item.vat_rate_id else None
    cost = item.last_cost or item.avg_cost or item.standard_cost
    variant_codes = {v.id: v.code for v in item.variants}
    out["variants"] = [row(v, ["id", "code", "size", "color", "format", "price_delta", "active"]) for v in item.variants]
    out["barcodes"] = [{**row(b, ["barcode", "barcode_type", "unit", "quantity"]),
                        "variant_code": variant_codes.get(b.variant_id)} for b in item.barcodes]
    out["units"] = [row(u, ["unit", "factor"]) for u in item.units]
    out["suppliers"] = []
    for sup in item.suppliers:
        party = db.get(Party, sup.supplier_id)
        out["suppliers"].append({**row(sup, ["supplier_id", "supplier_code", "last_cost", "discount", "min_order_qty"]),
                                 "supplier_name": party.name if party else None})
    out["prices"] = []
    for p in sorted(item.prices, key=lambda p: (lists[p.price_list_id].code if p.price_list_id in lists else "", p.min_qty)):
        pl = lists.get(p.price_list_id)
        net = pricing.cascade(p.price, p.discount1, p.discount2, p.discount3)
        net_ex = pricing.net_of_vat(net, vat.rate if vat else None, bool(pl and pl.vat_included))
        markup, margin = pricing.markup_margin(net_ex, cost)
        out["prices"].append({
            **row(p, ["price_list_id", "min_qty", "price", "discount1", "discount2", "discount3"]),
            "price_list_code": pl.code if pl else None, "vat_included": bool(pl and pl.vat_included),
            "net_price": s(net), "net_ex_vat": s(net_ex), "markup": s(markup), "margin": s(margin),
        })
    imgs = db.scalars(select(ItemImage).where(ItemImage.item_id == item.id).order_by(ItemImage.sort_order, ItemImage.created_at)).all()
    out["images"] = [{"id": str(i.id), **media.urls(i.file_name)} for i in imgs]
    out["components"] = [{"component_id": str(c.component_id), "quantity": s(c.quantity),
                          "code": c.component.code, "description": c.component.description} for c in item.components]
    return out


def _check_item_refs(ctx: TenantContext, body: ItemIn, item_id: uuid.UUID | None) -> None:
    db = ctx.db
    if body.item_type not in ("articolo", "servizio"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipo articolo non valido")
    if body.lot_managed and body.serial_managed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Un articolo non può avere sia lotti sia matricole")
    if not db.scalar(select(Unit).where(Unit.code == body.unit)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Unità di misura {body.unit} inesistente")
    for b in body.barcodes:
        if b.barcode_type in ("EAN13", "EAN8", "UPC") and not valid_ean(b.barcode):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Codice a barre {b.barcode} non valido (cifra di controllo)")
    variant_codes = {v.code for v in body.variants}
    if len(variant_codes) != len(body.variants):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Codici variante duplicati")
    for b in body.barcodes:
        if b.variant_code and b.variant_code not in variant_codes:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Variante {b.variant_code} inesistente")
    for c in body.components:
        if item_id and c.component_id == item_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Un kit non può contenere sé stesso")
        if db.get(Item, c.component_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Componente inesistente")
    for sup in body.suppliers:
        p = db.get(Party, sup.supplier_id)
        if p is None or not p.is_supplier:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fornitore non valido")


def _apply_item(ctx: TenantContext, item: Item, body: ItemIn) -> None:
    tid = ctx.tenant_id
    data = body.model_dump(exclude={"variants", "barcodes", "units", "suppliers", "prices", "components", "code"})
    for k, v in data.items():
        setattr(item, k, v)
    item.has_variants = bool(body.variants)
    if body.code:
        item.code = body.code.strip().upper()

    # Varianti: aggiornate per id/codice, così i codici a barre e (in futuro) le giacenze restano collegati.
    existing = {v.code: v for v in item.variants}
    keep = []
    for v in body.variants:
        obj = existing.get(v.code) or ItemVariant(tenant_id=tid, code=v.code)
        for k in ("size", "color", "format", "price_delta", "active"):
            setattr(obj, k, getattr(v, k))
        keep.append(obj)
    item.variants = keep
    ctx.db.flush()
    vmap = {v.code: v.id for v in item.variants}

    # Svuota e scrive prima di reinserire: evita conflitti sui vincoli unici (stesso barcode, stesso scaglione).
    for coll in (item.barcodes, item.units, item.suppliers, item.prices, item.components):
        coll.clear()
    ctx.db.flush()
    item.barcodes = [ItemBarcode(tenant_id=tid, barcode=b.barcode.strip(), barcode_type=b.barcode_type,
                                 variant_id=vmap.get(b.variant_code) if b.variant_code else None,
                                 unit=b.unit, quantity=b.quantity) for b in body.barcodes]
    item.units = [ItemUnit(tenant_id=tid, unit=u.unit, factor=u.factor) for u in body.units]
    item.suppliers = [ItemSupplier(tenant_id=tid, **sup.model_dump()) for sup in body.suppliers]
    item.prices = [ItemPrice(tenant_id=tid, **p.model_dump()) for p in body.prices]
    item.components = [ItemComponent(tenant_id=tid, component_id=c.component_id, quantity=c.quantity)
                       for c in body.components]
    item.is_kit = bool(body.components) or body.is_kit


@router.get("/articoli")
def list_items(
    q: str | None = None,
    category_id: uuid.UUID | None = None,
    brand_id: uuid.UUID | None = None,
    supplier_id: uuid.UUID | None = None,
    active: bool | None = True,
    under_min: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(reader),
):
    db = ctx.db
    stmt = select(Item)
    if q:
        like = f"%{q.strip()}%"
        barcode_items = select(ItemBarcode.item_id).where(ItemBarcode.barcode == q.strip())
        supplier_code_items = select(ItemSupplier.item_id).where(ItemSupplier.supplier_code.ilike(like))
        stmt = stmt.where(or_(Item.code.ilike(like), Item.description.ilike(like), Item.id.in_(barcode_items),
                              Item.id.in_(supplier_code_items), Item.tags.any(q.strip().lower())))
    if category_id:
        children = select(Category.id).where(Category.parent_id == category_id)
        stmt = stmt.where(or_(Item.category_id == category_id, Item.category_id.in_(children)))
    if brand_id:
        stmt = stmt.where(Item.brand_id == brand_id)
    if supplier_id:
        stmt = stmt.where(or_(Item.preferred_supplier_id == supplier_id,
                              Item.id.in_(select(ItemSupplier.item_id).where(ItemSupplier.supplier_id == supplier_id))))
    if active is not None:
        stmt = stmt.where(Item.active.is_(active))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Item.code).offset((page - 1) * page_size).limit(page_size)).all()

    default = _default_list(db)
    ids = [i.id for i in items]
    prices = {}
    if default and ids:
        for p in db.scalars(select(ItemPrice).where(ItemPrice.item_id.in_(ids), ItemPrice.price_list_id == default.id,
                                                    ItemPrice.min_qty == 0)):
            prices[p.item_id] = p.price
    cats = {c.id: c.name for c in db.scalars(select(Category))}
    brands = {b.id: b.name for b in db.scalars(select(Brand))}
    thumbs = {}
    if ids:
        for im in db.scalars(select(ItemImage).where(ItemImage.item_id.in_(ids)).order_by(ItemImage.sort_order.desc(), ItemImage.created_at.desc())):
            thumbs[im.item_id] = media.urls(im.file_name)["thumb_url"]  # l'ultima scritta è la principale
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "price_list": default.code if default else None,
        "rows": [
            {"id": str(i.id), "code": i.code, "description": i.description, "item_type": i.item_type, "unit": i.unit,
             "category": cats.get(i.category_id), "brand": brands.get(i.brand_id), "price": s(prices.get(i.id)),
             "last_cost": s(i.last_cost), "lot_managed": i.lot_managed, "serial_managed": i.serial_managed,
             "has_variants": i.has_variants, "is_kit": i.is_kit, "active": i.active, "thumb_url": thumbs.get(i.id)}
            for i in items
        ],
    }


@router.get("/articoli/nuovo-codice")
def new_item_code(ctx: TenantContext = Depends(reader)):
    return {"code": next_code(ctx.db, Item, "ART")}


@router.get("/articoli/genera-barcode")
def generate_barcode(ctx: TenantContext = Depends(writer)):
    """EAN-13 interno (prefisso 200) non ancora usato da questa azienda."""
    used = set(ctx.db.scalars(select(ItemBarcode.barcode).where(ItemBarcode.barcode.like("200%"))))
    n = len(used) + 1
    while (code := make_internal_ean13("200", n)) in used:
        n += 1
    return {"barcode": code}


@router.get("/articoli/cerca-barcode/{barcode}")
def lookup_barcode(barcode: str, ctx: TenantContext = Depends(reader)):
    """Lettura da scanner: restituisce articolo, variante e quantità del codice (es. cartone da 12)."""
    b = ctx.db.scalar(select(ItemBarcode).where(ItemBarcode.barcode == barcode.strip()))
    if b is None:
        item = ctx.db.scalar(select(Item).where(func.upper(Item.code) == barcode.strip().upper()))
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Codice non trovato")
        return {"item_id": str(item.id), "code": item.code, "description": item.description, "variant_id": None, "quantity": "1"}
    item = ctx.db.get(Item, b.item_id)
    variant = ctx.db.get(ItemVariant, b.variant_id) if b.variant_id else None
    return {"item_id": str(item.id), "code": item.code, "description": item.description,
            "variant_id": str(variant.id) if variant else None, "variant_code": variant.code if variant else None,
            "quantity": s(b.quantity)}


@router.get("/articoli/{item_id}")
def get_item(item_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    item = ctx.db.scalar(_item_query().where(Item.id == item_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    return _item_out(ctx.db, item)


@router.post("/articoli", status_code=201)
def create_item(body: ItemIn, ctx: TenantContext = Depends(writer)):
    _check_item_refs(ctx, body, None)
    item = Item(tenant_id=ctx.tenant_id, code=(body.code or next_code(ctx.db, Item, "ART")).strip().upper())
    ctx.db.add(item)
    _apply_item(ctx, item, body)
    flush_or_conflict(ctx.db, "Codice articolo, variante o codice a barre già esistente")
    audit(ctx.db, "item", "creazione", item.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, admin_id=ctx.impersonated_by,
          after={"code": item.code, "description": item.description})
    ctx.db.expire(item)
    return get_item(item.id, ctx)


@router.put("/articoli/{item_id}")
def update_item(item_id: uuid.UUID, body: ItemIn, ctx: TenantContext = Depends(writer)):
    item = ctx.db.scalar(_item_query().where(Item.id == item_id))
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    _check_item_refs(ctx, body, item_id)
    before = {"code": item.code, "description": item.description, "last_cost": s(item.last_cost)}
    _apply_item(ctx, item, body)
    flush_or_conflict(ctx.db, "Codice articolo, variante o codice a barre già esistente")
    audit(ctx.db, "item", "modifica", item.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, admin_id=ctx.impersonated_by,
          before=before, after={"code": item.code, "description": item.description, "last_cost": s(item.last_cost)})
    ctx.db.expire(item)
    return get_item(item.id, ctx)


@router.post("/articoli/{item_id}/duplica", status_code=201)
def duplicate_item(item_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    src = get_item(item_id, ctx)
    body = ItemIn(**{**src, "code": None, "description": src["description"] + " (copia)", "barcodes": [],
                     "variants": [{**v, "code": v["code"] + "-C", "id": None} for v in src["variants"]]})
    return create_item(body, ctx)


@router.delete("/articoli/{item_id}")
def deactivate_item(item_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    """Gli articoli non si cancellano (servono allo storico dei documenti): si disattivano."""
    item = ctx.db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    item.active = False
    audit(ctx.db, "item", "disattivazione", item.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id)
    return {"ok": True}


# ====================================================================== clienti e fornitori

PARTY_FIELDS = [
    "code", "is_customer", "is_supplier", "person_type", "name", "first_name", "last_name", "vat_number", "tax_code",
    "sdi_code", "pec", "email", "phone", "mobile", "website", "address", "street_number", "zip_code", "city",
    "province", "country", "iban", "bank_name", "payment_term_id", "price_list_id", "discount1", "discount2",
    "credit_limit", "credit_policy", "split_payment", "vat_rate_id", "customer_category_id", "exemption_letter", "notes", "custom", "active",
]


class AddressIn(BaseModel):
    id: uuid.UUID | None = None  # presente = destinazione esistente da aggiornare (i documenti la citano)
    label: str
    address: str
    zip_code: str | None = None
    city: str | None = None
    province: str | None = None
    country: str = "IT"
    is_default: bool = False


class PartyIn(BaseModel):
    code: str | None = None
    is_customer: bool = True
    is_supplier: bool = False
    person_type: str = "azienda"
    name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    vat_number: str | None = None
    tax_code: str | None = None
    sdi_code: str | None = None
    pec: str | None = None
    email: str | None = None
    phone: str | None = None
    mobile: str | None = None
    website: str | None = None
    address: str | None = None
    street_number: str | None = None
    zip_code: str | None = None
    city: str | None = None
    province: str | None = None
    country: str = "IT"
    iban: str | None = None
    bank_name: str | None = None
    payment_term_id: uuid.UUID | None = None
    price_list_id: uuid.UUID | None = None
    discount1: Decimal | None = None
    discount2: Decimal | None = None
    credit_limit: Decimal | None = None
    credit_policy: str = "blocca"
    split_payment: bool = False
    vat_rate_id: uuid.UUID | None = None
    customer_category_id: uuid.UUID | None = None
    exemption_letter: str | None = None
    notes: str | None = None
    custom: dict = {}
    active: bool = True
    addresses: list[AddressIn] = []


def _normalize_party(body: PartyIn) -> dict:
    data = body.model_dump(exclude={"addresses"})
    for k in ("vat_number", "tax_code", "sdi_code", "province", "country", "iban"):
        if data.get(k):
            data[k] = re.sub(r"\s", "", data[k]).upper()
    if data.get("vat_number", "") and data["vat_number"].startswith("IT") and data["country"] == "IT":
        data["vat_number"] = data["vat_number"][2:]
    for k in ("email", "pec"):
        if data.get(k):
            data[k] = data[k].strip().lower()
    if data["person_type"] == "privato" and not data.get("name"):
        data["name"] = " ".join(x for x in (data.get("last_name"), data.get("first_name")) if x)
    if not data.get("name"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica la ragione sociale o nome e cognome")
    if data["person_type"] not in ("azienda", "privato", "pa"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipo soggetto non valido")
    if data["credit_policy"] not in ("blocca", "avvisa"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Comportamento fido non valido")
    if not data["is_customer"] and not data["is_supplier"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica se è cliente, fornitore o entrambi")
    if data["person_type"] == "privato" and not data.get("sdi_code"):
        data["sdi_code"] = "0000000"  # privati: fattura nel cassetto fiscale
    problems = party_problems(data)
    if problems:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, {"code": "dati_non_validi", "message": "; ".join(problems)})
    return data


def _party_out(db: Session, p: Party) -> dict:
    out = row(p, ["id", *PARTY_FIELDS])
    out["addresses"] = [row(a, ["id", "label", "address", "zip_code", "city", "province", "country", "is_default"]) for a in p.addresses]
    out["warnings"] = []
    if p.vat_number:
        dup = db.scalar(select(func.count()).select_from(Party).where(Party.vat_number == p.vat_number, Party.id != p.id))
        if dup:
            out["warnings"].append("Esiste un'altra anagrafica con la stessa partita IVA")
    if p.is_customer and p.person_type != "privato" and not p.sdi_code and not p.pec:
        out["warnings"].append("Manca codice destinatario SDI o PEC per la fattura elettronica")
    return out


@router.get("/soggetti")
def list_parties(
    tipo: str = Query("clienti", pattern="^(clienti|fornitori|tutti)$"),
    q: str | None = None,
    active: bool | None = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    ctx: TenantContext = Depends(reader),
):
    stmt = select(Party)
    if tipo == "clienti":
        stmt = stmt.where(Party.is_customer)
    elif tipo == "fornitori":
        stmt = stmt.where(Party.is_supplier)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Party.name.ilike(like), Party.code.ilike(like), Party.vat_number.ilike(like),
                              Party.tax_code.ilike(like), Party.city.ilike(like), Party.email.ilike(like)))
    if active is not None:
        stmt = stmt.where(Party.active.is_(active))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = ctx.db.scalars(stmt.order_by(Party.name).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "rows": [
        {"id": str(p.id), "code": p.code, "name": p.name, "vat_number": p.vat_number, "tax_code": p.tax_code,
         "city": p.city, "province": p.province, "phone": p.phone, "email": p.email, "is_customer": p.is_customer,
         "is_supplier": p.is_supplier, "person_type": p.person_type, "active": p.active} for p in rows]}


@router.get("/soggetti/{party_id}")
def get_party(party_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    p = ctx.db.scalar(select(Party).where(Party.id == party_id).options(selectinload(Party.addresses)))
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anagrafica non trovata")
    return _party_out(ctx.db, p)


def _party_prefix(data: dict) -> str:
    return "C" if data["is_customer"] else "F"


@router.post("/soggetti", status_code=201)
def create_party(body: PartyIn, ctx: TenantContext = Depends(writer)):
    data = _normalize_party(body)
    data["code"] = (data.get("code") or next_code(ctx.db, Party, _party_prefix(data))).strip().upper()
    p = Party(tenant_id=ctx.tenant_id, **data)
    p.addresses = [PartyAddress(tenant_id=ctx.tenant_id, **a.model_dump(exclude={"id"})) for a in body.addresses]
    ctx.db.add(p)
    flush_or_conflict(ctx.db, "Codice anagrafica già esistente")
    audit(ctx.db, "party", "creazione", p.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, admin_id=ctx.impersonated_by,
          after={"code": p.code, "name": p.name})
    return get_party(p.id, ctx)


@router.put("/soggetti/{party_id}")
def update_party(party_id: uuid.UUID, body: PartyIn, ctx: TenantContext = Depends(writer)):
    p = ctx.db.scalar(select(Party).where(Party.id == party_id).options(selectinload(Party.addresses)))
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anagrafica non trovata")
    data = _normalize_party(body)
    if not data.get("code"):
        data["code"] = p.code
    before = {"name": p.name, "vat_number": p.vat_number}
    for k, v in data.items():
        setattr(p, k, v)
    existing = {a.id: a for a in p.addresses}
    keep = []
    for a in body.addresses:
        fields = a.model_dump(exclude={"id"})
        if a.id and a.id in existing:
            for k, v in fields.items():
                setattr(existing[a.id], k, v)
            keep.append(existing[a.id])
        else:
            keep.append(PartyAddress(tenant_id=ctx.tenant_id, **fields))
    p.addresses = keep
    flush_or_conflict(ctx.db, "Codice anagrafica già esistente")
    audit(ctx.db, "party", "modifica", p.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, admin_id=ctx.impersonated_by,
          before=before, after={"name": p.name, "vat_number": p.vat_number})
    ctx.db.expire(p)
    return get_party(p.id, ctx)


@router.delete("/soggetti/{party_id}")
def deactivate_party(party_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    p = ctx.db.get(Party, party_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anagrafica non trovata")
    p.active = False
    return {"ok": True}


# ====================================================================== import / export CSV

ITEM_EXPORT = ["code", "description", "long_description", "unit", "category", "brand", "vat", "price", "last_cost",
               "avg_cost", "barcode", "supplier", "supplier_code", "min_stock", "location", "family", "season",
               "weight_net", "lot_managed", "serial_managed", "warranty_months"]
PARTY_EXPORT = ["code", "name", "person_type", "vat_number", "tax_code", "sdi_code", "pec", "email", "phone", "mobile",
                "address", "zip_code", "city", "province", "country", "iban", "is_customer", "is_supplier"]
# compatibilità con i nomi usati nei CSV della prima versione
ITEM_CSV, PARTY_CSV = ITEM_EXPORT, PARTY_EXPORT


def _csv_response(rows: list[list], header: list[str], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows([[_it(v) if isinstance(v, Decimal) else ("" if v is None else v) for v in r] for r in rows])
    data = "﻿" + buf.getvalue()  # BOM: Excel riconosce l'UTF-8 e gli accenti
    return StreamingResponse(iter([data]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _items_table(db: Session) -> list[list]:
    default = _default_list(db)
    cats = {c.id: c.name for c in db.scalars(select(Category))}
    brands = {b.id: b.name for b in db.scalars(select(Brand))}
    vats = {v.id: v.code for v in db.scalars(select(VatRate))}
    parties = {p.id: p.name for p in db.scalars(select(Party).where(Party.is_supplier))}
    out = []
    for i in db.scalars(_item_query().where(Item.active).order_by(Item.code)):
        price = next((p.price for p in i.prices if default and p.price_list_id == default.id and p.min_qty == 0), None)
        sup = i.suppliers[0] if i.suppliers else None
        out.append([i.code, i.description, i.long_description, i.unit, cats.get(i.category_id), brands.get(i.brand_id),
                    vats.get(i.vat_rate_id), price, i.last_cost, i.avg_cost, i.barcodes[0].barcode if i.barcodes else None,
                    parties.get(sup.supplier_id) if sup else None, sup.supplier_code if sup else None, i.min_stock,
                    i.location, i.family, i.season, i.weight_net, "si" if i.lot_managed else None,
                    "si" if i.serial_managed else None, i.warranty_months])
    return out


def _parties_table(db: Session) -> list[list]:
    out = []
    for p in db.scalars(select(Party).where(Party.active).order_by(Party.code)):
        out.append([("si" if getattr(p, f) else None) if isinstance(getattr(p, f), bool) else getattr(p, f) for f in PARTY_EXPORT])
    return out


def _labels(fields: list[str], defs: dict) -> list[str]:
    return [defs[f][0] if f in defs else f for f in fields]


@router.get("/articoli-export.csv")
def export_items(ctx: TenantContext = Depends(reader)):
    return _csv_response(_items_table(ctx.db), ITEM_EXPORT, "articoli.csv")


@router.get("/articoli-export.xlsx")
def export_items_xlsx(ctx: TenantContext = Depends(reader)):
    money = {ITEM_EXPORT.index(k) for k in ("price", "last_cost", "avg_cost")}
    return tabular.xlsx_response("Articoli", _labels(ITEM_EXPORT, tabular.ITEM_FIELDS | {"avg_cost": ("Costo medio", [])}),
                                 _items_table(ctx.db), "articoli.xlsx", money)


@router.get("/soggetti-export.csv")
def export_parties(ctx: TenantContext = Depends(reader)):
    return _csv_response(_parties_table(ctx.db), PARTY_EXPORT, "clienti-fornitori.csv")


@router.get("/soggetti-export.xlsx")
def export_parties_xlsx(ctx: TenantContext = Depends(reader)):
    return tabular.xlsx_response("Clienti e fornitori", _labels(PARTY_EXPORT, tabular.PARTY_FIELDS),
                                 _parties_table(ctx.db), "clienti-fornitori.xlsx")


def _it(v) -> str:
    return "" if v is None else str(v).replace(".", ",")


def _dec(v: str | None) -> Decimal | None:
    if v is None or str(v).strip() == "":
        return None
    t = str(v).strip().replace("€", "").replace(" ", "")
    try:
        return Decimal(t.replace(".", "").replace(",", ".") if "," in t else t)
    except InvalidOperation:
        raise ValueError(f"numero non valido: {v}") from None


def _yes(v: str | None) -> bool:
    return str(v or "").strip().lower() in ("si", "sì", "s", "1", "true", "x", "yes", "vero")


def _read_csv(text: str) -> list[dict]:
    headers, rows = tabular.read_table("dati.csv", text.encode("utf-8"))
    keys = [h.strip().lower() for h in headers]
    return [dict(zip(keys, r)) for r in rows]


class CsvIn(BaseModel):
    content: str | None = None  # CSV con le intestazioni dell'export
    rows: list[dict] | None = None  # oppure righe già abbinate ai campi (import guidato da Excel)
    update_existing: bool = True


def _import_rows(body: CsvIn) -> list[dict]:
    if body.rows is not None:
        return [{k: ("" if v is None else str(v).strip()) for k, v in r.items()} for r in body.rows[: tabular.MAX_ROWS]]
    if body.content:
        return _read_csv(body.content)
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nessun dato da importare")


@router.post("/import/anteprima")
async def import_preview(tipo: str = Query(pattern="^(articoli|soggetti)$"), file: UploadFile = File(...),
                         ctx: TenantContext = Depends(writer)):
    """Primo passo dell'import guidato: legge Excel o CSV, propone l'abbinamento colonne → campi."""
    headers, rows = tabular.read_table(file.filename or "", await file.read())
    fields = tabular.ITEM_FIELDS if tipo == "articoli" else tabular.PARTY_FIELDS
    return {
        "headers": headers,
        "sample": rows[:8],
        "rows": rows,
        "total": len(rows),
        "mapping": tabular.suggest_mapping(headers, fields),
        "fields": [{"key": k, "label": v[0]} for k, v in fields.items()],
        "required": ["description"] if tipo == "articoli" else ["name"],
    }


def _find_or_create(db: Session, cache: dict, model, tenant_id, name: str, **extra):
    key = name.strip().lower()
    obj = cache.get(key)
    if obj is None:
        obj = model(tenant_id=tenant_id, name=name.strip()[:120], **extra)
        db.add(obj)
        db.flush()
        cache[key] = obj
    return obj


@router.post("/articoli-import")
def import_items(body: CsvIn, ctx: TenantContext = Depends(writer)):
    """Importa articoli (CSV o righe abbinate da Excel). Crea al volo categorie, marche e fornitori."""
    db = ctx.db
    default = _default_list(db)
    vats = {v.code: v for v in db.scalars(select(VatRate))}
    vats_by_rate = {}
    for v in vats.values():
        if not v.nature:
            vats_by_rate.setdefault(Decimal(v.rate).normalize(), v)
    units = {u.code for u in db.scalars(select(Unit))}
    cats = {(c.parent_id, c.name.lower()): c for c in db.scalars(select(Category))}
    brands = {b.name.lower(): b for b in db.scalars(select(Brand))}
    suppliers = {p.name.lower(): p for p in db.scalars(select(Party).where(Party.is_supplier))}
    created = updated = 0
    errors = []
    for n, r in enumerate(_import_rows(body), start=2):
        savepoint = db.begin_nested()
        try:
            if not r.get("description"):
                raise ValueError("descrizione mancante")
            code = (r.get("code") or "").strip().upper() or next_code(db, Item, "ART")
            item = db.scalar(_item_query().where(Item.code == code))
            if item and not body.update_existing:
                savepoint.rollback()
                continue
            is_new = item is None
            if is_new:
                item = Item(tenant_id=ctx.tenant_id, code=code[:40], tags=[], custom={})
                db.add(item)
            item.description = r["description"][:200]
            if r.get("long_description"):
                item.long_description = r["long_description"]
            unit = (r.get("unit") or item.unit or "PZ").upper()
            item.unit = unit if unit in units else "PZ"
            if r.get("category"):
                parent = cats.get((None, r["category"].strip().lower()))
                if parent is None:
                    parent = Category(tenant_id=ctx.tenant_id, name=r["category"].strip()[:120])
                    db.add(parent)
                    db.flush()
                    cats[(None, parent.name.lower())] = parent
                target = parent
                if r.get("subcategory"):
                    sub = cats.get((parent.id, r["subcategory"].strip().lower()))
                    if sub is None:
                        sub = Category(tenant_id=ctx.tenant_id, name=r["subcategory"].strip()[:120], parent_id=parent.id)
                        db.add(sub)
                        db.flush()
                        cats[(parent.id, sub.name.lower())] = sub
                    target = sub
                item.category_id = target.id
            if r.get("brand"):
                item.brand_id = _find_or_create(db, brands, Brand, ctx.tenant_id, r["brand"]).id
            vat_raw = (r.get("vat") or "").upper().replace("%", "").strip()
            if vat_raw in vats:
                item.vat_rate_id = vats[vat_raw].id
            elif vat_raw and _dec(vat_raw) is not None and _dec(vat_raw).normalize() in vats_by_rate:
                item.vat_rate_id = vats_by_rate[_dec(vat_raw).normalize()].id
            elif not item.vat_rate_id and "22" in vats:
                item.vat_rate_id = vats["22"].id
            for f in ("last_cost", "min_stock", "weight_net"):
                if r.get(f):
                    setattr(item, f, _dec(r[f]))
            if r.get("last_cost") and not item.avg_cost:
                item.avg_cost = item.last_cost
            for f in ("location", "family", "season"):
                if r.get(f):
                    setattr(item, f, r[f][:80])
            if r.get("lot_managed"):
                item.lot_managed = _yes(r["lot_managed"])
            if r.get("serial_managed"):
                item.serial_managed = _yes(r["serial_managed"]) and not item.lot_managed
            if r.get("warranty_months"):
                item.warranty_months = int(_dec(r["warranty_months"]))
            db.flush()
            if r.get("price") and default:
                price = _dec(r["price"])
                existing = next((p for p in (item.prices if not is_new else []) if p.price_list_id == default.id and p.min_qty == 0), None)
                if existing:
                    existing.price = price
                else:
                    db.add(ItemPrice(tenant_id=ctx.tenant_id, item_id=item.id, price_list_id=default.id, min_qty=0, price=price))
            if r.get("barcode") and not db.scalar(select(ItemBarcode).where(ItemBarcode.barcode == r["barcode"])):
                db.add(ItemBarcode(tenant_id=ctx.tenant_id, item_id=item.id, barcode=r["barcode"][:60],
                                   barcode_type="EAN13" if valid_ean(r["barcode"]) else "CODE128"))
            if r.get("supplier"):
                sup = suppliers.get(r["supplier"].strip().lower())
                if sup is None:
                    sup = Party(tenant_id=ctx.tenant_id, code=next_code(db, Party, "F"), name=r["supplier"].strip()[:200],
                                is_customer=False, is_supplier=True, person_type="azienda", country="IT", custom={})
                    db.add(sup)
                    db.flush()
                    suppliers[sup.name.lower()] = sup
                link = db.scalar(select(ItemSupplier).where(ItemSupplier.item_id == item.id, ItemSupplier.supplier_id == sup.id))
                if link is None:
                    link = ItemSupplier(tenant_id=ctx.tenant_id, item_id=item.id, supplier_id=sup.id)
                    db.add(link)
                link.supplier_code = r.get("supplier_code") or link.supplier_code
                link.last_cost = item.last_cost
                item.preferred_supplier_id = item.preferred_supplier_id or sup.id
            db.flush()
            savepoint.commit()
            created += is_new
            updated += not is_new
        except Exception as exc:  # una riga sbagliata non blocca le altre
            savepoint.rollback()
            detail = exc.detail if isinstance(exc, HTTPException) else exc
            errors.append(f"Riga {n}: {detail}")
    return {"created": created, "updated": updated, "errors": errors[:100], "errors_total": len(errors)}


@router.post("/soggetti-import")
def import_parties(body: CsvIn, tipo: str = Query("clienti", pattern="^(clienti|fornitori)$"), ctx: TenantContext = Depends(writer)):
    db = ctx.db
    created = updated = 0
    errors = []
    for n, r in enumerate(_import_rows(body), start=2):
        savepoint = db.begin_nested()
        try:
            data = {k: r.get(k) or None for k in PARTY_EXPORT if k not in ("is_customer", "is_supplier")}
            data["is_customer"] = _yes(r["is_customer"]) if r.get("is_customer") else tipo == "clienti"
            data["is_supplier"] = _yes(r["is_supplier"]) if r.get("is_supplier") else tipo == "fornitori"
            pt = (data.get("person_type") or "azienda").lower()
            data["person_type"] = "privato" if pt.startswith("priv") else "pa" if pt in ("pa", "ente", "pubblica amministrazione") else "azienda"
            data["country"] = data.get("country") or "IT"
            norm = _normalize_party(PartyIn(**data))
            code = (norm.get("code") or "").upper()
            p = db.scalar(select(Party).where(Party.code == code)) if code else None
            if p is None and norm.get("vat_number"):
                p = db.scalar(select(Party).where(Party.vat_number == norm["vat_number"]))
            if p and not body.update_existing:
                savepoint.rollback()
                continue
            if p is None:
                norm["code"] = code or next_code(db, Party, _party_prefix(norm))
                db.add(Party(tenant_id=ctx.tenant_id, **norm))
                created += 1
            else:
                norm["code"] = p.code
                for k, v in norm.items():
                    setattr(p, k, v)
                updated += 1
            db.flush()
            savepoint.commit()
        except HTTPException as exc:
            savepoint.rollback()
            detail = exc.detail["message"] if isinstance(exc.detail, dict) else exc.detail
            errors.append(f"Riga {n}: {detail}")
        except Exception as exc:
            savepoint.rollback()
            errors.append(f"Riga {n}: {exc}")
    return {"created": created, "updated": updated, "errors": errors[:100], "errors_total": len(errors)}


# ====================================================================== prezzo da applicare


@router.get("/prezzo")
def price_lookup(item_id: uuid.UUID, party_id: uuid.UUID | None = None, qty: Decimal = Decimal(1),
                 variant_id: uuid.UUID | None = None, on: date | None = None, ctx: TenantContext = Depends(reader)):
    """Prezzo che verrà proposto in vendita, con la sua origine (prezzo cliente, promozione o listino)."""
    item = ctx.db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    party = ctx.db.get(Party, party_id) if party_id else None
    res = resolve_price(ctx.db, item, party, qty, on, variant_id).to_dict()
    if ctx.user.role != "cassa":  # i costi non si mostrano alla cassa
        res["last_cost"] = s(item.last_cost)
        res["avg_cost"] = s(item.avg_cost)
        cost = item.last_cost or item.avg_cost
        if cost and res["unit_price"]:
            markup, margin = pricing.markup_margin(Decimal(res["unit_price"]), cost)
            res["markup"], res["margin"] = s(markup), s(margin)
    return res


# ====================================================================== prezzi netti per cliente


class CustomerPriceIn(BaseModel):
    item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    min_qty: Decimal = Decimal(0)
    net_price: Decimal = Field(ge=0)
    valid_from: date | None = None
    valid_to: date | None = None
    notes: str | None = None


def _cp_out(db: Session, rows: list[CustomerPrice]) -> list[dict]:
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({r.item_id for r in rows})))} if rows else {}
    variants = {v.id: v.code for v in db.scalars(select(ItemVariant).where(ItemVariant.id.in_({r.variant_id for r in rows if r.variant_id})))} if rows else {}
    out = []
    for r in rows:
        it = items.get(r.item_id)
        default = resolve_price(db, it, None).unit_price if it else None
        out.append({**row(r, ["id", "party_id", "item_id", "variant_id", "min_qty", "net_price", "valid_from", "valid_to", "notes"]),
                    "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                    "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                    "item_code": it.code if it else None, "item_description": it.description if it else None,
                    "variant_code": variants.get(r.variant_id), "list_price": s(default),
                    "last_cost": s(it.last_cost) if it else None})
    return sorted(out, key=lambda x: (x["item_code"] or "", Decimal(x["min_qty"])))


def _party_or_404(db: Session, party_id: uuid.UUID) -> Party:
    p = db.get(Party, party_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente non trovato")
    return p


@router.get("/soggetti/{party_id}/prezzi")
def customer_prices(party_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    _party_or_404(ctx.db, party_id)
    return _cp_out(ctx.db, ctx.db.scalars(select(CustomerPrice).where(CustomerPrice.party_id == party_id)).all())


@router.put("/soggetti/{party_id}/prezzi")
def set_customer_prices(party_id: uuid.UUID, body: list[CustomerPriceIn], ctx: TenantContext = Depends(writer)):
    """Sostituisce l'intero listino personalizzato del cliente."""
    p = _party_or_404(ctx.db, party_id)
    for r in body:
        if r.valid_from and r.valid_to and r.valid_to < r.valid_from:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Data di fine validità precedente all'inizio")
        if ctx.db.get(Item, r.item_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Articolo inesistente")
    for old in ctx.db.scalars(select(CustomerPrice).where(CustomerPrice.party_id == party_id)):
        ctx.db.delete(old)
    ctx.db.flush()
    for r in body:
        ctx.db.add(CustomerPrice(tenant_id=ctx.tenant_id, party_id=party_id, **r.model_dump()))
    ctx.db.flush()
    audit(ctx.db, "customer_prices", "modifica", p.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          admin_id=ctx.impersonated_by, after={"righe": len(body)})
    return customer_prices(party_id, ctx)


@router.post("/soggetti/{party_id}/prezzi/copia-da/{source_id}")
def copy_customer_prices(party_id: uuid.UUID, source_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    """Aggiunge al cliente i prezzi netti di un altro cliente (quelli già presenti per lo stesso articolo restano)."""
    _party_or_404(ctx.db, party_id)
    have = {(r.item_id, r.variant_id, r.min_qty) for r in ctx.db.scalars(select(CustomerPrice).where(CustomerPrice.party_id == party_id))}
    n = 0
    for r in ctx.db.scalars(select(CustomerPrice).where(CustomerPrice.party_id == source_id)).all():
        if (r.item_id, r.variant_id, r.min_qty) in have:
            continue
        ctx.db.add(CustomerPrice(tenant_id=ctx.tenant_id, party_id=party_id, item_id=r.item_id, variant_id=r.variant_id,
                                 min_qty=r.min_qty, net_price=r.net_price, valid_from=r.valid_from, valid_to=r.valid_to))
        n += 1
    ctx.db.flush()
    return {"copied": n}


class PercentIn(BaseModel):
    percent: Decimal = Field(ge=-90, le=500)


@router.post("/soggetti/{party_id}/prezzi/variazione")
def change_customer_prices(party_id: uuid.UUID, body: PercentIn, ctx: TenantContext = Depends(writer)):
    """Aumenta o riduce in percentuale tutti i prezzi netti del cliente (es. adeguamento annuale)."""
    _party_or_404(ctx.db, party_id)
    rows = ctx.db.scalars(select(CustomerPrice).where(CustomerPrice.party_id == party_id)).all()
    for r in rows:
        r.net_price = (Decimal(r.net_price) * (Decimal(100) + body.percent) / Decimal(100)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return {"updated": len(rows)}


@router.get("/articoli/{item_id}/prezzi-clienti")
def item_customer_prices(item_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    rows = ctx.db.scalars(select(CustomerPrice).where(CustomerPrice.item_id == item_id)).all()
    names = {p.id: p.name for p in ctx.db.scalars(select(Party).where(Party.id.in_({r.party_id for r in rows})))} if rows else {}
    return [{**x, "party_name": names.get(uuid.UUID(x["party_id"]))} for x in _cp_out(ctx.db, rows)]


# ====================================================================== promozioni


class PromotionIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    date_from: date
    date_to: date
    active: bool = True
    item_scope: str = "articoli"
    category_ids: list[uuid.UUID] = []
    item_ids: list[uuid.UUID] = []
    customer_scope: str = "tutti"
    customer_category_ids: list[uuid.UUID] = []
    party_ids: list[uuid.UUID] = []
    price_type: str = "sconto"
    value: Decimal = Field(ge=0)
    vat_included: bool = True
    min_qty: Decimal = Decimal(0)
    mechanic: str = "prezzo"
    buy_qty: int | None = Field(None, ge=2, le=99)
    pay_qty: int | None = Field(None, ge=1, le=98)
    threshold: Decimal | None = Field(None, ge=0)
    notes: str | None = None


PROMO_FIELDS = list(PromotionIn.model_fields)


def _check_promo(body: PromotionIn) -> None:
    if body.date_to < body.date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La data di fine è precedente all'inizio")
    if body.item_scope not in ("tutti", "categorie", "articoli") or body.customer_scope not in ("tutti", "categorie", "clienti"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Ambito non valido")
    if body.price_type not in ("prezzo", "sconto", "importo"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipo di prezzo non valido")
    if body.mechanic not in ("prezzo", "nxm", "nesimo", "soglia"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipo di promozione non valido")
    if body.mechanic != "prezzo" and body.customer_scope != "tutti":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Le promozioni di cassa valgono per tutti i clienti")
    if body.mechanic == "nxm" and not (body.buy_qty and body.pay_qty and body.pay_qty < body.buy_qty):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica quanti pezzi si prendono e quanti si pagano (es. 3x2)")
    if body.mechanic == "nesimo" and (not body.buy_qty or body.price_type != "sconto" or not 0 < body.value <= 100):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica ogni quanti pezzi scatta lo sconto e la percentuale (es. 2° pezzo al 50%)")
    if body.mechanic == "soglia" and (body.threshold is None or body.price_type not in ("sconto", "importo") or body.value <= 0):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica la spesa minima e lo sconto (in % o in euro)")
    if body.mechanic != "nxm":
        body.pay_qty = None
    if body.mechanic not in ("nxm", "nesimo"):
        body.buy_qty = None
    if body.mechanic != "soglia":
        body.threshold = None
    if body.price_type == "sconto" and body.value > 100:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Lo sconto non può superare il 100%")
    if body.item_scope == "categorie" and not body.category_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Scegli almeno una categoria di articoli")
    if body.item_scope == "articoli" and not body.item_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Scegli almeno un articolo")
    if body.customer_scope == "categorie" and not body.customer_category_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Scegli almeno una categoria di clienti")
    if body.customer_scope == "clienti" and not body.party_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Scegli almeno un cliente")


def _promo_out(db: Session, p: Promotion) -> dict:
    today = date.today()
    state = "scaduta" if p.date_to < today else "futura" if p.date_from > today else "attiva"
    if not p.active:
        state = "sospesa"
    out = {f: s(getattr(p, f)) for f in PROMO_FIELDS}
    out.update({"id": str(p.id), "date_from": p.date_from.isoformat(), "date_to": p.date_to.isoformat(), "state": state,
                "category_ids": [str(x) for x in p.category_ids or []], "item_ids": [str(x) for x in p.item_ids or []],
                "customer_category_ids": [str(x) for x in p.customer_category_ids or []],
                "party_ids": [str(x) for x in p.party_ids or []]})
    if p.item_ids:
        out["items"] = [{"id": str(i.id), "code": i.code, "description": i.description}
                        for i in db.scalars(select(Item).where(Item.id.in_(p.item_ids)))]
    if p.party_ids:
        out["parties"] = [{"id": str(x.id), "name": x.name} for x in db.scalars(select(Party).where(Party.id.in_(p.party_ids)))]
    return out


@router.get("/promozioni")
def list_promotions(stato: str = "tutte", ctx: TenantContext = Depends(reader)):
    rows = [_promo_out(ctx.db, p) for p in ctx.db.scalars(select(Promotion).order_by(Promotion.date_from.desc()))]
    return rows if stato == "tutte" else [r for r in rows if r["state"] == stato]


@router.get("/promozioni/{promo_id}")
def get_promotion(promo_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    p = ctx.db.get(Promotion, promo_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promozione non trovata")
    return _promo_out(ctx.db, p)


@router.post("/promozioni", status_code=201)
def create_promotion(body: PromotionIn, ctx: TenantContext = Depends(writer)):
    _check_promo(body)
    p = Promotion(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(p)
    ctx.db.flush()
    audit(ctx.db, "promotion", "creazione", p.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after={"name": p.name})
    return _promo_out(ctx.db, p)


@router.put("/promozioni/{promo_id}")
def update_promotion(promo_id: uuid.UUID, body: PromotionIn, ctx: TenantContext = Depends(writer)):
    p = ctx.db.get(Promotion, promo_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promozione non trovata")
    _check_promo(body)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    ctx.db.flush()
    return _promo_out(ctx.db, p)


@router.delete("/promozioni/{promo_id}")
def delete_promotion(promo_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    p = ctx.db.get(Promotion, promo_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Promozione non trovata")
    ctx.db.delete(p)
    return {"ok": True}


# ====================================================================== immagini articolo


def _sync_main_image(db: Session, item: Item) -> None:
    imgs = db.scalars(select(ItemImage).where(ItemImage.item_id == item.id).order_by(ItemImage.sort_order, ItemImage.created_at)).all()
    for n, im in enumerate(imgs):
        im.sort_order = n
    item.image_url = media.urls(imgs[0].file_name)["url"] if imgs else None


@router.post("/articoli/{item_id}/immagini", status_code=201)
async def upload_images(item_id: uuid.UUID, files: list[UploadFile] = File(...), ctx: TenantContext = Depends(writer)):
    item = ctx.db.get(Item, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    count = ctx.db.scalar(select(func.count()).select_from(ItemImage).where(ItemImage.item_id == item_id))
    if count + len(files) > 12:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Massimo 12 immagini per articolo")
    for n, f in enumerate(files):
        name = media.save_image(await f.read())
        ctx.db.add(ItemImage(tenant_id=ctx.tenant_id, item_id=item_id, file_name=name, sort_order=count + n))
    ctx.db.flush()
    _sync_main_image(ctx.db, item)
    return get_item(item_id, ctx)["images"]


@router.post("/articoli/{item_id}/immagini/{image_id}/principale")
def set_main_image(item_id: uuid.UUID, image_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    item = ctx.db.get(Item, item_id)
    img = ctx.db.get(ItemImage, image_id)
    if item is None or img is None or img.item_id != item_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Immagine non trovata")
    img.sort_order = -1
    ctx.db.flush()
    _sync_main_image(ctx.db, item)
    return get_item(item_id, ctx)["images"]


@router.delete("/articoli/{item_id}/immagini/{image_id}")
def delete_item_image(item_id: uuid.UUID, image_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    item = ctx.db.get(Item, item_id)
    img = ctx.db.get(ItemImage, image_id)
    if item is None or img is None or img.item_id != item_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Immagine non trovata")
    name = img.file_name
    ctx.db.delete(img)
    ctx.db.flush()
    _sync_main_image(ctx.db, item)
    media.delete_image(name)
    return get_item(item_id, ctx)["images"]


# ====================================================================== cataloghi e listini stampabili


class CatalogIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    title: str | None = None
    layout: str = "griglia"
    price_list_id: uuid.UUID | None = None
    party_id: uuid.UUID | None = None
    show_prices: bool = True
    vat_included: bool = True
    show_codes: bool = True
    group_by_category: bool = True
    category_ids: list[uuid.UUID] = []
    include_item_ids: list[uuid.UUID] = []
    exclude_item_ids: list[uuid.UUID] = []
    valid_until: date | None = None
    notes: str | None = None


def _catalog_out(c: Catalog) -> dict:
    out = {f: s(getattr(c, f)) for f in CatalogIn.model_fields}
    for k in ("category_ids", "include_item_ids", "exclude_item_ids"):
        out[k] = [str(x) for x in getattr(c, k) or []]
    out["valid_until"] = c.valid_until.isoformat() if c.valid_until else None
    out["id"] = str(c.id)
    out["updated_at"] = c.updated_at.isoformat() if c.updated_at else None
    return out


def _get_catalog(db: Session, cat_id: uuid.UUID) -> Catalog:
    c = db.get(Catalog, cat_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Catalogo non trovato")
    return c


@router.get("/cataloghi")
def list_catalogs(ctx: TenantContext = Depends(reader)):
    return [_catalog_out(c) for c in ctx.db.scalars(select(Catalog).order_by(Catalog.name))]


@router.get("/cataloghi/{cat_id}")
def get_catalog(cat_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    return _catalog_out(_get_catalog(ctx.db, cat_id))


def _check_catalog(body: CatalogIn) -> None:
    if body.layout not in ("griglia", "elenco"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Impaginazione non valida")


@router.post("/cataloghi", status_code=201)
def create_catalog(body: CatalogIn, ctx: TenantContext = Depends(writer)):
    _check_catalog(body)
    c = Catalog(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(c)
    ctx.db.flush()
    return _catalog_out(c)


@router.put("/cataloghi/{cat_id}")
def update_catalog(cat_id: uuid.UUID, body: CatalogIn, ctx: TenantContext = Depends(writer)):
    _check_catalog(body)
    c = _get_catalog(ctx.db, cat_id)
    for k, v in body.model_dump().items():
        setattr(c, k, v)
    ctx.db.flush()
    return _catalog_out(c)


@router.delete("/cataloghi/{cat_id}")
def delete_catalog(cat_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    ctx.db.delete(_get_catalog(ctx.db, cat_id))
    return {"ok": True}


def build_catalog(db: Session, c: CatalogIn | Catalog, role: str) -> dict:
    """Contenuto aggiornato del catalogo: articoli selezionati, raggruppati per categoria, con prezzi e immagini."""
    cats = {x.id: x for x in db.scalars(select(Category))}

    def descendants(ids) -> set:
        out, todo = set(), list(ids)
        while todo:
            cid = todo.pop()
            if cid in out:
                continue
            out.add(cid)
            todo += [x.id for x in cats.values() if x.parent_id == cid]
        return out

    selected_cats = descendants(c.category_ids or [])
    conds = []
    if selected_cats:
        conds.append(Item.category_id.in_(selected_cats))
    if c.include_item_ids:
        conds.append(Item.id.in_(c.include_item_ids))
    if not conds:
        items = []
    else:
        stmt = select(Item).where(Item.active, or_(*conds))
        if c.exclude_item_ids:
            stmt = stmt.where(Item.id.not_in(c.exclude_item_ids))
        items = db.scalars(stmt.order_by(Item.description)).all()

    party = db.get(Party, c.party_id) if c.party_id else None
    pl = db.get(PriceList, c.price_list_id) if c.price_list_id else None
    images = {}
    if items:
        for im in db.scalars(select(ItemImage).where(ItemImage.item_id.in_([i.id for i in items])).order_by(ItemImage.sort_order.desc())):
            images[im.item_id] = media.urls(im.file_name)
    brands = {b.id: b.name for b in db.scalars(select(Brand))}

    rows = []
    for it in items:
        price = None
        label = None
        if c.show_prices:
            if party is not None:
                res = resolve_price(db, it, party)
            elif pl is not None:
                from app.anagrafiche.price_engine import PriceResult, _vat, list_price
                vr = _vat(db, it)
                lp = list_price(db, it, pl, Decimal(1), None, vr)
                res = PriceResult(unit_price=lp, source="listino", source_label=pl.code, vat_rate=vr)
            else:
                res = resolve_price(db, it, None)
            d = res.to_dict()
            price = d["unit_price_vat_included"] if c.vat_included else d["unit_price"]
            if price is not None and not c.vat_included:
                price = str(Decimal(price).quantize(Decimal("0.01"), ROUND_HALF_UP))
            label = d["source_label"] if d["source"] == "promozione" else None
        cat = cats.get(it.category_id)
        group = cat.name if cat else "Altri articoli"
        if cat and cat.parent_id and cat.parent_id in cats:
            group = f"{cats[cat.parent_id].name} › {cat.name}"
        rows.append({"id": str(it.id), "code": it.code, "description": it.description,
                     "long_description": it.long_description, "unit": it.unit, "brand": brands.get(it.brand_id),
                     "price": price, "promo": label, "group": group, **(images.get(it.id) or {"url": None, "thumb_url": None})})

    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["group"] if c.group_by_category else "", []).append(r)
    return {"items_count": len(rows), "groups": [{"name": k, "items": v} for k, v in sorted(groups.items())],
            "party_name": party.name if party else None, "price_list": pl.code if pl else None}


@router.post("/cataloghi/anteprima")
def preview_catalog(body: CatalogIn, ctx: TenantContext = Depends(reader)):
    """Anteprima senza salvare (usata mentre si costruisce il catalogo)."""
    return build_catalog(ctx.db, body, ctx.user.role)


@router.get("/cataloghi/{cat_id}/contenuto")
def catalog_content(cat_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    c = _get_catalog(ctx.db, cat_id)
    return {"catalog": _catalog_out(c), **build_catalog(ctx.db, c, ctx.user.role)}


@router.get("/cataloghi/{cat_id}/export.csv")
def catalog_csv(cat_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    c = _get_catalog(ctx.db, cat_id)
    data = build_catalog(ctx.db, c, ctx.user.role)
    rows = [[r["group"], r["code"], r["description"], r["unit"], _it(r["price"]), r["promo"] or ""]
            for g in data["groups"] for r in g["items"]]
    return _csv_response(rows, ["categoria", "codice", "descrizione", "um", "prezzo", "promozione"],
                         re.sub(r"[^A-Za-z0-9_-]", "_", c.name) + ".csv")


# ====================================================================== schede tecniche e allegati

ATTACH_KINDS = {"scheda_tecnica": "Scheda tecnica", "certificato": "Certificato", "manuale": "Manuale",
                "sicurezza": "Scheda di sicurezza", "altro": "Altro"}


def _att_out(a: ItemAttachment) -> dict:
    return {"id": str(a.id), "title": a.title, "kind": a.kind, "kind_label": ATTACH_KINDS.get(a.kind, a.kind),
            "original_name": a.original_name, "size": a.size, "attach_to_quotes": a.attach_to_quotes,
            "url": f"/api/media/file/{a.file_name}?n={a.original_name}", "created_at": a.created_at.isoformat() if a.created_at else None}


@router.get("/articoli/{item_id}/allegati")
def list_attachments(item_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    rows = ctx.db.scalars(select(ItemAttachment).where(ItemAttachment.item_id == item_id).order_by(ItemAttachment.created_at)).all()
    return [_att_out(a) for a in rows]


@router.post("/articoli/{item_id}/allegati", status_code=201)
async def upload_attachment(item_id: uuid.UUID, file: UploadFile = File(...), title: str | None = None,
                            kind: str = "scheda_tecnica", ctx: TenantContext = Depends(writer)):
    if ctx.db.get(Item, item_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    if kind not in ATTACH_KINDS:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipo di allegato non valido")
    data = await file.read()
    name = media.save_file(data, file.filename or "file")
    original = (file.filename or name)[:200]
    a = ItemAttachment(tenant_id=ctx.tenant_id, item_id=item_id, file_name=name, original_name=original,
                       title=(title or original.rsplit(".", 1)[0])[:200], kind=kind, size=len(data))
    ctx.db.add(a)
    ctx.db.flush()
    return _att_out(a)


class AttachmentUpdate(BaseModel):
    title: str | None = None
    kind: str | None = None
    attach_to_quotes: bool | None = None


@router.patch("/articoli/{item_id}/allegati/{att_id}")
def update_attachment(item_id: uuid.UUID, att_id: uuid.UUID, body: AttachmentUpdate, ctx: TenantContext = Depends(writer)):
    a = ctx.db.get(ItemAttachment, att_id)
    if a is None or a.item_id != item_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Allegato non trovato")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "kind" and v not in ATTACH_KINDS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Tipo di allegato non valido")
        setattr(a, k, v)
    return _att_out(a)


@router.delete("/articoli/{item_id}/allegati/{att_id}")
def delete_attachment(item_id: uuid.UUID, att_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    a = ctx.db.get(ItemAttachment, att_id)
    if a is None or a.item_id != item_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Allegato non trovato")
    name = a.file_name
    ctx.db.delete(a)
    ctx.db.flush()
    media.delete_file(name)
    return {"ok": True}
