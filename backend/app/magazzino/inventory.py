"""Inventario: confronto tra conteggi (smartphone, manuali, importati) e giacenza teorica, e rettifiche alla chiusura.

Regola dei non contati: durante l'inventario nessuna riga viene azzerata in automatico (l'inventario può essere
interrotto e ripreso). Una riga è "contata" solo se ha almeno un conteggio accettato. Alla chiusura l'utente sceglie
se lasciare invariate le righe non contate (inventario parziale) o azzerarle (inventario concluso)."""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Category, Item, ItemVariant
from app.magazzino import service
from app.magazzino.models import InventoryCount, InventorySession, Lot, Serial, StockBalance


def scope_items(db: Session, s: InventorySession) -> list[Item]:
    stmt = select(Item).where(Item.active, Item.stock_managed, Item.is_kit.is_(False), Item.item_type == "articolo")
    if s.category_ids:
        cats = {c.id: c for c in db.scalars(select(Category))}
        todo, ids = list(s.category_ids), set()
        while todo:
            cid = todo.pop()
            if cid not in ids:
                ids.add(cid)
                todo += [c.id for c in cats.values() if c.parent_id == cid]
        stmt = stmt.where(Item.category_id.in_(ids))
    if s.location_prefix:
        stmt = stmt.where(Item.location.ilike(f"{s.location_prefix}%"))
    return db.scalars(stmt.order_by(Item.location.nulls_last(), Item.code)).all()


def summary(db: Session, s: InventorySession) -> dict:
    items = {i.id: i for i in scope_items(db, s)}
    counts = db.scalars(select(InventoryCount).where(InventoryCount.session_id == s.id).order_by(InventoryCount.counted_at)).all()
    for c in counts:  # articoli contati ma fuori ambito (es. trovati in negozio) entrano comunque
        if c.item_id not in items:
            it = db.get(Item, c.item_id)
            if it:
                items[it.id] = it
    ids = list(items)
    variants = {v.id: v for v in db.scalars(select(ItemVariant).where(ItemVariant.item_id.in_(ids)))} if ids else {}
    lots = {l.id: l for l in db.scalars(select(Lot).where(Lot.item_id.in_(ids)))} if ids else {}

    theo: dict[tuple, Decimal] = defaultdict(Decimal)
    for b in (db.scalars(select(StockBalance).where(StockBalance.warehouse_id == s.warehouse_id, StockBalance.item_id.in_(ids))) if ids else []):
        theo[(b.item_id, b.variant_id, lots[b.lot_id].lot_number if b.lot_id else None)] += Decimal(b.on_hand)

    counted: dict[tuple, Decimal] = defaultdict(Decimal)
    is_counted: set = set()
    details: dict[tuple, list] = defaultdict(list)
    expiry: dict[tuple, date] = {}
    serials_counted: dict[tuple, list] = defaultdict(list)
    for c in counts:
        key = (c.item_id, c.variant_id, c.lot_number.upper() if c.lot_number else None)
        details[key].append({"id": str(c.id), "quantity": str(c.quantity), "source": c.source, "accepted": c.accepted,
                             "serial_number": c.serial_number, "counted_at": c.counted_at.isoformat(),
                             "user_id": str(c.user_id) if c.user_id else None})
        if c.accepted:
            counted[key] += Decimal(c.quantity)
            is_counted.add(key)
            if c.expiry_date:
                expiry[key] = c.expiry_date
            if c.serial_number:
                serials_counted[key].append(c.serial_number.upper())

    serials_expected: dict[tuple, list] = defaultdict(list)
    for ser in (db.scalars(select(Serial).where(Serial.warehouse_id == s.warehouse_id, Serial.status == "disponibile",
                                                Serial.item_id.in_(ids))) if ids else []):
        serials_expected[(ser.item_id, ser.variant_id, None)].append(ser.serial_number)

    keys = set(theo) | set(details) | set(serials_expected)
    for it in items.values():  # articoli semplici senza giacenza: compaiono comunque tra i non contati
        if not it.has_variants and not it.lot_managed and not any(k[0] == it.id for k in keys):
            keys.add((it.id, None, None))

    rows = []
    for key in keys:
        item_id, variant_id, lot_no = key
        it = items.get(item_id)
        if it is None:
            continue
        th = theo.get(key, Decimal(0))
        cnt = counted[key] if key in is_counted else None
        v = variants.get(variant_id)
        lot = next((l for l in lots.values() if l.item_id == item_id and l.lot_number == lot_no), None) if lot_no else None
        exp = expiry.get(key) or (lot.expiry_date if lot else None)
        expected = sorted(serials_expected.get(key, [])) if it.serial_managed else None
        scanned = sorted(set(serials_counted.get(key, []))) if it.serial_managed else None
        rows.append({
            "item_id": str(item_id), "variant_id": str(variant_id) if variant_id else None, "lot_number": lot_no,
            "code": it.code, "description": it.description, "location": it.location, "unit": it.unit,
            "variant_code": v.code if v else None, "size": v.size if v else None, "color": v.color if v else None,
            "expiry_date": exp.isoformat() if exp else None, "lot_managed": it.lot_managed, "serial_managed": it.serial_managed,
            "theoretical": str(th), "counted": str(cnt) if cnt is not None else None,
            "difference": str(cnt - th) if cnt is not None else None, "is_counted": cnt is not None,
            "unit_cost": str(it.avg_cost) if it.avg_cost is not None else None,
            "counts": details.get(key, []),
            "serials_expected": expected, "serials_counted": scanned,
            "serials_missing": sorted(set(expected or []) - set(scanned or [])) if it.serial_managed else None,
            "serials_extra": sorted(set(scanned or []) - set(expected or [])) if it.serial_managed else None,
        })
    rows.sort(key=lambda r: (r["location"] or "~", r["code"], r["variant_code"] or "", r["lot_number"] or ""))

    counted_rows = [r for r in rows if r["is_counted"]]
    uncounted_rows = [r for r in rows if not r["is_counted"] and Decimal(r["theoretical"]) != 0]
    cost = lambda r: Decimal(r["unit_cost"] or 0)  # noqa: E731
    return {
        "rows": rows,
        "totals": {
            "rows_in_scope": len(rows),
            "rows_counted": len(counted_rows),
            "items_in_scope": len({r["item_id"] for r in rows}),
            "items_counted": len({r["item_id"] for r in counted_rows}),
            "rows_with_difference": sum(1 for r in counted_rows if Decimal(r["difference"]) != 0),
            "value_difference": str(sum((Decimal(r["difference"]) * cost(r) for r in counted_rows), Decimal(0)).quantize(Decimal("0.01"))),
            "rows_uncounted": len(uncounted_rows),
            "value_uncounted": str(sum((Decimal(r["theoretical"]) * cost(r) for r in uncounted_rows), Decimal(0)).quantize(Decimal("0.01"))),
            "counts_total": len(counts),
            "counts_rejected": sum(1 for c in counts if not c.accepted),
        },
    }


