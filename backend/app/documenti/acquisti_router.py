"""API acquisti: /api/acquisti/...  (modulo "acquisti").

Ordini a fornitore, DDT e fatture fornitore, fattura da DDT, proposta di riordino, import fatture elettroniche."""

import re
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.anagrafiche import pricing
from app.anagrafiche.models import (
    Item,
    ItemBarcode,
    ItemPrice,
    ItemSupplier,
    ItemVariant,
    Party,
    PaymentTerm,
    PriceList,
    Unit,
    VatRate,
)
from app.anagrafiche.router import next_code
from app.anagrafiche.validators import valid_ean
from app.core import media
from app.core.deps import TenantContext, require_module
from app.core.models import Company, Warehouse
from app.documenti import fatturapa_import as fpa
from app.documenti import service as docs
from app.documenti.models import Document, DocumentLine, DocumentLink, PurchaseLineMemory
from app.magazzino.models import StockBalance
from app.saas.service import audit

router = APIRouter(prefix="/api/acquisti", tags=["acquisti"])
reader = require_module("acquisti")
TYPES = ("ORF", "DDTF", "FTF", "NCF")


def writer(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role in ("cassa", "vendite"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può registrare acquisti")
    return ctx


def s(v):
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


LINE_FIELDS = ["id", "line_no", "item_id", "variant_id", "description", "unit", "quantity", "unit_price", "discount1",
               "discount2", "discount3", "vat_rate_id", "vat_rate", "vat_nature", "line_total", "lot_number", "expiry_date",
               "serials", "qty_processed", "origin_line_id", "supplier_code", "notes"]


def doc_out(db: Session, d: Document, full: bool = True) -> dict:
    party = db.get(Party, d.party_id)
    out = {
        "id": str(d.id), "doc_type": d.doc_type, "type_label": docs.DOC_TYPES[d.doc_type][0], "number": d.number,
        "year": d.year, "series": d.series, "doc_date": s(d.doc_date), "external_number": d.external_number,
        "external_date": s(d.external_date), "party_id": str(d.party_id), "party_name": party.name if party else None,
        "warehouse_id": s(d.warehouse_id), "status": d.status, "moves_stock": d.moves_stock,
        "payment_term_id": s(d.payment_term_id), "taxable_total": s(d.taxable_total), "vat_total": s(d.vat_total),
        "total": s(d.total), "stamp_duty": s(d.stamp_duty), "reference": d.reference, "notes": d.notes, "source": d.source,
        "xml_url": f"/api/media/file/{d.xml_file}?n=fattura.xml" if d.xml_file else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }
    if full:
        items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({l.item_id for l in d.lines if l.item_id})))} if d.lines else {}
        variants = {v.id: v for v in db.scalars(select(ItemVariant).where(ItemVariant.id.in_({l.variant_id for l in d.lines if l.variant_id})))} if d.lines else {}
        out["lines"] = []
        for l in d.lines:
            it = items.get(l.item_id)
            v = variants.get(l.variant_id)
            out["lines"].append({**{f: s(getattr(l, f)) for f in LINE_FIELDS}, "serials": l.serials or [],
                                 "item_code": it.code if it else None, "variant_code": v.code if v else None,
                                 "lot_managed": bool(it and it.lot_managed), "serial_managed": bool(it and it.serial_managed),
                                 "residual": s(Decimal(l.quantity) - Decimal(l.qty_processed or 0))})
        out["vat_summary"] = [{k: s(x) for k, x in r.items()} for r in docs.vat_summary(d)]
        out["payment_schedule"] = d.payment_schedule or []
        links = db.execute(select(DocumentLink.from_id, DocumentLink.to_id).where(or_(DocumentLink.from_id == d.id, DocumentLink.to_id == d.id))).all()
        rel = []
        for f, t in links:
            other = db.get(Document, t if f == d.id else f)
            if other:
                rel.append({"id": str(other.id), "doc_type": other.doc_type, "label": docs.DOC_TYPES.get(other.doc_type, (other.doc_type,))[0],
                            "number": other.number, "external_number": other.external_number, "date": s(other.doc_date),
                            "status": other.status, "direction": "origine" if t == d.id else "derivato"})
        out["related"] = rel
    return out


