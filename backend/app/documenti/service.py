"""Servizi comuni ai documenti: numerazione, calcolo totali e riepilogo IVA, conferma/annullamento acquisti."""

import uuid
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.anagrafiche import pricing
from app.anagrafiche.models import AppSetting, Item, ItemSupplier, VatRate
from app.documenti.models import Document, DocumentLine, DocumentLink, Numbering
from app.magazzino import service as stock
from app.magazzino.models import StockBalance, StockMovement

CENT = Decimal("0.01")

# Imposta di bollo (DPR 642/1972, tariffa art. 13): 2 € sulle fatture con importi senza IVA oltre 77,47 €.
# Non è dovuta per esportazioni e cessioni intracomunitarie (N3.1–N3.4, art. 15 tab. B), reverse charge (N6.x) e N7.
STAMP_AMOUNT = Decimal("2.00")
STAMP_THRESHOLD = Decimal("77.47")
STAMP_FREE_NATURES = ("N3.1", "N3.2", "N3.3", "N3.4", "N6", "N7")
STAMP_DOC_TYPES = ("FTI", "FTD", "NC")
STAMP_MODES = ("cliente", "azienda", "no")  # a carico del cliente (nel totale) | dell'azienda | non calcolare


def stamp_mode(db: Session, tenant_id) -> str:
    row = db.get(AppSetting, (tenant_id, "bollo"))
    mode = (row.value or {}).get("mode") if row else None
    return mode if mode in STAMP_MODES else "cliente"


def stamp_base(doc: Document) -> Decimal:
    """Importi della fattura senza IVA soggetti a bollo."""
    return sum((Decimal(ln.line_total or 0) for ln in doc.lines if not Decimal(ln.vat_rate or 0)
                and not (ln.vat_nature or "").startswith(STAMP_FREE_NATURES)), Decimal(0))

DOC_TYPES = {
    "ORF": ("Ordine a fornitore", "acquisto"),
    "DDTF": ("DDT fornitore", "acquisto"),
    "FTF": ("Fattura fornitore", "acquisto"),
    "NCF": ("Nota di credito fornitore", "acquisto"),
}