def close(db: Session, c: service.Ctx, s: InventorySession, zero_uncounted: bool) -> int:
    """Rettifiche: righe contate → quantità contata; righe non contate → azzerate solo se richiesto."""
    data = summary(db, s)
    n = 0
    for r in data["rows"]:
        item = db.get(Item, r["item_id"])
        variant_id = r["variant_id"]
        if item.serial_managed:
            extra = r["serials_extra"] or []
            # matricole attese ma non lette: tolte solo se si conferma che l'inventario è concluso
            missing = (r["serials_missing"] or []) if zero_uncounted else []
            if missing:
                service.apply_line(db, c, warehouse_id=s.warehouse_id, item_id=item.id, qty=-Decimal(len(missing)),
                                   reason="inventario", variant_id=variant_id, serials=missing)
            if extra:
                service.apply_line(db, c, warehouse_id=s.warehouse_id, item_id=item.id, qty=Decimal(len(extra)),
                                   reason="inventario", variant_id=variant_id, serials=extra, unit_cost=item.avg_cost)
            n += bool(missing or extra)
            continue
        if r["is_counted"]:
            diff = Decimal(r["difference"])
        elif zero_uncounted:
            diff = -Decimal(r["theoretical"])
        else:
            continue
        if diff == 0:
            continue
        lot = None
        if r["lot_number"]:
            lot = service.get_or_create_lot(db, c.tenant_id, item, r["lot_number"],
                                            date.fromisoformat(r["expiry_date"]) if r["expiry_date"] else None)
        service.move(db, c, warehouse_id=s.warehouse_id, item=item, qty=diff, reason="inventario", variant_id=variant_id,
                     lot=lot, unit_cost=item.avg_cost, check_negative=False)
        n += 1
    s.status, s.closed_at, s.operation_id = "chiuso", datetime.now().astimezone(), c.operation_id
    s.zero_uncounted = zero_uncounted
    return n