def _load(db: Session, doc_id: uuid.UUID) -> Document:
    d = db.scalar(select(Document).where(Document.id == doc_id, Document.direction == "acquisto").options(selectinload(Document.lines)))
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento non trovato")
    return d


# ====================================================================== elenco e dettaglio


@router.get("/documenti")
def list_docs(tipo: str | None = Query(None, pattern="^(ORF|DDTF|FTF|NCF)$"), stato: str | None = None,
              party_id: uuid.UUID | None = None, q: str | None = None, date_from: date | None = None, date_to: date | None = None,
              da_fatturare: bool = False, page: int = Query(1, ge=1), page_size: int = Query(50, le=200),
              ctx: TenantContext = Depends(reader)):
    stmt = select(Document).where(Document.direction == "acquisto")
    if tipo:
        stmt = stmt.where(Document.doc_type == tipo)
    if stato:
        stmt = stmt.where(Document.status == stato)
    if party_id:
        stmt = stmt.where(Document.party_id == party_id)
    if date_from:
        stmt = stmt.where(Document.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(Document.doc_date <= date_to)
    if da_fatturare:  # DDT fornitore confermati e non ancora fatturati
        stmt = stmt.where(Document.doc_type == "DDTF", Document.status == "confermato")
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.external_number.ilike(like), Document.reference.ilike(like),
                              Document.party_id.in_(select(Party.id).where(Party.name.ilike(like)))))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = ctx.db.scalars(stmt.order_by(Document.doc_date.desc(), Document.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "rows": [doc_out(ctx.db, d, full=False) for d in rows]}


@router.get("/documenti/{doc_id}")
def get_doc(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    return doc_out(ctx.db, _load(ctx.db, doc_id))


# ====================================================================== creazione e modifica


class LineIn(BaseModel):
    item_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    description: str | None = None
    unit: str | None = None
    quantity: Decimal = Decimal(0)
    unit_price: Decimal = Decimal(0)
    discount1: Decimal | None = None
    discount2: Decimal | None = None
    discount3: Decimal | None = None
    vat_rate_id: uuid.UUID | None = None
    lot_number: str | None = None
    expiry_date: date | None = None
    serials: list[str] = []
    origin_line_id: uuid.UUID | None = None
    supplier_code: str | None = None
    notes: str | None = None


class DocIn(BaseModel):
    doc_type: str = Field(pattern="^(ORF|DDTF|FTF|NCF)$")
    party_id: uuid.UUID
    doc_date: date | None = None
    external_number: str | None = None
    external_date: date | None = None
    warehouse_id: uuid.UUID | None = None
    payment_term_id: uuid.UUID | None = None
    moves_stock: bool | None = None
    reference: str | None = None
    notes: str | None = None
    lines: list[LineIn] = []


def _default_vat(db: Session):
    return db.scalar(select(VatRate).where(VatRate.code == "22"))


def _apply(ctx: TenantContext, d: Document, body: DocIn) -> None:
    db = ctx.db
    p = db.get(Party, body.party_id)
    if p is None or not p.is_supplier:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fornitore non valido")
    d.doc_type, d.party_id = body.doc_type, body.party_id
    d.doc_date = body.doc_date or date.today()
    d.year = d.doc_date.year
    d.external_number, d.external_date = body.external_number, body.external_date
    d.warehouse_id = body.warehouse_id or d.warehouse_id or db.scalar(select(Warehouse.id).order_by(Warehouse.code))
    d.payment_term_id = body.payment_term_id or p.payment_term_id
    d.moves_stock = body.moves_stock if body.moves_stock is not None else body.doc_type in ("DDTF", "FTF", "NCF")
    d.reference, d.notes = body.reference, body.notes
    if body.doc_type in ("FTF", "NCF") and not body.external_number:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Indica il numero della fattura del fornitore")
    vat22 = _default_vat(db)
    d.lines.clear()
    db.flush()
    for n, ln in enumerate(body.lines, start=1):
        it = db.get(Item, ln.item_id) if ln.item_id else None
        if ln.item_id and it is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Articolo inesistente")
        if it and it.has_variants and not ln.variant_id and d.moves_stock and body.doc_type != "ORF":
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{it.code}: indica la variante")
        d.lines.append(DocumentLine(
            tenant_id=ctx.tenant_id, line_no=n, item_id=ln.item_id, variant_id=ln.variant_id,
            description=ln.description or (it.description if it else ""), unit=ln.unit or (it.unit if it else None),
            quantity=ln.quantity, unit_price=ln.unit_price, discount1=ln.discount1, discount2=ln.discount2, discount3=ln.discount3,
            vat_rate_id=ln.vat_rate_id or (it.vat_rate_id if it else None) or (vat22.id if vat22 else None),
            lot_number=(ln.lot_number or "").strip().upper() or None, expiry_date=ln.expiry_date,
            serials=[x.strip().upper() for x in ln.serials if x.strip()], origin_line_id=ln.origin_line_id,
            supplier_code=ln.supplier_code, notes=ln.notes))
    db.flush()
    docs.recompute(db, d)


@router.post("/documenti", status_code=201)
def create_doc(body: DocIn, ctx: TenantContext = Depends(writer)):
    company = ctx.db.scalar(select(Company).order_by(Company.name))
    d = Document(tenant_id=ctx.tenant_id, company_id=company.id, direction="acquisto", doc_type=body.doc_type,
                 doc_date=date.today(), year=date.today().year, party_id=body.party_id, created_by=ctx.user.id, series="")
    ctx.db.add(d)
    _apply(ctx, d, body)
    _check_duplicate(ctx.db, d)
    ctx.db.flush()
    return doc_out(ctx.db, d)


def _check_duplicate(db: Session, d: Document) -> None:
    if d.doc_type in ("FTF", "NCF") and d.external_number:
        dup = db.scalar(select(Document.id).where(Document.party_id == d.party_id, Document.doc_type == d.doc_type,
                                                  Document.external_number == d.external_number, Document.year == d.year,
                                                  Document.status != "annullato", Document.id != d.id))
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, f"La fattura {d.external_number} di questo fornitore è già registrata")


@router.put("/documenti/{doc_id}")
def update_doc(doc_id: uuid.UUID, body: DocIn, ctx: TenantContext = Depends(writer)):
    d = _load(ctx.db, doc_id)
    if d.status != "bozza":
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo le bozze si possono modificare: annulla e ricrea il documento")
    _apply(ctx, d, body)
    _check_duplicate(ctx.db, d)
    return doc_out(ctx.db, d)


@router.delete("/documenti/{doc_id}")
def delete_draft(doc_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    d = _load(ctx.db, doc_id)
    if d.status != "bozza":
        raise HTTPException(status.HTTP_409_CONFLICT, "Si possono eliminare solo le bozze")
    if d.xml_file:
        media.delete_file(d.xml_file)
    ctx.db.delete(d)
    return {"ok": True}


@router.post("/documenti/{doc_id}/conferma")
def confirm_doc(doc_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    d = _load(ctx.db, doc_id)
    _check_duplicate(ctx.db, d)
    docs.confirm_purchase(ctx.db, d, ctx.user.id)
    audit(ctx.db, "document", "conferma", d.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          after={"tipo": d.doc_type, "numero": d.number, "totale": str(d.total)})
    return doc_out(ctx.db, d)


@router.post("/documenti/{doc_id}/annulla")
def cancel_doc(doc_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    d = _load(ctx.db, doc_id)
    docs.cancel_purchase(ctx.db, d, ctx.user.id)
    audit(ctx.db, "document", "annullamento", d.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id)
    return doc_out(ctx.db, d)


# ====================================================================== trasformazioni


class TransformIn(BaseModel):
    to: str = Field(pattern="^(DDTF|FTF)$")
    external_number: str | None = None
    external_date: date | None = None
    quantities: dict[str, Decimal] | None = None  # line_id -> quantità da evadere (default: residuo)


@router.post("/documenti/{doc_id}/trasforma", status_code=201)
def transform(doc_id: uuid.UUID, body: TransformIn, ctx: TenantContext = Depends(writer)):
    """Ordine fornitore → DDT o fattura (evasione anche parziale). Crea una bozza da completare e confermare."""
    src = _load(ctx.db, doc_id)
    if src.doc_type != "ORF" or src.status not in ("confermato",):
        raise HTTPException(status.HTTP_409_CONFLICT, "Si può evadere solo un ordine fornitore confermato e non evaso")
    lines = []
    for l in src.lines:
        residual = Decimal(l.quantity) - Decimal(l.qty_processed or 0)
        q = body.quantities.get(str(l.id), residual) if body.quantities is not None else residual
        if q <= 0:
            continue
        lines.append(LineIn(item_id=l.item_id, variant_id=l.variant_id, description=l.description, unit=l.unit,
                            quantity=min(q, residual) if l.item_id else q, unit_price=l.unit_price, discount1=l.discount1,
                            discount2=l.discount2, discount3=l.discount3, vat_rate_id=l.vat_rate_id, origin_line_id=l.id))
    if not lines:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Niente da evadere")
    new = create_doc(DocIn(doc_type=body.to, party_id=src.party_id, warehouse_id=src.warehouse_id,
                           payment_term_id=src.payment_term_id, external_number=body.external_number,
                           external_date=body.external_date, lines=lines), ctx)
    ctx.db.add(DocumentLink(tenant_id=ctx.tenant_id, from_id=src.id, to_id=uuid.UUID(new["id"])))
    ctx.db.flush()
    return get_doc(uuid.UUID(new["id"]), ctx)


class InvoiceFromDdtIn(BaseModel):
    ddt_ids: list[uuid.UUID] = Field(min_length=1)
    external_number: str
    external_date: date | None = None


@router.post("/fattura-da-ddt", status_code=201)
def invoice_from_ddt(body: InvoiceFromDdtIn, ctx: TenantContext = Depends(writer)):
    """Fattura differita del fornitore: raccoglie i DDT già caricati (il magazzino non viene movimentato di nuovo)."""
    ddts = [_load(ctx.db, i) for i in body.ddt_ids]
    if len({d.party_id for d in ddts}) != 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "I DDT devono essere dello stesso fornitore")
    if any(d.doc_type != "DDTF" or d.status != "confermato" for d in ddts):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Scegli DDT fornitore confermati e non ancora fatturati")
    lines = []
    for d in sorted(ddts, key=lambda x: x.doc_date):
        lines.append(LineIn(description=f"DDT n. {d.external_number or d.number} del {d.doc_date.strftime('%d/%m/%Y')}", quantity=Decimal(0)))
        for l in d.lines:
            lines.append(LineIn(item_id=l.item_id, variant_id=l.variant_id, description=l.description, unit=l.unit,
                                quantity=l.quantity, unit_price=l.unit_price, discount1=l.discount1, discount2=l.discount2,
                                discount3=l.discount3, vat_rate_id=l.vat_rate_id, origin_line_id=l.id,
                                supplier_code=l.supplier_code))
    new = create_doc(DocIn(doc_type="FTF", party_id=ddts[0].party_id, warehouse_id=ddts[0].warehouse_id, moves_stock=False,
                           payment_term_id=ddts[0].payment_term_id, external_number=body.external_number,
                           external_date=body.external_date, lines=lines), ctx)
    for d in ddts:
        ctx.db.add(DocumentLink(tenant_id=ctx.tenant_id, from_id=d.id, to_id=uuid.UUID(new["id"])))
    ctx.db.flush()
    return get_doc(uuid.UUID(new["id"]), ctx)


# ====================================================================== proposta di riordino


@router.get("/proposta-riordino")
def reorder_proposal(warehouse_id: uuid.UUID | None = None, ctx: TenantContext = Depends(reader)):
    """Articoli sotto il punto di riordino (o la scorta minima), considerando anche l'ordinato, raggruppati per fornitore."""
    db = ctx.db
    items = db.scalars(select(Item).where(Item.active, Item.stock_managed, Item.is_kit.is_(False),
                                          or_(Item.reorder_point.is_not(None), Item.min_stock.is_not(None)))).all()
    q = select(StockBalance.item_id, func.sum(StockBalance.on_hand), func.sum(StockBalance.reserved), func.sum(StockBalance.ordered)) \
        .group_by(StockBalance.item_id)
    if warehouse_id:
        q = q.where(StockBalance.warehouse_id == warehouse_id)
    bal = {r[0]: (Decimal(r[1]), Decimal(r[2]), Decimal(r[3])) for r in db.execute(q)}
    groups: dict = defaultdict(list)
    for it in items:
        oh, rs, od = bal.get(it.id, (Decimal(0),) * 3)
        threshold = Decimal(it.reorder_point if it.reorder_point is not None else it.min_stock)
        projected = oh - rs + od
        if projected >= threshold:
            continue
        target = Decimal(it.max_stock) if it.max_stock else threshold
        qty = Decimal(it.reorder_qty) if it.reorder_qty else max(target - projected, Decimal(1))
        sup = db.scalar(select(ItemSupplier).where(ItemSupplier.item_id == it.id, ItemSupplier.supplier_id == it.preferred_supplier_id)) if it.preferred_supplier_id else None
        if sup and sup.min_order_qty and qty < sup.min_order_qty:
            qty = Decimal(sup.min_order_qty)
        groups[str(it.preferred_supplier_id) if it.preferred_supplier_id else ""].append({
            "item_id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit, "on_hand": s(oh),
            "reserved": s(rs), "ordered": s(od), "threshold": s(threshold), "proposed_qty": s(qty),
            "unit_price": s(sup.last_cost if sup and sup.last_cost else it.last_cost), "supplier_code": sup.supplier_code if sup else None})
    out = []
    for sid, rows in groups.items():
        p = db.get(Party, uuid.UUID(sid)) if sid else None
        out.append({"supplier_id": sid or None, "supplier_name": p.name if p else "Senza fornitore preferito", "items": rows})
    return sorted(out, key=lambda g: (g["supplier_id"] is None, g["supplier_name"]))


# ====================================================================== import fatture elettroniche


def _norm_desc(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (t or "").lower())).strip()[:200]


def _match_line(db: Session, supplier_id, ln: fpa.XmlLine) -> tuple[Item | None, uuid.UUID | None, str]:
    values = [v for _, v in ln.codes if v]
    if supplier_id and values:
        link = db.scalar(select(ItemSupplier).where(ItemSupplier.supplier_id == supplier_id, ItemSupplier.supplier_code.in_(values)))
        if link:
            return db.get(Item, link.item_id), None, "codice fornitore"
    if values:
        bc = db.scalar(select(ItemBarcode).where(ItemBarcode.barcode.in_(values)))
        if bc:
            return db.get(Item, bc.item_id), bc.variant_id, "codice a barre"
    if supplier_id:
        mem = db.scalar(select(PurchaseLineMemory).where(PurchaseLineMemory.supplier_id == supplier_id,
                                                         PurchaseLineMemory.description_key == _norm_desc(ln.description)))
        if mem:
            return db.get(Item, mem.item_id), mem.variant_id, "abbinamento precedente"
    if values:
        it = db.scalar(select(Item).where(func.upper(Item.code).in_([v.upper() for v in values])))
        if it:
            return it, None, "codice articolo"
    return None, None, ""


def _supplier_for(db: Session, sup: dict) -> Party | None:
    if sup.get("vat_number"):
        p = db.scalar(select(Party).where(Party.vat_number == sup["vat_number"]).order_by(Party.is_supplier.desc()))
        if p:
            return p
    if sup.get("tax_code"):
        return db.scalar(select(Party).where(Party.tax_code == sup["tax_code"].upper()))
    return None


def _preview(db: Session, inv: fpa.XmlInvoice, file_ref: str, index: int, company: Company) -> dict:
    p = _supplier_for(db, inv.supplier)
    doc_type = "NCF" if inv.doc_type in ("TD04", "TD08") else "FTF"
    warnings = []
    duplicate = None
    if p:
        duplicate = db.scalar(select(Document.id).where(Document.party_id == p.id, Document.doc_type == doc_type,
                                                        Document.external_number == inv.number, Document.year == inv.date.year,
                                                        Document.status != "annullato"))
        if duplicate:
            warnings.append("Questa fattura risulta già registrata")
    if inv.customer_vat and company.vat_number and inv.customer_vat != company.vat_number:
        warnings.append(f"La fattura è intestata alla partita IVA {inv.customer_vat}, non alla tua azienda")
    if inv.doc_type not in ("TD01", "TD04", "TD24", "TD25", "TD02", "TD08", "TD06"):
        warnings.append(f"Tipo documento {inv.doc_type}: verifica prima di registrarla")
    # DDT del fornitore già caricati a magazzino e citati in fattura → fattura differita
    ddt_docs = []
    if p and inv.ddt:
        nums = [d["number"] for d in inv.ddt if d["number"]]
        ddt_docs = db.scalars(select(Document).where(Document.party_id == p.id, Document.doc_type == "DDTF",
                                                     Document.external_number.in_(nums), Document.status == "confermato")).all()
    lines = []
    for ln in inv.lines:
        it, variant_id, how = _match_line(db, p.id if p else None, ln)
        lines.append({
            "number": ln.number, "codes": [v for _, v in ln.codes], "description": ln.description, "quantity": s(ln.quantity),
            "unit": ln.unit, "unit_price": s(ln.unit_price), "discounts": [s(d) for d in ln.discounts], "total": s(ln.total),
            "vat_rate": s(ln.vat_rate), "nature": ln.nature, "ddt_numbers": ln.ddt_numbers,
            "item_id": str(it.id) if it else None, "item_code": it.code if it else None,
            "item_description": it.description if it else None, "variant_id": str(variant_id) if variant_id else None,
            "has_variants": bool(it and it.has_variants), "lot_managed": bool(it and it.lot_managed),
            "serial_managed": bool(it and it.serial_managed), "match": how,
            "action": "abbina" if it else ("ignora" if ln.total == 0 or not ln.quantity else "nuovo"),
        })
    return {
        "file_ref": file_ref, "index": index, "file_name": inv.file_name, "doc_type": doc_type, "xml_type": inv.doc_type,
        "number": inv.number, "date": s(inv.date), "total": s(inv.total), "currency": inv.currency,
        "supplier": inv.supplier, "supplier_id": str(p.id) if p else None, "supplier_name": p.name if p else inv.supplier["name"],
        "duplicate": bool(duplicate), "warnings": warnings, "payments": inv.payments, "summary": inv.summary,
        "ddt": inv.ddt, "ddt_loaded": [{"id": str(d.id), "number": d.external_number, "date": s(d.doc_date)} for d in ddt_docs],
        "suggest_moves_stock": not ddt_docs, "lines": lines,
    }


@router.post("/import-xml/anteprima")
async def import_preview(files: list[UploadFile] = File(...), ctx: TenantContext = Depends(writer)):
    raw = [(f.filename or "fattura.xml", await f.read()) for f in files]
    invoices, errors = fpa.read_files(raw)
    company = ctx.db.scalar(select(Company).order_by(Company.name))
    out = []
    by_raw: dict[bytes, str] = {}
    for inv in invoices:
        ref = by_raw.get(inv.raw)
        if ref is None:
            ref = media.save_file(inv.raw, "fattura.xml")
            by_raw[inv.raw] = ref
        idx = sum(1 for o in out if o["file_ref"] == ref)
        out.append(_preview(ctx.db, inv, ref, idx, company))
    return {"invoices": out, "errors": errors}


class FromSdiIn(BaseModel):
    inbox_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


@router.post("/import-xml/anteprima-sdi")
def import_preview_sdi(body: FromSdiIn, ctx: TenantContext = Depends(writer)):
    """Anteprima delle fatture arrivate da SDI (casella della fatturazione elettronica): stesso flusso dell'import manuale."""
    import os

    from app.fatturapa.models import EInvoiceInbox
    company = ctx.db.scalar(select(Company).order_by(Company.name))
    out, errors = [], []
    for rid in body.inbox_ids:
        r = ctx.db.get(EInvoiceInbox, rid)
        if r is None or not r.xml_file:
            errors.append("Fattura ricevuta non trovata")
            continue
        with open(os.path.join(media.media_dir(), r.xml_file), "rb") as fh:
            invs = fpa.parse_xml(r.filename, fh.read())
        for idx, inv in enumerate(invs):
            out.append({**_preview(ctx.db, inv, r.xml_file, idx, company), "inbox_id": str(r.id)})
    return {"invoices": out, "errors": errors}


class ImportLineIn(BaseModel):
    number: int
    action: str = Field(pattern="^(abbina|nuovo|ignora)$")
    item_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    lot_number: str | None = None
    expiry_date: date | None = None
    serials: list[str] = []


class ImportConfirmIn(BaseModel):
    file_ref: str
    index: int = 0
    supplier_id: uuid.UUID | None = None  # vuoto = crea il fornitore dai dati della fattura
    warehouse_id: uuid.UUID | None = None
    moves_stock: bool = True
    update_prices: bool = False  # ricalcola il prezzo del listino predefinito con il ricarico del listino
    link_ddt_ids: list[uuid.UUID] = []
    confirm: bool = True
    lines: list[ImportLineIn]


def _load_invoice(ref: str, index: int) -> fpa.XmlInvoice:
    import os
    if not re.fullmatch(r"[0-9a-f]{32}\.xml", ref):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Riferimento file non valido")
    path = os.path.join(media.media_dir(), ref)
    if not os.path.exists(path):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File della fattura non trovato: ricaricalo")
    with open(path, "rb") as fh:
        invs = fpa.parse_xml("fattura.xml", fh.read())
    if index >= len(invs):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fattura non trovata nel file")
    return invs[index]


@router.post("/import-xml/conferma", status_code=201)
def import_confirm(body: ImportConfirmIn, ctx: TenantContext = Depends(writer)):
    db = ctx.db
    inv = _load_invoice(body.file_ref, body.index)
    # fornitore
    if body.supplier_id:
        sup = db.get(Party, body.supplier_id)
        if sup is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Fornitore inesistente")
        sup.is_supplier = True
    else:
        sup = _supplier_for(db, inv.supplier)
        if sup is None:
            x = inv.supplier
            sup = Party(tenant_id=ctx.tenant_id, code=next_code(db, Party, "F"), name=(x["name"] or "Fornitore")[:200],
                        is_customer=False, is_supplier=True, person_type="azienda",
                        vat_number=x["vat_number"] if x["vat_country"] == "IT" else f"{x['vat_country']}{x['vat_number'] or ''}" or None,
                        tax_code=(x["tax_code"] or "").upper() or None, address=x["address"], zip_code=x["zip_code"],
                        city=x["city"], province=(x["province"] or "")[:2] or None, country=(x["country"] or "IT")[:2],
                        email=(x["email"] or "").lower() or None, phone=x["phone"], custom={})
            db.add(sup)
            db.flush()
        sup.is_supplier = True
    vats = list(db.scalars(select(VatRate).where(VatRate.active)))
    units = {u.code for u in db.scalars(select(Unit))}
    default_list = db.scalar(select(PriceList).where(PriceList.is_default))

    def vat_for(rate: Decimal, nature: str | None):
        if nature:
            v = next((v for v in vats if v.nature == nature), None) or next((v for v in vats if v.nature and v.nature.startswith(nature[:2])), None)
            if v:
                return v
        return next((v for v in vats if not v.nature and Decimal(v.rate) == rate), None)

    decisions = {l.number: l for l in body.lines}
    doc_type = "NCF" if inv.doc_type in ("TD04", "TD08") else "FTF"
    lines_in: list[LineIn] = []
    ddt_lines = []
    if body.link_ddt_ids:
        for did in body.link_ddt_ids:
            ddt_lines += list(_load(db, did).lines)
    for ln in inv.lines:
        dec = decisions.get(ln.number) or ImportLineIn(number=ln.number, action="ignora")
        v = vat_for(ln.vat_rate, ln.nature)
        item_id, variant_id = None, None
        code = next((val for typ, val in ln.codes if val), None)
        if dec.action == "abbina":
            it = db.get(Item, dec.item_id) if dec.item_id else None
            if it is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Riga {ln.number}: scegli l'articolo da abbinare")
            item_id, variant_id = it.id, dec.variant_id
        elif dec.action == "nuovo":
            unit = (ln.unit or "PZ").upper()[:10]
            net_cost = (ln.total / ln.quantity).quantize(Decimal("0.0001")) if ln.quantity else ln.unit_price
            it = Item(tenant_id=ctx.tenant_id, code=next_code(db, Item, "ART"), description=ln.description[:200] or "Articolo",
                      unit=unit if unit in units else "PZ", vat_rate_id=v.id if v else None, last_cost=net_cost, avg_cost=None,
                      preferred_supplier_id=sup.id, tags=[], custom={})
            db.add(it)
            db.flush()
            for val in [val for _, val in ln.codes if val]:
                if valid_ean(val) and not db.scalar(select(ItemBarcode).where(ItemBarcode.barcode == val)):
                    db.add(ItemBarcode(tenant_id=ctx.tenant_id, item_id=it.id, barcode=val))
                    break
            item_id = it.id
        if item_id:
            # memoria: la prossima fattura di questo fornitore verrà abbinata da sola
            if code:
                link = db.scalar(select(ItemSupplier).where(ItemSupplier.item_id == item_id, ItemSupplier.supplier_id == sup.id))
                if link is None:
                    db.add(ItemSupplier(tenant_id=ctx.tenant_id, item_id=item_id, supplier_id=sup.id, supplier_code=code))
                else:
                    link.supplier_code = code
            else:
                key = _norm_desc(ln.description)
                mem = db.scalar(select(PurchaseLineMemory).where(PurchaseLineMemory.supplier_id == sup.id, PurchaseLineMemory.description_key == key))
                if mem is None:
                    db.add(PurchaseLineMemory(tenant_id=ctx.tenant_id, supplier_id=sup.id, description_key=key, item_id=item_id, variant_id=variant_id))
                else:
                    mem.item_id, mem.variant_id = item_id, variant_id
            db.flush()
        origin = None
        if item_id and ddt_lines:
            origin = next((d for d in ddt_lines if d.item_id == item_id and d.variant_id == variant_id
                           and Decimal(d.qty_processed or 0) < Decimal(d.quantity)), None)
        lines_in.append(LineIn(
            item_id=item_id, variant_id=variant_id, description=ln.description, unit=(ln.unit or None) and ln.unit[:10],
            quantity=ln.quantity if ln.quantity else Decimal(1 if ln.total else 0), unit_price=ln.unit_price if ln.quantity else ln.total,
            discount1=ln.discounts[0] if len(ln.discounts) > 0 else None, discount2=ln.discounts[1] if len(ln.discounts) > 1 else None,
            discount3=ln.discounts[2] if len(ln.discounts) > 2 else None, vat_rate_id=v.id if v else None,
            lot_number=dec.lot_number, expiry_date=dec.expiry_date, serials=dec.serials, supplier_code=code,
            origin_line_id=origin.id if origin else None))

    moves = body.moves_stock and not body.link_ddt_ids
    new = create_doc(DocIn(doc_type=doc_type, party_id=sup.id, doc_date=inv.date, external_number=inv.number,
                           external_date=inv.date, warehouse_id=body.warehouse_id, moves_stock=moves,
                           reference=f"Fattura elettronica {inv.file_name}", lines=lines_in), ctx)
    d = _load(db, uuid.UUID(new["id"]))
    d.source, d.xml_file, d.payment_schedule = "xml", body.file_ref, inv.payments
    d.stamp_duty = inv.stamp_duty or 0
    docs.recompute(db, d)
    for did in body.link_ddt_ids:
        db.add(DocumentLink(tenant_id=ctx.tenant_id, from_id=did, to_id=d.id))
    warnings = []
    if inv.total is not None and abs(Decimal(d.total) - inv.total) > Decimal("0.05"):
        warnings.append(f"Il totale calcolato ({d.total:.2f}) differisce da quello della fattura ({inv.total:.2f}): controlla le righe")
    if body.confirm:
        docs.confirm_purchase(db, d, ctx.user.id)
    if body.update_prices and default_list and default_list.markup_percent:
        for ln in d.lines:
            if not ln.item_id or not ln.quantity:
                continue
            it = db.get(Item, ln.item_id)
            vat = db.get(VatRate, it.vat_rate_id) if it.vat_rate_id else None
            new_price = pricing.price_from_markup(Decimal(ln.line_total) / Decimal(ln.quantity), Decimal(default_list.markup_percent),
                                                  Decimal(vat.rate) if vat else None, default_list.vat_included)
            pr = db.scalar(select(ItemPrice).where(ItemPrice.item_id == it.id, ItemPrice.price_list_id == default_list.id, ItemPrice.min_qty == 0))
            if pr is None:
                db.add(ItemPrice(tenant_id=ctx.tenant_id, item_id=it.id, price_list_id=default_list.id, min_qty=0, price=new_price))
            else:
                pr.price = new_price
    from app.fatturapa.models import EInvoiceInbox
    for r in db.scalars(select(EInvoiceInbox).where(EInvoiceInbox.xml_file == body.file_ref)):
        r.status, r.document_id = "registrata", d.id
    db.flush()
    audit(db, "document", "import_xml", d.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          after={"fornitore": sup.name, "numero": inv.number, "totale": str(d.total)})
    return {**doc_out(db, d), "warnings": warnings}
