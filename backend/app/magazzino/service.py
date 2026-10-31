"""Logica di magazzino: unico punto in cui si scrivono movimenti e giacenze.

Ogni funzione lavora nella transazione corrente (niente commit qui): se una riga fallisce,
l'intera operazione viene annullata dal chiamante."""

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.anagrafiche.models import AppSetting, Item, ItemComponent, ItemVariant
from app.magazzino.models import Lot, Serial, StockBalance, StockMovement

# causale -> segno ammesso (+1 entrata, -1 uscita, 0 entrambi)
REASONS: dict[str, tuple[str, int]] = {
    "carico": ("Carico", 1),
    "scarico": ("Scarico", -1),
    "rettifica": ("Rettifica", 0),
    "inventario": ("Inventario", 0),
    "trasferimento": ("Trasferimento", 0),
    "acquisto": ("Acquisto", 1),
    "reso_fornitore": ("Reso a fornitore", -1),
    "vendita": ("Vendita", -1),
    "reso_cliente": ("Reso da cliente", 1),
    "omaggio": ("Omaggio", -1),
    "scarto": ("Scarto / deperimento", -1),
}
COST_REASONS = {"carico", "acquisto"}  # aggiornano costo ultimo e medio ponderato
Q4 = Decimal("0.0001")


def fail(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, message)


def allow_negative(db: Session, tenant_id) -> bool:
    s = db.get(AppSetting, (tenant_id, "stock_policy"))
    return bool((s.value if s else {}).get("allow_negative", True))


@dataclass
class Ctx:
    tenant_id: uuid.UUID
    user_id: uuid.UUID | None
    operation_id: uuid.UUID = field(default_factory=uuid.uuid4)
    moved_at: datetime | None = None
    party_id: uuid.UUID | None = None
    reference: str | None = None
    document_type: str | None = None
    document_id: uuid.UUID | None = None


def _balance(db: Session, tenant_id, warehouse_id, item_id, variant_id, lot_id) -> StockBalance:
    """Riga di giacenza bloccata per l'aggiornamento (creata se manca)."""
    db.execute(
        insert(StockBalance)
        .values(id=uuid.uuid4(), tenant_id=tenant_id, warehouse_id=warehouse_id, item_id=item_id,
                variant_id=variant_id, lot_id=lot_id, on_hand=0, reserved=0, ordered=0)
        .on_conflict_do_nothing(constraint="uq_stock_balance")
    )
    return db.scalar(
        select(StockBalance).where(
            StockBalance.warehouse_id == warehouse_id, StockBalance.item_id == item_id,
            StockBalance.variant_id.is_(None) if variant_id is None else StockBalance.variant_id == variant_id,
            StockBalance.lot_id.is_(None) if lot_id is None else StockBalance.lot_id == lot_id,
        ).with_for_update()
    )


def _update_cost(db: Session, item: Item, qty: Decimal, unit_cost: Decimal | None) -> None:
    if unit_cost is None or qty <= 0:
        return
    total = db.scalar(select(func.coalesce(func.sum(StockBalance.on_hand), 0)).where(StockBalance.item_id == item.id)) or Decimal(0)
    total = max(Decimal(total), Decimal(0))
    old = Decimal(item.avg_cost or unit_cost)
    item.avg_cost = ((old * total + Decimal(unit_cost) * qty) / (total + qty)).quantize(Q4, ROUND_HALF_UP)
    item.last_cost = Decimal(unit_cost)


def move(db: Session, c: Ctx, *, warehouse_id, item: Item, qty: Decimal, reason: str, variant_id=None,
         lot: Lot | None = None, serial: Serial | None = None, unit_cost: Decimal | None = None,
         check_negative: bool = True) -> StockMovement:
    """Movimento elementare: aggiorna la giacenza e registra il movimento."""
    qty = Decimal(qty)
    if qty == 0:
        raise fail("Quantità zero")
    if reason not in REASONS:
        raise fail(f"Causale {reason} sconosciuta")
    sign = REASONS[reason][1]
    if sign and (qty > 0) != (sign > 0):
        raise fail(f"La causale «{REASONS[reason][0]}» non ammette quantità {'negative' if qty < 0 else 'positive'}")
    bal = _balance(db, c.tenant_id, warehouse_id, item.id, variant_id, lot.id if lot else None)
    new = Decimal(bal.on_hand) + qty
    if qty < 0 and new < 0 and check_negative and (lot or serial or not allow_negative(db, c.tenant_id)):
        raise fail(f"Giacenza insufficiente per {item.code} — {item.description}"
                   + (f" (lotto {lot.lot_number})" if lot else "") + f": disponibili {Decimal(bal.on_hand).normalize()}")
    if reason in COST_REASONS:
        _update_cost(db, item, qty, unit_cost)
    bal.on_hand = new
    mv = StockMovement(
        tenant_id=c.tenant_id, warehouse_id=warehouse_id, item_id=item.id, variant_id=variant_id,
        lot_id=lot.id if lot else None, serial_id=serial.id if serial else None, quantity=qty,
        unit_cost=unit_cost if unit_cost is not None else item.avg_cost, reason=reason, party_id=c.party_id,
        operation_id=c.operation_id, reference=c.reference, user_id=c.user_id, document_type=c.document_type,
        document_id=c.document_id,
    )
    if c.moved_at:
        mv.moved_at = c.moved_at
    db.add(mv)
    db.flush()
    return mv


