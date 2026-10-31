"""Ciclo attivo: preventivo → ordine (impegna) → DDT / fattura immediata → fattura differita, note di credito.

Regole principali
- Fatture immediate, differite e note di credito condividono un'unica numerazione annuale ("FT"),
  e la data di una nuova fattura non può precedere quella dell'ultima emessa.
- L'ordine cliente confermato impegna la merce (giacenza "impegnata"); DDT e fatture che lo evadono la liberano.
- DDT e fattura immediata scaricano il magazzino (causale "vendita"); la fattura differita no (l'ha già fatto il DDT);
  la nota di credito carica solo se la merce rientra (causale "reso da cliente").
- Fido: prima di confermare ordini, DDT e fatture si controlla l'esposizione del cliente.
"""

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Item, Party, VatRate
from app.documenti import service as docs
from app.documenti.models import Contract, Document, DocumentLine, DocumentLink
from app.magazzino import service as stock
from app.magazzino.models import StockMovement

SALES_TYPES = {
    "PRV": "Preventivo",
    "ORC": "Ordine cliente",
    "DDT": "DDT",
    "FTI": "Fattura",
    "FTD": "Fattura differita",
    "NC": "Nota di credito",
    "SCO": "Scontrino",
    "RSO": "Reso al banco",
}
for _k, _v in SALES_TYPES.items():
    docs.DOC_TYPES[_k] = (_v, "vendita")

INVOICE_TYPES = ("FTI", "FTD", "NC")
CREDIT_CHECKED = ("ORC", "DDT", "FTI")


def numbering_key(doc_type: str) -> str:
    return "FT" if doc_type in INVOICE_TYPES else doc_type


def default_moves_stock(doc_type: str) -> bool:
    return doc_type in ("DDT", "FTI", "SCO", "RSO")


def _q(v) -> Decimal:
    return Decimal(v or 0)


# ====================================================================== fido


def credit_exposure(db: Session, party_id, exclude_id=None) -> dict:
    """Esposizione del cliente: rate non incassate dello scadenzario, DDT non ancora fatturati, ordini aperti (residuo)."""
    base = select(Document).where(Document.party_id == party_id, Document.direction == "vendita",
                                  Document.status.in_(("confermato", "evaso")))
    if exclude_id:
        base = base.where(Document.id != exclude_id)
    from app.scadenzario import service as due

    position = due.party_position(db, party_id)
    invoices = position["open"]  # rate ancora da incassare (note di credito comprese, con segno negativo)
    ddt = Decimal(0)
    orders = Decimal(0)
    for d in db.scalars(base.where(Document.doc_type.in_(("DDT", "ORC")))):
        if d.doc_type == "DDT" and d.status == "confermato":
            ddt += _residual_value(d)
        elif d.doc_type == "ORC" and d.status == "confermato":
            orders += _residual_value(d)
    total = invoices + ddt + orders
    return {"invoices": invoices, "ddt": ddt, "orders": orders, "total": total, "overdue": position["overdue"],
            "overdue_days": position["overdue_days"], "unpaid": position["unpaid"]}


def _residual_value(d: Document) -> Decimal:
    """Valore IVA inclusa della parte non ancora evasa (ordini e DDT)."""
    if not d.taxable_total:
        return Decimal(0)
    ratio = _q(d.total) / _q(d.taxable_total)
    out = Decimal(0)
    for ln in d.lines:
        if not ln.quantity:
            continue
        open_qty = max(Decimal(0), _q(ln.quantity) - _q(ln.qty_processed))
        out += _q(ln.line_total) * open_qty / _q(ln.quantity)
    return (out * ratio).quantize(docs.CENT)


def _new_value(db: Session, d: Document) -> Decimal:
    """Valore che il documento aggiunge all'esposizione (le righe che evadono ordini/DDT sono già contate)."""
    if not d.taxable_total:
        return Decimal(0)
    fresh = Decimal(0)
    for ln in d.lines:
        if ln.origin_line_id:
            origin_doc = db.scalar(select(Document.doc_type).join(DocumentLine, DocumentLine.document_id == Document.id)
                                   .where(DocumentLine.id == ln.origin_line_id))
            if origin_doc in ("ORC", "DDT"):
                continue
        fresh += _q(ln.line_total)
    return (fresh * _q(d.total) / _q(d.taxable_total)).quantize(docs.CENT)


