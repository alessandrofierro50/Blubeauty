"""API vendite: /api/vendite/...  (modulo "vendite").

Preventivi, ordini cliente, DDT, fatture immediate e differite, note di credito, riquadro prezzi della riga,
fido, storico articolo, acquistato per cliente, contratti e canoni ricorrenti."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.anagrafiche import price_engine
from app.anagrafiche.models import (
    Item,
    ItemAttachment,
    ItemImage,
    ItemSupplier,
    ItemVariant,
    Party,
    PartyAddress,
    PaymentTerm,
    PriceList,
    VatRate,
)
from app.anagrafiche.router import next_code
from app.core import media
from app.core.deps import TenantContext, require_module
from app.core.models import Company, Warehouse
from app.documenti import service as docs
from app.documenti import numerazioni as num
from app.documenti import vendite_service as sales
from app.documenti.acquisti_router import doc_out as base_doc_out
from app.documenti.acquisti_router import s
from app.documenti.models import Contract, ContractLine, Document, DocumentLine, DocumentLink
from app.magazzino.models import StockBalance
from app.saas.service import audit

router = APIRouter(prefix="/api/vendite", tags=["vendite"])
reader = require_module("vendite")
TYPES = tuple(sales.SALES_TYPES)
TYPE_PATTERN = "^(" + "|".join(TYPES) + ")$"  # elenco e filtri: anche scontrini e resi al banco
EDIT_PATTERN = "^(" + "|".join(t for t in TYPES if t not in ("SCO", "RSO")) + ")$"  # scontrini solo dalla cassa


def writer(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role == "cassa":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può emettere documenti di vendita")
    return ctx


def can_see_costs(ctx: TenantContext) -> bool:
    return ctx.user.role in ("amministratore", "amministrazione", "contabilita")


def doc_out(db: Session, d: Document, full: bool = True, costs: bool = True) -> dict:
    out = base_doc_out(db, d, full)
    out.update({
        "direction": d.direction, "destination_id": s(d.destination_id), "transport": d.transport or {},
        "valid_until": s(d.valid_until), "settled": d.settled, "contract_id": s(d.contract_id),
        "attachment_ids": [str(a) for a in (d.attachment_ids or [])], "print_options": d.print_options or {},
        "van_trip_id": s(d.van_trip_id), "display_number": num.display_number(db, d), "number_label": num.number_label(db, d),
        "delivery": {**(d.delivery or {}), "signature_url": f"/api/media/file/{d.delivery['signature_file']}"}
        if (d.delivery or {}).get("signature_file") else (d.delivery or {}),
    })
    if d.doc_type in ("FTI", "FTD", "NC") and d.number:
        from app.fatturapa.models import STATUS_LABELS, EInvoice
        e = db.scalar(select(EInvoice).where(EInvoice.document_id == d.id).order_by(EInvoice.attempt.desc()).limit(1))
        out["sdi_status"] = e.status if e else "da_inviare"
        out["sdi_label"] = STATUS_LABELS.get(e.status if e else "da_inviare")
    if full:
        by_id = {ln.id: ln for ln in d.lines}
        cost_total = Decimal(0)
        for row in out["lines"]:
            ln = by_id[uuid.UUID(row["id"])]
            row["price_source"] = ln.price_source
            row["unit_cost"] = s(ln.unit_cost) if costs else None
            if ln.unit_cost is not None and ln.quantity:
                cost_total += Decimal(ln.unit_cost) * Decimal(ln.quantity)
        if costs:
            margin = Decimal(d.taxable_total or 0) - cost_total
            out["margin"] = {"cost": s(cost_total.quantize(docs.CENT)), "margin": s(margin.quantize(docs.CENT)),
                             "percent": s((margin / Decimal(d.taxable_total) * 100).quantize(docs.CENT)) if d.taxable_total else None}
    return out


def _load(db: Session, doc_id: uuid.UUID) -> Document:
    d = db.scalar(select(Document).where(Document.id == doc_id, Document.direction == "vendita").options(selectinload(Document.lines)))
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Documento non trovato")
    return d


def _editable(d: Document) -> Document:
    if d.doc_type in ("SCO", "RSO"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Scontrini e resi al banco si gestiscono dalla cassa")
    return d


# ====================================================================== elenco e dettaglio


@router.get("/documenti")
def list_docs(tipo: str | None = Query(None, pattern=TYPE_PATTERN), stato: str | None = None,
              party_id: uuid.UUID | None = None, q: str | None = None, date_from: date | None = None,
              date_to: date | None = None, da_fatturare: bool = False, da_incassare: bool = False,
              page: int = Query(1, ge=1), page_size: int = Query(50, le=200), ctx: TenantContext = Depends(reader)):
    stmt = select(Document).where(Document.direction == "vendita")
    if tipo == "FTI":  # "Fatture" comprende immediate e differite
        stmt = stmt.where(Document.doc_type.in_(("FTI", "FTD")))
    elif tipo:
        stmt = stmt.where(Document.doc_type == tipo)
    else:  # scontrini e resi al banco solo se richiesti espressamente
        stmt = stmt.where(Document.doc_type.not_in(("SCO", "RSO")))
    if stato:
        stmt = stmt.where(Document.status == stato)
    if party_id:
        stmt = stmt.where(Document.party_id == party_id)
    if date_from:
        stmt = stmt.where(Document.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(Document.doc_date <= date_to)
    if da_fatturare:
        stmt = stmt.where(Document.doc_type == "DDT", Document.status == "confermato")
    if da_incassare:
        stmt = stmt.where(Document.doc_type.in_(sales.INVOICE_TYPES), Document.status.in_(("confermato", "evaso")),
                          Document.settled.is_(False))
    if q:
        like = f"%{q.strip()}%"
        cond = [Document.reference.ilike(like), Document.party_id.in_(select(Party.id).where(Party.name.ilike(like)))]
        if q.strip().isdigit():
            cond.append(Document.number == int(q.strip()))
        stmt = stmt.where(or_(*cond))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    sub = stmt.where(Document.status != "annullato").subquery()
    sums = ctx.db.execute(select(func.coalesce(func.sum(sub.c.taxable_total), 0), func.coalesce(func.sum(sub.c.total), 0))).first()
    rows = ctx.db.scalars(stmt.options(selectinload(Document.lines))
                          .order_by(Document.doc_date.desc(), Document.number.desc().nulls_first(), Document.created_at.desc())
                          .offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "page": page, "page_size": page_size, "sum_taxable": s(sums[0]), "sum_total": s(sums[1]),
            "rows": [doc_out(ctx.db, d, full=False) for d in rows]}


@router.get("/documenti/{doc_id}")
def get_doc(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    return doc_out(ctx.db, _load(ctx.db, doc_id), costs=can_see_costs(ctx))


# ====================================================================== creazione e modifica


class LineIn(BaseModel):
    item_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    description: str | None = None
    unit: str | None = None
    quantity: Decimal = Decimal(0)
    unit_price: Decimal | None = None  # vuoto: lo calcola il motore prezzi
    discount1: Decimal | None = None
    discount2: Decimal | None = None
    discount3: Decimal | None = None
    vat_rate_id: uuid.UUID | None = None
    lot_number: str | None = None
    expiry_date: date | None = None
    serials: list[str] = []
    origin_line_id: uuid.UUID | None = None
    price_source: str | None = None
    notes: str | None = None


class DocIn(BaseModel):
    doc_type: str = Field(pattern=EDIT_PATTERN)
    party_id: uuid.UUID
    doc_date: date | None = None
    warehouse_id: uuid.UUID | None = None
    destination_id: uuid.UUID | None = None
    payment_term_id: uuid.UUID | None = None
    moves_stock: bool | None = None
    valid_until: date | None = None
    reference: str | None = None
    notes: str | None = None
    transport: dict = {}
    attachment_ids: list[uuid.UUID] = []
    print_options: dict = {}
    series: str | None = None  # sezionale (vuoto = principale; assente = predefinito per il tipo)
    lines: list[LineIn] = []


def _apply(ctx: TenantContext, d: Document, body: DocIn) -> None:
    db = ctx.db
    p = db.get(Party, body.party_id)
    if p is None or not p.is_customer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cliente non valido")
    if body.destination_id:
        dest = db.get(PartyAddress, body.destination_id)
        if dest is None or dest.party_id != p.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Destinazione non valida per questo cliente")
    d.doc_type, d.party_id = body.doc_type, body.party_id
    if d.van_trip_id is None:  # i documenti dell'agente usano il sezionale del furgone
        d.series = (num.check_series(db, ctx.tenant_id, body.doc_type, body.series) if body.series is not None
                    else d.series or num.check_series(db, ctx.tenant_id, body.doc_type, None))
    d.doc_date = body.doc_date or date.today()
    d.year = d.doc_date.year
    d.warehouse_id = body.warehouse_id or d.warehouse_id or db.scalar(select(Warehouse.id).order_by(Warehouse.code))
    d.destination_id = body.destination_id
    d.payment_term_id = body.payment_term_id or p.payment_term_id
    d.moves_stock = body.moves_stock if body.moves_stock is not None else sales.default_moves_stock(body.doc_type)
    if body.doc_type in ("PRV", "ORC", "FTD"):
        d.moves_stock = False
    d.valid_until = body.valid_until if body.doc_type == "PRV" else None
    d.reference, d.notes = body.reference, body.notes
    d.transport = body.transport or {}
    d.attachment_ids = list(dict.fromkeys(body.attachment_ids))
    d.print_options = body.print_options or {}
    default_vat = db.scalar(select(VatRate).where(VatRate.code == "22"))
    d.lines.clear()
    db.flush()
    for n, ln in enumerate(body.lines, start=1):
        it = db.get(Item, ln.item_id) if ln.item_id else None
        if ln.item_id and it is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Articolo inesistente")
        if it and it.has_variants and not ln.variant_id and d.moves_stock:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{it.code}: indica la variante (taglia/colore)")
        price, source = ln.unit_price, ln.price_source
        if price is None and it is not None:
            r = price_engine.resolve_price(db, it, p, ln.quantity or Decimal(1), d.doc_date, ln.variant_id)
            price, source = r.unit_price or Decimal(0), r.source_label
        vat_id = p.vat_rate_id or ln.vat_rate_id or (it.vat_rate_id if it else None) or (default_vat.id if default_vat else None)
        d.lines.append(DocumentLine(
            tenant_id=ctx.tenant_id, line_no=n, item_id=ln.item_id, variant_id=ln.variant_id,
            description=ln.description or (it.description if it else ""), unit=ln.unit or (it.unit if it else None),
            quantity=ln.quantity, unit_price=price or Decimal(0), discount1=ln.discount1, discount2=ln.discount2,
            discount3=ln.discount3, vat_rate_id=vat_id, lot_number=(ln.lot_number or "").strip().upper() or None,
            expiry_date=ln.expiry_date, serials=[x.strip().upper() for x in ln.serials if x.strip()],
            origin_line_id=ln.origin_line_id, price_source=(source or None) and source[:60], notes=ln.notes,
            unit_cost=sales.item_cost(it) if it else None))
    db.flush()
    docs.recompute(db, d)


def _company(db: Session) -> Company:
    return db.scalar(select(Company).order_by(Company.name))


@router.post("/documenti", status_code=201)
def create_doc(body: DocIn, ctx: TenantContext = Depends(writer)):
    d = Document(tenant_id=ctx.tenant_id, company_id=_company(ctx.db).id, direction="vendita", doc_type=body.doc_type,
                 doc_date=date.today(), year=date.today().year, party_id=body.party_id, created_by=ctx.user.id, series="")
    ctx.db.add(d)
    _apply(ctx, d, body)
    ctx.db.flush()
    return doc_out(ctx.db, d, costs=can_see_costs(ctx))


@router.put("/documenti/{doc_id}")
def update_doc(doc_id: uuid.UUID, body: DocIn, ctx: TenantContext = Depends(writer)):
    d = _editable(_load(ctx.db, doc_id))
    if d.status != "bozza":
        raise HTTPException(status.HTTP_409_CONFLICT, "Solo le bozze si possono modificare: annulla e ricrea il documento")
    _apply(ctx, d, body)
    return doc_out(ctx.db, d, costs=can_see_costs(ctx))


@router.delete("/documenti/{doc_id}")
def delete_draft(doc_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    d = _editable(_load(ctx.db, doc_id))
    if d.status != "bozza":
        raise HTTPException(status.HTTP_409_CONFLICT, "Si possono eliminare solo le bozze")
    ctx.db.delete(d)
    return {"ok": True}


class ConfirmIn(BaseModel):
    force: bool = False  # supera il blocco del fido (solo amministratori)
    number: int | None = Field(None, ge=1, le=9999999)  # numero scelto a mano (vuoto = il prossimo)


@router.post("/documenti/{doc_id}/conferma")
def confirm_doc(doc_id: uuid.UUID, body: ConfirmIn | None = None, ctx: TenantContext = Depends(writer)):
    d = _editable(_load(ctx.db, doc_id))
    force = bool(body and body.force)
    if force and ctx.user.role not in ("amministratore", "amministrazione"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un amministratore può superare il blocco del fido")
    if body and body.number and ctx.user.role not in ("amministratore", "amministrazione"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo l'amministrazione può scegliere il numero a mano")
    warning = sales.confirm_sale(ctx.db, d, ctx.user.id, force=force, number=body.number if body else None)
    warnings = [warning] if warning else []
    if d.doc_type in sales.INVOICE_TYPES and "fatturapa" in ctx.state.modules:
        from app.fatturapa import service as sdi
        if sdi.settings(ctx.db, ctx.tenant_id).get("auto_send"):
            try:
                e = sdi.send(ctx.db, d, ctx.user.id)
                if e.status == "errore_elaborazione":
                    warnings.append("Invio a SDI non riuscito: " + "; ".join(x["description"] for x in e.errors))
            except HTTPException as exc:
                warnings.append(f"Fattura emessa ma non inviata a SDI: {exc.detail}")
    audit(ctx.db, "document", "conferma", d.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          after={"tipo": d.doc_type, "numero": d.number, "totale": str(d.total), **({"fido_forzato": True} if force and warning else {})})
    return {**doc_out(ctx.db, d, costs=can_see_costs(ctx)), "warnings": warnings}


@router.post("/documenti/{doc_id}/annulla")
def cancel_doc(doc_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    d = _editable(_load(ctx.db, doc_id))
    sales.cancel_sale(ctx.db, d, ctx.user.id)
    audit(ctx.db, "document", "annullamento", d.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id)
    return doc_out(ctx.db, d, costs=can_see_costs(ctx))


@router.post("/documenti/{doc_id}/chiudi")
def close_doc(doc_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    d = _editable(_load(ctx.db, doc_id))
    sales.close_order(ctx.db, d)
    audit(ctx.db, "document", "chiusura_ordine", d.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id)
    return doc_out(ctx.db, d, costs=can_see_costs(ctx))


class SettledIn(BaseModel):
    settled: bool


@router.post("/documenti/{doc_id}/incassata")
def set_settled(doc_id: uuid.UUID, body: SettledIn, ctx: TenantContext = Depends(writer)):
    d = _load(ctx.db, doc_id)
    if d.doc_type not in sales.INVOICE_TYPES or d.status not in ("confermato", "evaso"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Solo le fatture confermate si segnano come incassate")
    from app.scadenzario import service as due
    due.settle_document(ctx.db, d, body.settled, date.today(), ctx.user.id)
    return doc_out(ctx.db, d, costs=can_see_costs(ctx))


# ====================================================================== trasformazioni

DEFAULT_TRANSPORT = {"causale": "Vendita", "porto": "Franco", "a_cura": "Mittente"}
ALLOWED = {"PRV": ("ORC", "DDT", "FTI"), "ORC": ("DDT", "FTI"), "DDT": ("FTD",), "FTI": ("NC",), "FTD": ("NC",)}


class TransformIn(BaseModel):
    to: str = Field(pattern=EDIT_PATTERN)
    quantities: dict[str, Decimal] | None = None  # line_id -> quantità (default: residuo)
    doc_date: date | None = None


def _copy_line(l: DocumentLine, qty: Decimal, origin: bool = True) -> LineIn:
    return LineIn(item_id=l.item_id, variant_id=l.variant_id, description=l.description, unit=l.unit, quantity=qty,
                  unit_price=l.unit_price, discount1=l.discount1, discount2=l.discount2, discount3=l.discount3,
                  vat_rate_id=l.vat_rate_id, origin_line_id=l.id if origin else None, price_source=l.price_source,
                  notes=l.notes, lot_number=l.lot_number, serials=l.serials or [])


@router.post("/documenti/{doc_id}/trasforma", status_code=201)
def transform(doc_id: uuid.UUID, body: TransformIn, ctx: TenantContext = Depends(writer)):
    """Preventivo → ordine/DDT/fattura · ordine → DDT/fattura (anche parziale) · DDT → fattura differita ·
    fattura → nota di credito. Crea una bozza da controllare e confermare."""
    src = _load(ctx.db, doc_id)
    if body.to not in ALLOWED.get(src.doc_type, ()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Da {sales.SALES_TYPES[src.doc_type]} non si può creare questo documento")
    if src.status != "confermato" and not (src.doc_type in ("FTI", "FTD") and src.status == "evaso"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Il documento d'origine deve essere confermato e ancora aperto")
    lines = []
    for l in src.lines:
        if body.to == "NC":
            lines.append(_copy_line(l, Decimal(l.quantity), origin=False))
            continue
        if src.doc_type == "PRV":
            residual = Decimal(l.quantity)
        else:
            residual = Decimal(l.quantity) - Decimal(l.qty_processed or 0)
        q = body.quantities.get(str(l.id), residual) if body.quantities is not None else residual
        if not l.item_id and not l.quantity:
            lines.append(_copy_line(l, Decimal(0), origin=False))  # riga descrittiva
            continue
        if q <= 0:
            continue
        lines.append(_copy_line(l, min(q, residual) if l.item_id and src.doc_type != "PRV" else q))
    if not any(l.quantity for l in lines):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Niente da evadere")
    new = create_doc(DocIn(doc_type=body.to, party_id=src.party_id, doc_date=body.doc_date, warehouse_id=src.warehouse_id,
                           destination_id=src.destination_id, payment_term_id=src.payment_term_id,
                           reference=src.reference if body.to != "NC" else f"Storno {sales.SALES_TYPES[src.doc_type].lower()} n. {src.number} del {src.doc_date.strftime('%d/%m/%Y')}",
                           moves_stock=False if body.to == "NC" else None,
                           attachment_ids=src.attachment_ids or [] if body.to in ("ORC",) else [],
                           transport=DEFAULT_TRANSPORT if body.to == "DDT" else {},
                           print_options={**(src.print_options or {}), "show_prices": body.to != "DDT"}, lines=lines), ctx)
    ctx.db.add(DocumentLink(tenant_id=ctx.tenant_id, from_id=src.id, to_id=uuid.UUID(new["id"])))
    ctx.db.flush()
    return get_doc(uuid.UUID(new["id"]), ctx)


@router.post("/documenti/{doc_id}/duplica", status_code=201)
def duplicate(doc_id: uuid.UUID, ctx: TenantContext = Depends(writer)):
    """Copia come nuova bozza (stesso cliente, prezzi ricalcolati solo se si cambiano le righe)."""
    src = _editable(_load(ctx.db, doc_id))
    doc_type = "FTI" if src.doc_type == "FTD" else src.doc_type
    return create_doc(DocIn(doc_type=doc_type, party_id=src.party_id, warehouse_id=src.warehouse_id,
                            destination_id=src.destination_id, payment_term_id=src.payment_term_id, reference=src.reference,
                            notes=src.notes, transport=src.transport or {}, attachment_ids=src.attachment_ids or [],
                            print_options=src.print_options or {},
                            lines=[_copy_line(l, Decimal(l.quantity), origin=False) for l in src.lines]), ctx)


@router.get("/fatturazione-ddt")
def ddt_to_invoice(fino_al: date | None = None, ctx: TenantContext = Depends(reader)):
    """Fatturazione DDT di fine mese (standard comune): clienti con DDT confermati e non ancora fatturati fino alla data,
    ognuno con i suoi DDT e le righe ancora da fatturare."""
    db = ctx.db
    stmt = select(Document).where(Document.direction == "vendita", Document.doc_type == "DDT", Document.status == "confermato")
    if fino_al:
        stmt = stmt.where(Document.doc_date <= fino_al)
    ddts = db.scalars(stmt.options(selectinload(Document.lines)).order_by(Document.doc_date, Document.number)).all()
    item_ids = {l.item_id for d in ddts for l in d.lines if l.item_id}
    codes = {i.id: i.code for i in db.scalars(select(Item).where(Item.id.in_(item_ids)))} if item_ids else {}
    terms = {t.id: t.description for t in db.scalars(select(PaymentTerm))}
    customers: dict = {}
    for d in ddts:
        lines, taxable = [], Decimal(0)
        for l in sorted(d.lines, key=lambda x: x.line_no):
            if l.item_id or l.quantity:
                residual = Decimal(l.quantity) - Decimal(l.qty_processed or 0)
                if residual <= 0:
                    continue
                amount = (docs.line_amount(l) * residual / Decimal(l.quantity)).quantize(docs.CENT) if l.quantity else Decimal(0)
                taxable += amount
                lines.append({"code": codes.get(l.item_id), "description": l.description, "quantity": s(residual), "unit": l.unit,
                              "unit_price": s(l.unit_price), "discount": " + ".join(f"{Decimal(x).normalize():f}%" for x in
                                                                                    (l.discount1, l.discount2, l.discount3) if x),
                              "amount": s(amount), "vat": l.vat_nature or (f"{Decimal(l.vat_rate or 0).normalize():f}%")})
            elif l.description:
                lines.append({"code": None, "description": l.description, "text": True})
        partial = any(Decimal(l.qty_processed or 0) > 0 for l in d.lines)
        c = customers.setdefault(d.party_id, {"party_id": str(d.party_id), "ddts": [], "taxable": Decimal(0), "total": Decimal(0)})
        c["ddts"].append({"id": str(d.id), "number": d.number, "number_label": num.number_label(db, d),
                          "date": s(d.doc_date), "reference": d.reference, "payment_term": terms.get(d.payment_term_id),
                          "taxable": s(taxable), "total": s(d.total if not partial else None), "partial": partial, "lines": lines})
        c["taxable"] += taxable
        c["total"] += Decimal(d.total) if not partial else taxable
    out = []
    for pid, c in customers.items():
        p = db.get(Party, pid)
        c.update({"name": p.name, "city": p.city, "count": len(c["ddts"]), "taxable": s(c["taxable"]), "total": s(c["total"]),
                  "payment_terms": len({x["payment_term"] for x in c["ddts"]})})
        out.append(c)
    out.sort(key=lambda c: c["name"].lower())
    return {"customers": out, "ddt_count": len(ddts), "taxable": s(sum((Decimal(c["taxable"]) for c in out), Decimal(0)))}


class DeferredIn(BaseModel):
    ddt_ids: list[uuid.UUID] = Field(min_length=1)
    doc_date: date | None = None
    confirm: bool = False


@router.post("/fatturazione-differita", status_code=201)
def deferred_invoicing(body: DeferredIn, ctx: TenantContext = Depends(writer)):
    """Fatturazione differita: una fattura per cliente (e condizione di pagamento) con tutti i suoi DDT."""
    ddts = [_load(ctx.db, i) for i in body.ddt_ids]
    if any(d.doc_type != "DDT" or d.status != "confermato" for d in ddts):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Scegli DDT confermati e non ancora fatturati")
    when = body.doc_date or date.today()
    if any(d.doc_date > when for d in ddts):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La fattura non può avere una data precedente ai DDT")
    groups: dict = defaultdict(list)
    for d in sorted(ddts, key=lambda x: (x.doc_date, x.number or 0)):
        groups[(d.party_id, d.payment_term_id)].append(d)
    created, warnings = [], []
    for (party_id, term_id), group in sorted(groups.items(), key=lambda g: ctx.db.get(Party, g[0][0]).name):
        lines = []
        for d in group:
            lines.append(LineIn(description=f"DDT n. {num.display_number(ctx.db, d)} del {d.doc_date.strftime('%d/%m/%Y')}", quantity=Decimal(0),
                                unit_price=Decimal(0)))
            for l in d.lines:
                residual = Decimal(l.quantity) - Decimal(l.qty_processed or 0)
                if l.item_id or l.quantity:
                    if residual <= 0:
                        continue
                    lines.append(_copy_line(l, residual))
                else:
                    lines.append(_copy_line(l, Decimal(0), origin=False))
        new = create_doc(DocIn(doc_type="FTD", party_id=party_id, doc_date=when, warehouse_id=group[0].warehouse_id,
                               payment_term_id=term_id, moves_stock=False, lines=lines), ctx)
        doc = _load(ctx.db, uuid.UUID(new["id"]))
        for d in group:
            ctx.db.add(DocumentLink(tenant_id=ctx.tenant_id, from_id=d.id, to_id=doc.id))
        ctx.db.flush()
        if body.confirm:
            w = sales.confirm_sale(ctx.db, doc, ctx.user.id)
            if w:
                warnings.append(w)
        created.append(doc_out(ctx.db, doc, full=False))
    return {"documents": created, "warnings": warnings}


# ====================================================================== fido, riquadro prezzi, storici


@router.get("/clienti/{party_id}/fido")
def customer_credit(party_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    p = ctx.db.get(Party, party_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente non trovato")
    return sales._plain(sales.credit_status(ctx.db, p))


def _net_unit(l: DocumentLine) -> Decimal | None:
    if not l.quantity:
        return None
    return (Decimal(l.line_total) / Decimal(l.quantity)).quantize(Decimal("0.0001"))


@router.get("/info-riga")
def line_info(item_id: uuid.UUID, party_id: uuid.UUID | None = None, qty: Decimal = Decimal(1),
              variant_id: uuid.UUID | None = None, on: date | None = None, ctx: TenantContext = Depends(reader)):
    """Tutto quello che serve per decidere il prezzo di una riga: prezzo proposto, costi, listini,
    ultimi prezzi praticati al cliente, ultimo acquisto, disponibilità."""
    db = ctx.db
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    party = db.get(Party, party_id) if party_id else None
    on = on or date.today()
    res = price_engine.resolve_price(db, it, party, qty if qty > 0 else Decimal(1), on, variant_id)
    vat_rate = res.vat_rate
    lists = []
    for pl in db.scalars(select(PriceList).order_by(PriceList.is_default.desc(), PriceList.code)):
        lp = price_engine.list_price(db, it, pl, qty if qty > 0 else Decimal(1), variant_id, vat_rate)
        if lp is not None:
            lists.append({"code": pl.code, "name": pl.name, "price": s(lp), "is_default": pl.is_default})
    last_sales = []
    if party:
        rows = db.execute(
            select(DocumentLine, Document).join(Document, Document.id == DocumentLine.document_id)
            .where(Document.direction == "vendita", Document.party_id == party.id, DocumentLine.item_id == it.id,
                   Document.status.in_(("confermato", "evaso")), Document.doc_type.in_(("PRV", "ORC", "DDT", "FTI", "FTD")),
                   DocumentLine.quantity > 0)
            .order_by(Document.doc_date.desc(), Document.created_at.desc()).limit(8)).all()
        seen_origins = set()
        for l, d in rows:
            if l.origin_line_id in seen_origins:
                continue
            seen_origins.add(l.id)
            last_sales.append({"date": s(d.doc_date), "doc_type": d.doc_type, "label": sales.SALES_TYPES[d.doc_type],
                               "number": d.number, "document_id": str(d.id), "quantity": s(l.quantity),
                               "unit_price": s(l.unit_price), "discounts": [s(x) for x in (l.discount1, l.discount2, l.discount3) if x],
                               "net_price": s(_net_unit(l))})
            if len(last_sales) >= 5:
                break
    last_purchase = None
    if can_see_costs(ctx):
        r = db.execute(select(DocumentLine, Document).join(Document, Document.id == DocumentLine.document_id)
                       .where(Document.direction == "acquisto", DocumentLine.item_id == it.id, DocumentLine.quantity > 0,
                              Document.doc_type.in_(("DDTF", "FTF")), Document.status.in_(("confermato", "evaso")))
                       .order_by(Document.doc_date.desc()).limit(1)).first()
        if r:
            l, d = r
            sup = db.get(Party, d.party_id)
            last_purchase = {"date": s(d.doc_date), "supplier": sup.name if sup else None, "quantity": s(l.quantity),
                             "net_price": s(_net_unit(l)), "document_id": str(d.id)}
    sq = select(func.coalesce(func.sum(StockBalance.on_hand), 0), func.coalesce(func.sum(StockBalance.reserved), 0),
                func.coalesce(func.sum(StockBalance.ordered), 0)).where(StockBalance.item_id == it.id)
    if variant_id:
        sq = sq.where(StockBalance.variant_id == variant_id)
    on_hand, reserved, ordered = db.execute(sq).first()
    cost = sales.item_cost(it)
    costs = can_see_costs(ctx)
    return {
        "item": {"id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit,
                 "stock_managed": it.stock_managed, "vat_rate_id": s(it.vat_rate_id), "lot_managed": it.lot_managed,
                 "serial_managed": it.serial_managed, "has_variants": it.has_variants, "is_kit": it.is_kit},
        "can_see_costs": costs,
        "price": res.to_dict(),
        "costs": {"last_cost": s(it.last_cost), "avg_cost": s(it.avg_cost), "cost": s(cost)} if costs else None,
        "suppliers": [{"supplier": db.get(Party, x.supplier_id).name, "last_cost": s(x.last_cost), "code": x.supplier_code}
                      for x in db.scalars(select(ItemSupplier).where(ItemSupplier.item_id == it.id))] if costs else [],
        "last_purchase": last_purchase,
        "lists": lists,
        "last_sales": last_sales,
        "stock": {"on_hand": s(on_hand), "reserved": s(reserved), "ordered": s(ordered),
                  "available": s(Decimal(on_hand) - Decimal(reserved))},
        "attachments": [{"id": str(a.id), "title": a.title, "kind": a.kind, "attach_to_quotes": a.attach_to_quotes,
                         "url": f"/api/media/file/{a.file_name}?n={a.original_name}"}
                        for a in db.scalars(select(ItemAttachment).where(ItemAttachment.item_id == it.id).order_by(ItemAttachment.title))],
    }


@router.get("/storico-articolo")
def item_history(item_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
                 direzione: str | None = Query(None, pattern="^(acquisto|vendita)$"), party_id: uuid.UUID | None = None,
                 ctx: TenantContext = Depends(reader)):
    """Da chi ho comprato e a chi ho venduto un articolo, a che prezzo (documenti che muovono merce o la fatturano)."""
    db = ctx.db
    it = db.get(Item, item_id)
    if it is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Articolo non trovato")
    costs = can_see_costs(ctx)
    stmt = (select(DocumentLine, Document).join(Document, Document.id == DocumentLine.document_id)
            .where(DocumentLine.item_id == item_id, Document.status.in_(("confermato", "evaso")),
                   Document.doc_type.in_(("DDTF", "FTF", "NCF", "DDT", "FTI", "FTD", "NC")), DocumentLine.quantity != 0))
    if direzione:
        stmt = stmt.where(Document.direction == direzione)
    if not costs:
        stmt = stmt.where(Document.direction == "vendita")
    if party_id:
        stmt = stmt.where(Document.party_id == party_id)
    if date_from:
        stmt = stmt.where(Document.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(Document.doc_date <= date_to)
    rows = db.execute(stmt.order_by(Document.doc_date.desc(), Document.created_at.desc()).limit(1000)).all()
    parties = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_({d.party_id for _, d in rows})))} if rows else {}
    variants = {v.id: v.code for v in db.scalars(select(ItemVariant).where(ItemVariant.item_id == item_id))}
    out = []
    tot = {"acquisto": [Decimal(0), Decimal(0)], "vendita": [Decimal(0), Decimal(0)]}
    for l, d in rows:
        # una riga di fattura che evade un DDT non va contata due volte
        counted = not (d.doc_type in ("FTD", "FTF") and l.origin_line_id and not d.moves_stock)
        sign = -1 if d.doc_type in ("NC", "NCF") else 1
        if counted:
            tot[d.direction][0] += Decimal(l.quantity) * sign
            tot[d.direction][1] += Decimal(l.line_total) * sign
        out.append({"date": s(d.doc_date), "direction": d.direction, "doc_type": d.doc_type,
                    "label": docs.DOC_TYPES[d.doc_type][0], "number": d.number, "external_number": d.external_number,
                    "document_id": str(d.id), "party_id": str(d.party_id), "party": parties.get(d.party_id),
                    "variant": variants.get(l.variant_id), "lot": l.lot_number, "quantity": s(Decimal(l.quantity) * sign),
                    "unit_price": s(l.unit_price), "net_price": s(_net_unit(l)), "total": s(Decimal(l.line_total) * sign),
                    "counted": counted})

    def avg(t):
        return s((t[1] / t[0]).quantize(Decimal("0.0001"))) if t[0] else None

    return {"item": {"id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit},
            "rows": out,
            "summary": {"bought_qty": s(tot["acquisto"][0]), "bought_amount": s(tot["acquisto"][1]), "avg_purchase": avg(tot["acquisto"]),
                        "sold_qty": s(tot["vendita"][0]), "sold_amount": s(tot["vendita"][1]), "avg_sale": avg(tot["vendita"])}}


@router.get("/acquistato-cliente")
def customer_purchases(party_id: uuid.UUID, date_from: date | None = None, date_to: date | None = None,
                       ctx: TenantContext = Depends(reader)):
    """Articoli comprati da un cliente in un periodo: quantità, importo, ultimo prezzo, ultima data."""
    db = ctx.db
    p = db.get(Party, party_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cliente non trovato")
    stmt = (select(DocumentLine, Document).join(Document, Document.id == DocumentLine.document_id)
            .where(Document.party_id == party_id, Document.direction == "vendita", DocumentLine.item_id.is_not(None),
                   Document.status.in_(("confermato", "evaso")), Document.doc_type.in_(("DDT", "FTI", "FTD", "NC"))))
    if date_from:
        stmt = stmt.where(Document.doc_date >= date_from)
    if date_to:
        stmt = stmt.where(Document.doc_date <= date_to)
    agg: dict = {}
    for l, d in db.execute(stmt.order_by(Document.doc_date)).all():
        if d.doc_type == "FTD" and l.origin_line_id:
            continue  # già contato nel DDT
        sign = -1 if d.doc_type == "NC" else 1
        key = (l.item_id, l.variant_id)
        a = agg.setdefault(key, {"qty": Decimal(0), "amount": Decimal(0), "docs": set(), "last_date": None, "last_price": None})
        a["qty"] += Decimal(l.quantity) * sign
        a["amount"] += Decimal(l.line_total) * sign
        a["docs"].add(d.id)
        if sign > 0 and l.quantity:
            a["last_date"], a["last_price"] = d.doc_date, _net_unit(l)
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({k[0] for k in agg})))} if agg else {}
    variants = {v.id: v.code for v in db.scalars(select(ItemVariant).where(ItemVariant.id.in_({k[1] for k in agg if k[1]})))} if agg else {}
    rows = []
    for (item_id, variant_id), a in agg.items():
        it = items.get(item_id)
        rows.append({"item_id": str(item_id), "code": it.code if it else "", "description": it.description if it else "",
                     "unit": it.unit if it else None, "variant": variants.get(variant_id), "quantity": s(a["qty"]),
                     "amount": s(a["amount"].quantize(docs.CENT)), "documents": len(a["docs"]),
                     "last_date": s(a["last_date"]), "last_price": s(a["last_price"])})
    rows.sort(key=lambda r: Decimal(r["amount"]), reverse=True)
    total = sum((Decimal(r["amount"]) for r in rows), Decimal(0))
    return {"party": {"id": str(p.id), "name": p.name}, "rows": rows, "total": s(total)}


# ====================================================================== stampa


@router.get("/documenti/{doc_id}/stampa")
def print_data(doc_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    """Dati per la stampa: documento, cliente, destinazione, pagamento, descrizioni estese, immagini, allegati."""
    db = ctx.db
    d = _load(db, doc_id)
    p = db.get(Party, d.party_id)
    dest = db.get(PartyAddress, d.destination_id) if d.destination_id else None
    term = db.get(PaymentTerm, d.payment_term_id) if d.payment_term_id else None
    item_ids = {l.item_id for l in d.lines if l.item_id}
    extras = {}
    if item_ids:
        imgs = {}
        for im in db.scalars(select(ItemImage).where(ItemImage.item_id.in_(item_ids)).order_by(ItemImage.sort_order)):
            imgs.setdefault(im.item_id, media.urls(im.file_name)["thumb_url"])
        for it in db.scalars(select(Item).where(Item.id.in_(item_ids))):
            extras[str(it.id)] = {"long_description": it.long_description, "image": imgs.get(it.id)}
    atts = []
    if d.attachment_ids:
        for a in db.scalars(select(ItemAttachment).where(ItemAttachment.id.in_(d.attachment_ids)).order_by(ItemAttachment.title)):
            atts.append({"id": str(a.id), "title": a.title, "kind": a.kind, "url": f"/api/media/file/{a.file_name}?n={a.original_name}"})
    party = {k: getattr(p, k) for k in ("name", "address", "street_number", "zip_code", "city", "province", "country",
                                         "vat_number", "tax_code", "sdi_code", "pec", "email", "phone") if hasattr(p, k)}
    return {"document": doc_out(db, d, costs=False), "party": party,
            "destination": {k: getattr(dest, k) for k in ("label", "address", "zip_code", "city", "province", "country")} if dest else None,
            "payment_term": term.description if term else None, "items": extras, "attachments": atts,
            "origins": _origins(db, d)}


ORIGIN_ORDER = {"PRV": 0, "ORC": 1, "DDT": 2, "FTI": 3, "FTD": 3}


def _origins(db: Session, d: Document) -> list[dict]:
    """Documenti da cui nasce `d`, risalendo la catena (preventivo → ordine → DDT → fattura): solo quelli emessi."""
    seen, todo, out = {d.id}, [d.id], []
    while todo and len(seen) < 60:
        ids = db.scalars(select(DocumentLink.from_id).where(DocumentLink.to_id.in_(todo))).all()
        todo = [i for i in ids if i not in seen]
        seen.update(todo)
        for o in db.scalars(select(Document).where(Document.id.in_(todo))) if todo else []:
            if o.number and o.status != "annullato" and o.direction == "vendita":
                out.append(o)
    out.sort(key=lambda o: (ORIGIN_ORDER.get(o.doc_type, 9), o.doc_date, o.number))
    return [{"doc_type": o.doc_type, "label": docs.DOC_TYPES.get(o.doc_type, (o.doc_type,))[0], "number": o.number,
             "number_label": num.number_label(db, o),
             "series": o.series, "year": o.year, "date": s(o.doc_date)} for o in out]


# ====================================================================== impostazioni: sezionali, numerazioni, bollo


def _admin(ctx: TenantContext) -> None:
    if ctx.user.role not in ("amministratore", "amministrazione"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo l'amministrazione può cambiare numerazioni e sezionali")


@router.get("/impostazioni")
def sales_settings(anno: int | None = None, ctx: TenantContext = Depends(reader)):
    year = anno or date.today().year
    return {**num.settings(ctx.db, ctx.tenant_id), "year": year,
            "counters": num.counters(ctx.db, ctx.tenant_id, _company(ctx.db).id, year)}


class SeriesIn(BaseModel):
    code: str
    description: str = ""


class SalesSettingsIn(BaseModel):
    bollo_mode: str = Field(pattern="^(cliente|azienda|no)$")
    series: dict[str, list[SeriesIn]] = {}
    formats: dict[str, dict[str, str]] = {}
    default_series: dict[str, str] = {}


@router.put("/impostazioni")
def save_sales_settings(body: SalesSettingsIn, ctx: TenantContext = Depends(writer)):
    _admin(ctx)
    out = num.save_settings(ctx.db, ctx.tenant_id, body.model_dump())
    audit(ctx.db, "vendite", "impostazioni", None, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after=body.model_dump())
    return out


class CounterIn(BaseModel):
    key: str = Field(pattern="^(FT|DDT|PRV|ORC)$")
    year: int = Field(ge=2000, le=2100)
    series: str = ""
    next_number: int = Field(ge=1, le=9999999)


@router.put("/numerazioni")
def set_counter(body: CounterIn, ctx: TenantContext = Depends(writer)):
    _admin(ctx)
    company = _company(ctx.db)
    notes = num.set_next(ctx.db, ctx.tenant_id, company.id, body.key, body.year, body.series.strip().upper(), body.next_number)
    audit(ctx.db, "vendite", "numerazione", None, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          after={**body.model_dump(), "note": notes})
    return {"notes": notes, "counters": num.counters(ctx.db, ctx.tenant_id, company.id, body.year)}


# ====================================================================== contratti ricorrenti


class ContractLineIn(BaseModel):
    item_id: uuid.UUID | None = None
    description: str = Field(min_length=1)
    quantity: Decimal = Decimal(1)
    unit_price: Decimal = Decimal(0)
    discount1: Decimal | None = None
    vat_rate_id: uuid.UUID | None = None


class ContractIn(BaseModel):
    party_id: uuid.UUID
    description: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date | None = None
    frequency_months: int = Field(1, ge=1, le=24)
    billing: str = Field("anticipata", pattern="^(anticipata|posticipata)$")
    next_invoice_date: date | None = None
    auto_confirm: bool = True
    payment_term_id: uuid.UUID | None = None
    active: bool = True
    notes: str | None = None
    lines: list[ContractLineIn] = Field(min_length=1)


def contract_out(db: Session, c: Contract) -> dict:
    p = db.get(Party, c.party_id)
    taxable = sum((pricing_net(l) for l in c.lines), Decimal(0))
    last = db.scalar(select(Document).where(Document.contract_id == c.id, Document.status != "annullato")
                     .order_by(Document.doc_date.desc(), Document.created_at.desc()).limit(1))
    return {
        "id": str(c.id), "code": c.code, "party_id": str(c.party_id), "party_name": p.name if p else None,
        "description": c.description, "start_date": s(c.start_date), "end_date": s(c.end_date),
        "frequency_months": c.frequency_months, "frequency_label": sales.FREQUENCIES.get(c.frequency_months, f"ogni {c.frequency_months} mesi"),
        "billing": c.billing, "next_invoice_date": s(c.next_invoice_date), "auto_confirm": c.auto_confirm,
        "payment_term_id": s(c.payment_term_id), "active": c.active, "notes": c.notes, "taxable": s(taxable.quantize(docs.CENT)),
        "yearly": s((taxable * 12 / c.frequency_months).quantize(docs.CENT)),
        "last_invoice": {"id": str(last.id), "number": last.number, "date": s(last.doc_date), "status": last.status} if last else None,
        "lines": [{"id": str(l.id), "item_id": s(l.item_id), "description": l.description, "quantity": s(l.quantity),
                   "unit_price": s(l.unit_price), "discount1": s(l.discount1), "vat_rate_id": s(l.vat_rate_id)} for l in c.lines],
    }


def pricing_net(l: ContractLine) -> Decimal:
    from app.anagrafiche import pricing
    return (pricing.cascade(Decimal(l.unit_price), l.discount1) * Decimal(l.quantity)).quantize(docs.CENT)


@router.get("/contratti")
def list_contracts(attivi: bool | None = None, party_id: uuid.UUID | None = None, ctx: TenantContext = Depends(reader)):
    stmt = select(Contract).options(selectinload(Contract.lines))
    if attivi is not None:
        stmt = stmt.where(Contract.active.is_(attivi))
    if party_id:
        stmt = stmt.where(Contract.party_id == party_id)
    rows = ctx.db.scalars(stmt.order_by(Contract.next_invoice_date, Contract.code)).all()
    return {"rows": [contract_out(ctx.db, c) for c in rows], "due": sales.contracts_due(ctx.db, date.today())}


@router.get("/contratti/{cid}")
def get_contract(cid: uuid.UUID, ctx: TenantContext = Depends(reader)):
    c = ctx.db.get(Contract, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contratto non trovato")
    out = contract_out(ctx.db, c)
    out["invoices"] = [doc_out(ctx.db, d, full=False) for d in ctx.db.scalars(
        select(Document).where(Document.contract_id == c.id).order_by(Document.doc_date.desc()).limit(50))]
    return out


def _apply_contract(ctx: TenantContext, c: Contract, body: ContractIn) -> None:
    p = ctx.db.get(Party, body.party_id)
    if p is None or not p.is_customer:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Cliente non valido")
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "La fine del contratto precede l'inizio")
    for f in ("party_id", "description", "start_date", "end_date", "frequency_months", "billing", "auto_confirm",
              "payment_term_id", "active", "notes"):
        setattr(c, f, getattr(body, f))
    if body.next_invoice_date:
        c.next_invoice_date = body.next_invoice_date
    elif c.next_invoice_date is None:
        # anticipata: si fattura all'inizio del periodo; posticipata: alla fine
        from dateutil.relativedelta import relativedelta
        c.next_invoice_date = body.start_date if body.billing == "anticipata" else body.start_date + relativedelta(months=body.frequency_months)
    c.lines.clear()
    ctx.db.flush()
    for n, l in enumerate(body.lines, start=1):
        c.lines.append(ContractLine(tenant_id=ctx.tenant_id, line_no=n, item_id=l.item_id, description=l.description,
                                    quantity=l.quantity, unit_price=l.unit_price, discount1=l.discount1, vat_rate_id=l.vat_rate_id))
    ctx.db.flush()


@router.post("/contratti", status_code=201)
def create_contract(body: ContractIn, ctx: TenantContext = Depends(writer)):
    c = Contract(tenant_id=ctx.tenant_id, code=next_code(ctx.db, Contract, "CT"))
    ctx.db.add(c)
    _apply_contract(ctx, c, body)
    audit(ctx.db, "contract", "creazione", c.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after={"codice": c.code})
    return contract_out(ctx.db, c)


@router.put("/contratti/{cid}")
def update_contract(cid: uuid.UUID, body: ContractIn, ctx: TenantContext = Depends(writer)):
    c = ctx.db.get(Contract, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contratto non trovato")
    _apply_contract(ctx, c, body)
    return contract_out(ctx.db, c)


@router.delete("/contratti/{cid}")
def delete_contract(cid: uuid.UUID, ctx: TenantContext = Depends(writer)):
    c = ctx.db.get(Contract, cid)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contratto non trovato")
    if ctx.db.scalar(select(Document.id).where(Document.contract_id == c.id).limit(1)):
        c.active = False  # ha già generato fatture: lo disattiva soltanto
        return {"ok": True, "deactivated": True}
    ctx.db.delete(c)
    return {"ok": True}


class GenerateIn(BaseModel):
    on: date | None = None
    contract_ids: list[uuid.UUID] | None = None


@router.post("/contratti/genera")
def generate(body: GenerateIn, ctx: TenantContext = Depends(writer)):
    """Genera adesso le fatture dei canoni scaduti (lo fa anche il sistema ogni mattina)."""
    on = body.on or date.today()
    if on > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Non si fatturano canoni futuri")
    created = sales.generate_contract_invoices(ctx.db, ctx.tenant_id, _company(ctx.db).id, on, ctx.user.id, body.contract_ids)
    return {"documents": [doc_out(ctx.db, d, full=False) for d in created]}