def get_or_create_lot(db: Session, tenant_id, item: Item, lot_number: str, expiry: date | None = None,
                      production: date | None = None, supplier_id=None) -> Lot:
    lot_number = lot_number.strip().upper()
    lot = db.scalar(select(Lot).where(Lot.item_id == item.id, Lot.lot_number == lot_number))
    if lot is None:
        if expiry is None and item.shelf_life_days:
            expiry = (production or date.today()) + timedelta(days=item.shelf_life_days)
        lot = Lot(tenant_id=tenant_id, item_id=item.id, lot_number=lot_number, expiry_date=expiry,
                  production_date=production, supplier_id=supplier_id)
        db.add(lot)
        db.flush()
    elif expiry and not lot.expiry_date:
        lot.expiry_date = expiry
    return lot


def fefo_allocation(db: Session, warehouse_id, item_id, variant_id, qty: Decimal) -> list[tuple[Lot, Decimal]]:
    """Lotti da cui prelevare: prima quelli che scadono prima (First Expired, First Out)."""
    rows = db.execute(
        select(StockBalance, Lot).join(Lot, Lot.id == StockBalance.lot_id).where(
            StockBalance.warehouse_id == warehouse_id, StockBalance.item_id == item_id,
            StockBalance.variant_id.is_(None) if variant_id is None else StockBalance.variant_id == variant_id,
            StockBalance.on_hand > 0,
        ).order_by(Lot.expiry_date.asc().nulls_last(), Lot.created_at)
    ).all()
    out, left = [], Decimal(qty)
    for bal, lot in rows:
        if left <= 0:
            break
        take = min(Decimal(bal.on_hand), left)
        out.append((lot, take))
        left -= take
    if left > 0:
        raise fail(f"Giacenza nei lotti insufficiente: mancano {left.normalize()}")
    return out