def credit_status(db: Session, party: Party, extra: Decimal = Decimal(0), exclude_id=None) -> dict:
    from app.scadenzario import service as due

    exp = credit_exposure(db, party.id, exclude_id)
    limit = _q(party.credit_limit) if party.credit_limit is not None else None
    after = exp["total"] + extra
    over = limit is not None and after > limit
    # cliente insolvente: rate insolute o ritardo oltre la soglia scelta nelle impostazioni dei solleciti
    block_days = due.settings(db, party.tenant_id).get("block_overdue_days")
    insolvent = exp["unpaid"] > 0 or bool(block_days and exp["overdue"] > 0 and exp["overdue_days"] >= int(block_days))
    return {
        "limit": limit, "policy": party.credit_policy, "exposure": exp, "adding": extra, "after": after,
        "available": (limit - exp["total"]) if limit is not None else None, "over": over, "insolvent": insolvent,
        "blocked": (over or insolvent) and party.credit_policy == "blocca",
    }


def check_credit(db: Session, d: Document, force: bool) -> str | None:
    """Solleva 409 se il fido è superato con criterio "blocca" (salvo forzatura); restituisce un avviso altrimenti."""
    if d.doc_type not in CREDIT_CHECKED:
        return None
    party = db.get(Party, d.party_id)
    if party is None:
        return None
    st = credit_status(db, party, _new_value(db, d), exclude_id=d.id)
    if not st["over"] and not st["insolvent"]:
        return None
    if st["over"]:
        msg = (f"Fido superato per {party.name}: fido {st['limit']:.2f} €, esposizione {st['exposure']['total']:.2f} €, "
               f"con questo documento {st['after']:.2f} €")
    else:
        e = st["exposure"]
        msg = (f"{party.name} ha pagamenti in ritardo: {e['overdue']:.2f} € scaduti da {e['overdue_days']} giorni"
               + (f", {e['unpaid']} rate insolute" if e["unpaid"] else ""))
    if st["blocked"] and not force:
        raise HTTPException(status.HTTP_409_CONFLICT, {"code": "fido_superato", "message": msg, "credit": _plain(st)})
    return msg


def _plain(v):
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, Decimal):
        return str(v)
    return v


# ====================================================================== conferma


def _ctx(d: Document, user_id, prefix: str = "") -> stock.Ctx:
    c = stock.Ctx(tenant_id=d.tenant_id, user_id=user_id, party_id=d.party_id, document_type=d.doc_type,
                  document_id=d.id, reference=f"{prefix}{SALES_TYPES[d.doc_type]} {d.number or ''}".strip())
    if d.doc_date != date.today():
        c.moved_at = datetime.combine(d.doc_date, time(12)).astimezone()
    return c


def _reserve(db: Session, d: Document, ln: DocumentLine, delta: Decimal) -> None:
    item = db.get(Item, ln.item_id)
    if item is None or not item.stock_managed or item.is_kit or delta == 0:
        return
    bal = stock._balance(db, d.tenant_id, d.warehouse_id, ln.item_id, ln.variant_id, None)
    bal.reserved = max(Decimal(0), _q(bal.reserved) + delta)


def _close_origin(db: Session, ln: DocumentLine, qty: Decimal) -> None:
    """Evade la riga d'origine; se è un ordine cliente libera l'impegno corrispondente."""
    orig = db.get(DocumentLine, ln.origin_line_id) if ln.origin_line_id else None
    if orig is None:
        return
    odoc = db.get(Document, orig.document_id)
    open_before = max(Decimal(0), _q(orig.quantity) - _q(orig.qty_processed))
    orig.qty_processed = _q(orig.qty_processed) + qty
    if odoc.doc_type == "ORC" and orig.item_id:
        _reserve(db, odoc, orig, -min(qty, open_before))
    if odoc.doc_type == "PRV":
        odoc.status = "evaso"  # preventivo accettato
    elif all(_q(l.qty_processed) >= _q(l.quantity) for l in odoc.lines if l.item_id or l.quantity):
        odoc.status = "evaso"


def _check_invoice_date(db: Session, d: Document) -> None:
    last = db.execute(select(Document.doc_date, Document.number, Document.doc_type).where(
        Document.direction == "vendita", Document.company_id == d.company_id, Document.doc_type.in_(INVOICE_TYPES),
        Document.year == d.year, Document.series == d.series, Document.number.is_not(None), Document.id != d.id,
    ).order_by(Document.number.desc()).limit(1)).first()
    if last and last.doc_date > d.doc_date:
        raise docs.fail(f"La data non può precedere quella dell'ultima fattura (n. {last.number} del "
                        f"{last.doc_date.strftime('%d/%m/%Y')})")