def fail(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def next_number(db: Session, tenant_id, company_id, doc_type: str, year: int, series: str = "") -> int:
    db.execute(insert(Numbering).values(id=uuid.uuid4(), tenant_id=tenant_id, company_id=company_id, doc_type=doc_type,
                                        year=year, series=series, last_number=0)
               .on_conflict_do_nothing(index_elements=["tenant_id", "company_id", "doc_type", "year", "series"]))
    row = db.scalar(select(Numbering).where(Numbering.company_id == company_id, Numbering.doc_type == doc_type,
                                            Numbering.year == year, Numbering.series == series).with_for_update())
    row.last_number += 1
    return row.last_number


def line_amount(ln: DocumentLine) -> Decimal:
    net = pricing.cascade(Decimal(ln.unit_price or 0), ln.discount1, ln.discount2, ln.discount3)
    return (net * Decimal(ln.quantity or 0)).quantize(CENT, ROUND_HALF_UP)


def gross_amount(ln: DocumentLine) -> Decimal:
    """Banco: importo della riga IVA inclusa (prezzo al pubblico × quantità, con sconti)."""
    gross = pricing.cascade(Decimal(ln.unit_price_gross or 0), ln.discount1, ln.discount2, ln.discount3)
    return (gross * Decimal(ln.quantity or 0)).quantize(CENT, ROUND_HALF_UP)


def recompute(db: Session, doc: Document) -> None:
    """Totali del documento: imponibile per riga, IVA arrotondata per aliquota (come nel riepilogo FatturaPA).

    Con prezzi IVA inclusa (banco) l'IVA si scorpora per aliquota: il totale resta la somma esatta delle righe."""
    rates = {v.id: v for v in db.scalars(select(VatRate))}
    for ln in doc.lines:
        v = rates.get(ln.vat_rate_id)
        if v is not None:
            ln.vat_rate, ln.vat_nature = Decimal(v.rate), v.nature
        if doc.prices_vat_included:
            r = Decimal(ln.vat_rate or 0)
            ln.unit_price = (Decimal(ln.unit_price_gross or 0) * 100 / (100 + r)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
            ln.line_total = (gross_amount(ln) * 100 / (100 + r)).quantize(CENT, ROUND_HALF_UP)
        else:
            ln.line_total = line_amount(ln)
    summary = vat_summary(doc)
    doc.taxable_total = sum((s["taxable"] for s in summary), Decimal(0))
    doc.vat_total = sum((s["vat"] for s in summary), Decimal(0))
    charged = True
    if doc.direction == "vendita":  # sugli acquisti il bollo è quello letto dalla fattura del fornitore
        mode = stamp_mode(db, doc.tenant_id) if doc.doc_type in STAMP_DOC_TYPES else "no"
        due = mode != "no" and stamp_base(doc) > STAMP_THRESHOLD
        doc.stamp_duty = STAMP_AMOUNT if due else Decimal(0)
        charged = mode == "cliente"
    doc.total = doc.taxable_total + doc.vat_total + (Decimal(doc.stamp_duty or 0) if charged else Decimal(0))


def vat_summary(doc: Document) -> list[dict]:
    groups: dict = defaultdict(lambda: Decimal(0))
    for ln in doc.lines:
        key = (Decimal(ln.vat_rate or 0), ln.vat_nature)
        groups[key] += gross_amount(ln) if doc.prices_vat_included else Decimal(ln.line_total or 0)
    out = []
    for (rate, nature), amount in sorted(groups.items(), key=lambda x: (-x[0][0], x[0][1] or "")):
        if doc.prices_vat_included:  # amount è IVA inclusa: scorporo
            taxable = (amount * 100 / (100 + rate)).quantize(CENT, ROUND_HALF_UP)
            out.append({"rate": rate, "nature": nature, "taxable": taxable, "vat": amount.quantize(CENT) - taxable})
        else:
            out.append({"rate": rate, "nature": nature, "taxable": amount.quantize(CENT),
                        "vat": (amount * rate / 100).quantize(CENT, ROUND_HALF_UP)})
    return out


def _unit_cost(ln: DocumentLine) -> Decimal | None:
    if not ln.quantity:
        return None
    return (Decimal(ln.line_total) / Decimal(ln.quantity)).quantize(Decimal("0.0001"), ROUND_HALF_UP)


def _ordered_balance(db: Session, doc: Document, ln: DocumentLine, delta: Decimal) -> None:
    bal = stock._balance(db, doc.tenant_id, doc.warehouse_id, ln.item_id, ln.variant_id, None)
    bal.ordered = max(Decimal(0), Decimal(bal.ordered) + delta)


def _close_origin(db: Session, doc: Document, ln: DocumentLine, qty: Decimal, ordered_too: bool) -> None:
    """Evade la riga d'origine (ordine o DDT) e, per gli ordini, riduce l'ordinato."""
    if not ln.origin_line_id:
        return
    orig = db.get(DocumentLine, ln.origin_line_id)
    if orig is None:
        return
    orig.qty_processed = Decimal(orig.qty_processed or 0) + qty
    odoc = db.get(Document, orig.document_id)
    if odoc.doc_type == "ORF" and ordered_too and orig.item_id:
        _ordered_balance(db, odoc, orig, -min(qty, Decimal(orig.quantity)))
    if all(Decimal(l.qty_processed or 0) >= Decimal(l.quantity) for l in odoc.lines if l.item_id or l.quantity):
        odoc.status = "evaso"


def confirm_purchase(db: Session, doc: Document, user_id) -> None:
    if doc.status != "bozza":
        raise fail("Il documento è già confermato")
    if not doc.lines:
        raise fail("Il documento non ha righe")
    if doc.warehouse_id is None:
        raise fail("Indica il magazzino")
    recompute(db, doc)
    doc.number = next_number(db, doc.tenant_id, doc.company_id, doc.doc_type, doc.year, doc.series)
    c = stock.Ctx(tenant_id=doc.tenant_id, user_id=user_id, party_id=doc.party_id, document_type=doc.doc_type,
                  document_id=doc.id, reference=f"{DOC_TYPES[doc.doc_type][0]} {doc.external_number or doc.number}")
    if doc.doc_date != date.today():
        from datetime import datetime, time
        c.moved_at = datetime.combine(doc.doc_date, time(12)).astimezone()
    doc.stock_operation_id = c.operation_id

    for ln in doc.lines:
        if ln.item_id is None or not ln.quantity:
            continue
        qty = Decimal(ln.quantity)
        if doc.doc_type == "ORF":
            item = db.get(Item, ln.item_id)
            if item.stock_managed and not item.is_kit:
                _ordered_balance(db, doc, ln, qty)
            continue
        if doc.moves_stock:
            reason = "reso_fornitore" if doc.doc_type == "NCF" else "acquisto"
            sign = -1 if doc.doc_type == "NCF" else 1
            stock.apply_line(db, c, warehouse_id=doc.warehouse_id, item_id=ln.item_id, qty=qty * sign, reason=reason,
                             variant_id=ln.variant_id, lot_number=ln.lot_number, expiry_date=ln.expiry_date,
                             serials=ln.serials or None, unit_cost=_unit_cost(ln) if sign > 0 else None)
        _close_origin(db, doc, ln, qty, ordered_too=doc.moves_stock or doc.doc_type == "DDTF")
        if doc.doc_type in ("DDTF", "FTF"):
            _remember_supplier_price(db, doc, ln)
    doc.status = "confermato"
    if doc.doc_type in ("FTF", "NCF"):
        from app.scadenzario import service as due
        due.create_for_document(db, doc, user_id)


def _remember_supplier_price(db: Session, doc: Document, ln: DocumentLine) -> None:
    link = db.scalar(select(ItemSupplier).where(ItemSupplier.item_id == ln.item_id, ItemSupplier.supplier_id == doc.party_id))
    if link is None:
        link = ItemSupplier(tenant_id=doc.tenant_id, item_id=ln.item_id, supplier_id=doc.party_id)
        db.add(link)
    link.last_cost = _unit_cost(ln)
    if ln.supplier_code:
        link.supplier_code = ln.supplier_code
    item = db.get(Item, ln.item_id)
    if not doc.moves_stock and link.last_cost is not None:  # fattura da DDT: il costo può differire dal DDT
        item.last_cost = link.last_cost
    if item.preferred_supplier_id is None:
        item.preferred_supplier_id = doc.party_id


def cancel_purchase(db: Session, doc: Document, user_id) -> None:
    if doc.status == "annullato":
        raise fail("Documento già annullato")
    downstream = db.scalar(select(DocumentLink).join(Document, Document.id == DocumentLink.to_id)
                           .where(DocumentLink.from_id == doc.id, Document.status != "annullato"))
    if downstream is not None:
        raise fail("Il documento è collegato a documenti successivi: annulla prima quelli", status.HTTP_409_CONFLICT)
    if doc.status != "bozza":
        if doc.doc_type in ("FTF", "NCF"):
            from app.scadenzario import service as due
            due.remove_for_document(db, doc)
        if doc.doc_type == "ORF":
            for ln in doc.lines:
                if ln.item_id:
                    _ordered_balance(db, doc, ln, -(Decimal(ln.quantity) - Decimal(ln.qty_processed or 0)))
        elif doc.stock_operation_id:
            c = stock.Ctx(tenant_id=doc.tenant_id, user_id=user_id, party_id=doc.party_id, document_type=doc.doc_type,
                          document_id=doc.id, reference=f"Annullamento {DOC_TYPES[doc.doc_type][0]} {doc.external_number or doc.number}")
            for mv in db.scalars(select(StockMovement).where(StockMovement.operation_id == doc.stock_operation_id)).all():
                item = db.get(Item, mv.item_id)
                lot = db.get(stock.Lot, mv.lot_id) if mv.lot_id else None
                ser = db.get(stock.Serial, mv.serial_id) if mv.serial_id else None
                if ser is not None:
                    ser.status, ser.warehouse_id = ("dismesso", None) if mv.quantity > 0 else ("disponibile", mv.warehouse_id)
                stock.move(db, c, warehouse_id=mv.warehouse_id, item=item, qty=-Decimal(mv.quantity), reason="rettifica",
                           variant_id=mv.variant_id, lot=lot, serial=ser, unit_cost=mv.unit_cost, check_negative=False)
        # riapre le righe d'origine
        for ln in doc.lines:
            if ln.origin_line_id:
                orig = db.get(DocumentLine, ln.origin_line_id)
                if orig:
                    orig.qty_processed = max(Decimal(0), Decimal(orig.qty_processed or 0) - Decimal(ln.quantity))
                    odoc = db.get(Document, orig.document_id)
                    if odoc.status == "evaso":
                        odoc.status = "confermato"
                    if odoc.doc_type == "ORF" and orig.item_id and (doc.moves_stock or doc.doc_type == "DDTF"):
                        _ordered_balance(db, odoc, orig, Decimal(ln.quantity))
    doc.status = "annullato"


def ordered_qty(db: Session, item_id) -> Decimal:
    from sqlalchemy import func
    return Decimal(db.scalar(select(func.coalesce(func.sum(StockBalance.ordered), 0)).where(StockBalance.item_id == item_id)) or 0)