def apply_line(db: Session, c: Ctx, *, warehouse_id, item_id, qty: Decimal, reason: str, variant_id=None,
               lot_number: str | None = None, expiry_date: date | None = None, serials: list[str] | None = None,
               unit_cost: Decimal | None = None, _depth: int = 0) -> list[StockMovement]:
    """Applica una riga di operazione gestendo varianti, lotti (FEFO), matricole e kit."""
    item = db.get(Item, item_id)
    if item is None:
        raise fail("Articolo inesistente")
    qty = Decimal(qty)
    if qty == 0:
        return []
    if item.is_kit:
        # Il kit non ha giacenza propria: si movimentano i componenti (in uscita, o in entrata se è un reso).
        if qty > 0 and reason != "reso_cliente":
            raise fail(f"{item.code}: i kit non si caricano, carica i singoli componenti")
        if _depth > 5:
            raise fail("Distinta base troppo profonda o circolare")
        out = []
        for comp in db.scalars(select(ItemComponent).where(ItemComponent.item_id == item.id)):
            out += apply_line(db, c, warehouse_id=warehouse_id, item_id=comp.component_id, qty=qty * Decimal(comp.quantity),
                              reason=reason, _depth=_depth + 1)
        return out
    if not item.stock_managed:
        return []  # servizi e articoli non gestiti: nessun movimento
    if item.has_variants and variant_id is None:
        raise fail(f"{item.code}: indica la variante (taglia/colore)")
    if variant_id is not None and db.scalar(select(ItemVariant.item_id).where(ItemVariant.id == variant_id)) != item.id:
        raise fail("Variante non valida")

    if item.serial_managed:
        serials = [s.strip().upper() for s in (serials or []) if s and s.strip()]
        if len(set(serials)) != len(serials):
            raise fail(f"{item.code}: matricole duplicate")
        if qty != int(qty) or abs(int(qty)) != len(serials):
            raise fail(f"{item.code}: indica una matricola per ogni pezzo ({abs(qty).normalize()} pezzi, {len(serials)} matricole)")
        out = []
        for sn in serials:
            ser = db.scalar(select(Serial).where(Serial.item_id == item.id, Serial.serial_number == sn))
            if qty > 0:
                if ser and ser.status == "disponibile" and ser.warehouse_id is not None:
                    raise fail(f"Matricola {sn} già presente in magazzino")
                if ser is None:
                    ser = Serial(tenant_id=c.tenant_id, item_id=item.id, variant_id=variant_id, serial_number=sn,
                                 supplier_id=c.party_id if reason == "acquisto" else None,
                                 purchase_date=(c.moved_at or datetime.now()).date(), purchase_cost=unit_cost)
                    db.add(ser)
                    db.flush()
                ser.status, ser.warehouse_id = "disponibile", warehouse_id
            else:
                if ser is None or ser.status != "disponibile" or ser.warehouse_id != warehouse_id:
                    raise fail(f"Matricola {sn} non disponibile in questo magazzino")
                if reason == "vendita":
                    day = (c.moved_at or datetime.now()).date()
                    ser.status, ser.customer_id, ser.sale_date = "venduto", c.party_id, day
                    ser.warranty_until = day + relativedelta(months=item.warranty_months) if item.warranty_months else None
                elif reason == "reso_fornitore":
                    ser.status = "reso"
                elif reason != "trasferimento":
                    ser.status = "dismesso"
                ser.warehouse_id = None
            out.append(move(db, c, warehouse_id=warehouse_id, item=item, qty=Decimal(1 if qty > 0 else -1), reason=reason,
                            variant_id=variant_id, serial=ser, unit_cost=unit_cost))
        return out

    if item.lot_managed:
        if qty > 0:
            if not lot_number:
                raise fail(f"{item.code}: indica il lotto")
            lot = get_or_create_lot(db, c.tenant_id, item, lot_number, expiry_date,
                                    supplier_id=c.party_id if reason == "acquisto" else None)
            return [move(db, c, warehouse_id=warehouse_id, item=item, qty=qty, reason=reason, variant_id=variant_id,
                         lot=lot, unit_cost=unit_cost)]
        if lot_number:
            lot = db.scalar(select(Lot).where(Lot.item_id == item.id, Lot.lot_number == lot_number.strip().upper()))
            if lot is None:
                raise fail(f"Lotto {lot_number} inesistente per {item.code}")
            allocation = [(lot, -qty)]
        else:
            allocation = fefo_allocation(db, warehouse_id, item.id, variant_id, -qty)
        return [move(db, c, warehouse_id=warehouse_id, item=item, qty=-q, reason=reason, variant_id=variant_id, lot=lot,
                     unit_cost=unit_cost) for lot, q in allocation]

    return [move(db, c, warehouse_id=warehouse_id, item=item, qty=qty, reason=reason, variant_id=variant_id,
                 unit_cost=unit_cost)]


def transfer(db: Session, c: Ctx, *, from_wh, to_wh, item_id, qty: Decimal, variant_id=None, lot_number=None,
             serials=None) -> list[StockMovement]:
    """Trasferimento: uscita dal magazzino di partenza e entrata identica (stesso lotto/matricola) in quello di arrivo."""
    if from_wh == to_wh:
        raise fail("Magazzino di partenza e di arrivo coincidono")
    if Decimal(qty) <= 0:
        raise fail("Quantità da trasferire non valida")
    outs = apply_line(db, c, warehouse_id=from_wh, item_id=item_id, qty=-Decimal(qty), reason="trasferimento",
                      variant_id=variant_id, lot_number=lot_number, serials=serials)
    ins = []
    for mv in outs:
        item = db.get(Item, mv.item_id)
        lot = db.get(Lot, mv.lot_id) if mv.lot_id else None
        ser = db.get(Serial, mv.serial_id) if mv.serial_id else None
        if ser:
            ser.status, ser.warehouse_id = "disponibile", to_wh
        ins.append(move(db, c, warehouse_id=to_wh, item=item, qty=-Decimal(mv.quantity), reason="trasferimento",
                        variant_id=mv.variant_id, lot=lot, serial=ser, unit_cost=mv.unit_cost, check_negative=False))
    return outs + ins


def stock_by_key(db: Session, item_ids: list | None = None, warehouse_id=None) -> dict:
    """{(item_id, variant_id, lot_id): (on_hand, reserved, ordered)} sommati sui magazzini richiesti."""
    q = select(StockBalance.item_id, StockBalance.variant_id, StockBalance.lot_id,
               func.sum(StockBalance.on_hand), func.sum(StockBalance.reserved), func.sum(StockBalance.ordered)) \
        .group_by(StockBalance.item_id, StockBalance.variant_id, StockBalance.lot_id)
    if item_ids is not None:
        q = q.where(StockBalance.item_id.in_(item_ids))
    if warehouse_id:
        q = q.where(StockBalance.warehouse_id == warehouse_id)
    return {(r[0], r[1], r[2]): (Decimal(r[3]), Decimal(r[4]), Decimal(r[5])) for r in db.execute(q)}