def item_cost(item: Item) -> Decimal | None:
    c = item.avg_cost if item.avg_cost else item.last_cost
    return Decimal(c) if c is not None else None


def confirm_sale(db: Session, d: Document, user_id, force: bool = False, number: int | None = None) -> str | None:
    if d.status != "bozza":
        raise docs.fail("Il documento è già confermato")
    if not d.lines:
        raise docs.fail("Il documento non ha righe")
    if d.warehouse_id is None and d.doc_type in ("ORC", "DDT", "FTI", "NC"):
        raise docs.fail("Indica il magazzino")
    docs.recompute(db, d)
    warning = check_credit(db, d, force)
    if number:
        from app.documenti import numerazioni
        d.number = numerazioni.manual_number(db, d, number)
    else:
        if d.doc_type in INVOICE_TYPES:
            _check_invoice_date(db, d)
        d.number = docs.next_number(db, d.tenant_id, d.company_id, numbering_key(d.doc_type), d.year, d.series)
    c = _ctx(d, user_id)
    d.stock_operation_id = c.operation_id
    for ln in d.lines:
        if ln.item_id is None or not ln.quantity:
            continue
        item = db.get(Item, ln.item_id)
        if ln.unit_cost is None:
            ln.unit_cost = item_cost(item)
        qty = _q(ln.quantity)
        if d.doc_type == "PRV":
            continue
        if d.doc_type == "ORC":
            _reserve(db, d, ln, qty)
            _close_origin(db, ln, qty)
            continue
        if d.moves_stock:
            if d.doc_type in ("NC", "RSO"):
                stock.apply_line(db, c, warehouse_id=d.warehouse_id, item_id=ln.item_id, qty=qty, reason="reso_cliente",
                                 variant_id=ln.variant_id, lot_number=ln.lot_number, expiry_date=ln.expiry_date,
                                 serials=ln.serials or None, unit_cost=ln.unit_cost)
            else:
                stock.apply_line(db, c, warehouse_id=d.warehouse_id, item_id=ln.item_id, qty=-qty, reason="vendita",
                                 variant_id=ln.variant_id, lot_number=ln.lot_number, serials=ln.serials or None)
        _close_origin(db, ln, qty)
    # le righe descrittive che evadono un'origine (es. intestazione "DDT n. ...") non hanno quantità: niente da fare
    d.status = "confermato"
    if d.doc_type in INVOICE_TYPES:
        from app.scadenzario import service as due
        due.create_for_document(db, d, user_id)
    return warning


def cancel_sale(db: Session, d: Document, user_id) -> None:
    if d.status == "annullato":
        raise docs.fail("Documento già annullato")
    downstream = db.scalar(select(DocumentLink).join(Document, Document.id == DocumentLink.to_id)
                           .where(DocumentLink.from_id == d.id, Document.status != "annullato"))
    if downstream is not None:
        raise docs.fail("Il documento è collegato a documenti successivi: annulla prima quelli", status.HTTP_409_CONFLICT)
    if d.status != "bozza":
        if d.doc_type in INVOICE_TYPES:
            from app.scadenzario import service as due
            due.remove_for_document(db, d)
        if d.doc_type == "ORC":
            for ln in d.lines:
                if ln.item_id:
                    _reserve(db, d, ln, -max(Decimal(0), _q(ln.quantity) - _q(ln.qty_processed)))
        elif d.stock_operation_id:
            c = _ctx(d, user_id, prefix="Annullamento ")
            for mv in db.scalars(select(StockMovement).where(StockMovement.operation_id == d.stock_operation_id)).all():
                item = db.get(Item, mv.item_id)
                lot = db.get(stock.Lot, mv.lot_id) if mv.lot_id else None
                ser = db.get(stock.Serial, mv.serial_id) if mv.serial_id else None
                if ser is not None:
                    if mv.quantity < 0:  # vendita annullata: la matricola torna disponibile
                        ser.status, ser.warehouse_id, ser.customer_id, ser.sale_date, ser.warranty_until = \
                            "disponibile", mv.warehouse_id, None, None, None
                    else:  # reso annullato: torna venduta al cliente
                        ser.status, ser.warehouse_id = "venduto", None
                stock.move(db, c, warehouse_id=mv.warehouse_id, item=item, qty=-Decimal(mv.quantity), reason="rettifica",
                           variant_id=mv.variant_id, lot=lot, serial=ser, unit_cost=mv.unit_cost, check_negative=False)
        for ln in d.lines:
            if not ln.origin_line_id:
                continue
            orig = db.get(DocumentLine, ln.origin_line_id)
            if orig is None:
                continue
            odoc = db.get(Document, orig.document_id)
            reopened = min(_q(ln.quantity), _q(orig.qty_processed))
            orig.qty_processed = max(Decimal(0), _q(orig.qty_processed) - _q(ln.quantity))
            if odoc.status == "evaso":
                odoc.status = "confermato"
            if odoc.doc_type == "ORC" and orig.item_id:
                _reserve(db, odoc, orig, reopened)
    d.status = "annullato"


