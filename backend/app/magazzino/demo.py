"""Giacenze di esempio per le aziende demo."""

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Item, ItemVariant
from app.core.models import Warehouse
from app.magazzino import service
from app.magazzino.models import StockMovement


def load_stock_demo(db: Session, tenant_id: uuid.UUID) -> None:
    if db.scalar(select(StockMovement.id).where(StockMovement.tenant_id == tenant_id).limit(1)):
        return
    wh = db.scalar(select(Warehouse).where(Warehouse.tenant_id == tenant_id).order_by(Warehouse.code))
    if wh is None:
        return
    rnd = random.Random(str(tenant_id))
    c = service.Ctx(tenant_id=tenant_id, user_id=None, reference="Giacenza iniziale (demo)")
    today = date.today()
    for it in db.scalars(select(Item).where(Item.tenant_id == tenant_id, Item.stock_managed, Item.is_kit.is_(False),
                                            Item.item_type == "articolo")):
        cost = it.last_cost
        if it.has_variants:
            for v in db.scalars(select(ItemVariant).where(ItemVariant.item_id == it.id)):
                q = rnd.choice([0, 1, 2, 3, 4, 6, 8])
                if q:
                    service.apply_line(db, c, warehouse_id=wh.id, item_id=it.id, qty=D(q), reason="carico", variant_id=v.id, unit_cost=cost)
        elif it.serial_managed:
            sns = [f"{it.code[-3:]}{today:%y}{n:05d}" for n in range(1, rnd.randint(3, 6))]
            service.apply_line(db, c, warehouse_id=wh.id, item_id=it.id, qty=D(len(sns)), reason="carico", serials=sns, unit_cost=cost)
        elif it.lot_managed:
            life = it.shelf_life_days or 30
            for n, days in enumerate((max(1, life // 4), max(2, life // 2))):
                lot = f"L{today:%y%m}{n + 1:02d}"
                service.apply_line(db, c, warehouse_id=wh.id, item_id=it.id, qty=D(rnd.randint(5, 40)), reason="carico",
                                   lot_number=lot, expiry_date=today + timedelta(days=days), unit_cost=cost)
        else:
            base = int(it.min_stock or 10)
            service.apply_line(db, c, warehouse_id=wh.id, item_id=it.id, qty=D(rnd.randint(max(1, base // 2), base * 3)),
                               reason="carico", unit_cost=cost)
    db.flush()