def close_order(db: Session, d: Document) -> None:
    """Chiude un ordine cliente con merce non più da consegnare: libera l'impegno residuo."""
    if d.doc_type != "ORC" or d.status != "confermato":
        raise docs.fail("Si possono chiudere solo ordini cliente confermati e aperti")
    for ln in d.lines:
        if ln.item_id:
            open_qty = max(Decimal(0), _q(ln.quantity) - _q(ln.qty_processed))
            _reserve(db, d, ln, -open_qty)
    d.status = "evaso"


# ====================================================================== contratti ricorrenti

FREQUENCIES = {1: "mensile", 2: "bimestrale", 3: "trimestrale", 4: "quadrimestrale", 6: "semestrale", 12: "annuale"}


def period_for(contract: Contract, due: date) -> tuple[date, date]:
    step = relativedelta(months=contract.frequency_months)
    if contract.billing == "posticipata":
        return due - step, due - timedelta(days=1)
    return due, due + step - timedelta(days=1)


def generate_contract_invoices(db: Session, tenant_id, company_id, on: date, user_id=None,
                               contract_ids: list | None = None) -> list[Document]:
    """Crea le fatture dei canoni scaduti fino al giorno `on` (una per periodo, anche arretrati)."""
    stmt = select(Contract).where(Contract.active, Contract.next_invoice_date <= on).order_by(Contract.code)
    if contract_ids:
        stmt = stmt.where(Contract.id.in_(contract_ids))
    created: list[Document] = []
    vat_cache = {v.id: v for v in db.scalars(select(VatRate))}
    default_vat = next((v for v in vat_cache.values() if v.code == "22"), None)
    from app.core.models import Warehouse
    warehouse_id = db.scalar(select(Warehouse.id).order_by(Warehouse.code))
    for ct in db.scalars(stmt).all():
        party = db.get(Party, ct.party_id)
        guard = 0
        while ct.active and ct.next_invoice_date <= on and guard < 36:
            guard += 1
            due = ct.next_invoice_date
            if ct.end_date and due > ct.end_date:
                ct.active = False
                break
            p_from, p_to = period_for(ct, due)
            from app.documenti import numerazioni
            d = Document(tenant_id=tenant_id, company_id=company_id, direction="vendita", doc_type="FTI",
                         series=numerazioni.check_series(db, tenant_id, "FTI", None),
                         doc_date=on, year=on.year, party_id=ct.party_id, warehouse_id=warehouse_id, moves_stock=False,
                         payment_term_id=ct.payment_term_id or party.payment_term_id, contract_id=ct.id,
                         reference=f"Contratto {ct.code}", created_by=user_id, transport={}, print_options={},
                         attachment_ids=[])
            db.add(d)
            period = f"periodo {p_from.strftime('%d/%m/%Y')} – {p_to.strftime('%d/%m/%Y')}"
            for n, cl in enumerate(ct.lines, start=1):
                item = db.get(Item, cl.item_id) if cl.item_id else None
                vat_id = party.vat_rate_id or cl.vat_rate_id or (item.vat_rate_id if item else None) or \
                    (default_vat.id if default_vat else None)
                d.lines.append(DocumentLine(tenant_id=tenant_id, line_no=n, item_id=cl.item_id,
                                            description=f"{cl.description} – {period}", unit=item.unit if item else None,
                                            quantity=cl.quantity, unit_price=cl.unit_price, discount1=cl.discount1,
                                            vat_rate_id=vat_id, serials=[], price_source="Contratto"))
            db.flush()
            docs.recompute(db, d)
            if ct.auto_confirm:
                confirm_sale(db, d, user_id, force=True)
            created.append(d)
            ct.next_invoice_date = due + relativedelta(months=ct.frequency_months)
            if ct.end_date and ct.next_invoice_date > ct.end_date:
                ct.active = False
    db.flush()
    return created


def contracts_due(db: Session, on: date) -> int:
    return db.scalar(select(func.count()).select_from(Contract).where(Contract.active, Contract.next_invoice_date <= on)) or 0
