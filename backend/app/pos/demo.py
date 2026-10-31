"""Vendita al banco di esempio (aziende demo col pacchetto Plus o Pro): reparti, una cassa e due settimane di scontrini."""

import random
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal as D

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import VatRate
from app.core.db import set_tenant
from app.core.models import User, Warehouse
from app.pos import service as pos
from app.pos.models import PosDepartment, PosRegister
from app.scadenzario.models import FinancialAccount

DEPARTMENTS = {
    "abbigliamento": [("ABB", "Abbigliamento", "22", "blue"), ("ACC", "Accessori", "22", "teal"), ("SART", "Sartoria e riparazioni", "22", "grape"), ("VARI", "Varie", "22", "gray")],
    "ferramenta": [("UTE", "Utensili e ferramenta", "22", "blue"), ("MIN", "Minuteria a peso", "22", "orange"), ("CHIAV", "Duplicazione chiavi", "22", "blue"), ("VARI", "Varie", "22", "gray")],
    "panetteria": [("PANE", "Pane", "4", "yellow"), ("DOLCI", "Pasticceria", "10", "pink"), ("VARI", "Varie", "22", "gray")],
}


def load_pos_demo(db: Session, tenant_id: uuid.UUID, kind: str) -> None:
    set_tenant(db, tenant_id)
    if db.scalar(select(PosRegister.id).where(PosRegister.tenant_id == tenant_id).limit(1)):
        return
    user = db.scalar(select(User).where(User.tenant_id == tenant_id).order_by(User.created_at))
    wh = db.scalar(select(Warehouse).where(Warehouse.tenant_id == tenant_id).order_by(Warehouse.code))
    if user is None or wh is None:
        return
    vats = {v.code: v.id for v in db.scalars(select(VatRate))}
    deps = []
    for n, (code, name, vat, color) in enumerate(DEPARTMENTS.get(kind, DEPARTMENTS["ferramenta"]), start=1):
        d = PosDepartment(tenant_id=tenant_id, code=code, name=name, vat_rate_id=vats.get(vat), rt_department=n, color=color, sort_order=n)
        db.add(d)
        deps.append(d)
    db.flush()
    from app.anagrafiche.models import Item
    for it in db.scalars(select(Item).where(Item.tenant_id == tenant_id, Item.pos_department_id.is_(None))):
        it.pos_department_id = deps[0].id  # ogni articolo nel reparto principale (le statistiche per reparto hanno senso)
    cash = db.scalar(select(FinancialAccount.id).where(FinancialAccount.kind == "cassa"))
    bank = db.scalar(select(FinancialAccount.id).where(FinancialAccount.kind == "banca"))
    reg = PosRegister(tenant_id=tenant_id, code="C1", name="Cassa negozio", warehouse_id=wh.id, mode="negozio",
                      cash_account_id=cash, card_account_id=bank, quick_keys=[], devices={}, settings={})
    db.add(reg)
    db.flush()
    cat = [i for i in pos.catalog(db, reg)["items"] if i["price"] and not i["lot_managed"] and not i["serial_managed"]
           and (not i["has_variants"] or i["variants"])]
    if not cat:
        return
    reg.quick_keys = [{"type": "item", "id": i["id"], "label": i["description"][:22], "color": None} for i in cat[:8]] + \
                     [{"type": "department", "id": str(d.id), "label": d.name[:22], "color": d.color} for d in deps[1:3]]
    rnd = random.Random(str(tenant_id))
    today = date.today()
    from app.anagrafiche.models import Promotion
    db.add(Promotion(tenant_id=tenant_id, name=f"{cat[0]['description'][:40]}: prendi 3 paghi 2", date_from=today - timedelta(days=20),
                     date_to=today + timedelta(days=40), item_scope="articoli", item_ids=[uuid.UUID(cat[0]["id"])], category_ids=[],
                     customer_scope="tutti", customer_category_ids=[], party_ids=[], mechanic="nxm", buy_qty=3, pay_qty=2,
                     price_type="sconto", value=D(0), vat_included=True, min_qty=D(0)))
    db.add(Promotion(tenant_id=tenant_id, name="Spendi 100 €, risparmi 10 €", date_from=today - timedelta(days=20),
                     date_to=today + timedelta(days=40), item_scope="tutti", item_ids=[], category_ids=[], customer_scope="tutti",
                     customer_category_ids=[], party_ids=[], mechanic="soglia", threshold=D(100), price_type="importo", value=D(10),
                     vat_included=True, min_qty=D(0)))
    db.flush()
    hours = [9, 10, 10, 11, 11, 11, 12, 12, 13, 16, 17, 17, 18, 18, 18, 19]
    for back in range(14, -1, -1):
        day = today - timedelta(days=back)
        if day.weekday() == 6:
            continue
        ses = pos.open_session(db, reg, user.id, D("100"))
        ses.opened_at = datetime.combine(day, time(8, 30), timezone.utc)
        for _ in range(rnd.randint(4, 9) if back else 3):
            lines = []
            for it in rnd.sample(cat, k=min(len(cat), rnd.randint(1, 3))):
                ln = {"item_id": it["id"], "quantity": str(rnd.randint(1, 2)), "unit_price_gross": it["price"]}
                if it["has_variants"]:
                    ln["variant_id"] = rnd.choice(it["variants"])["id"]
                lines.append(ln)
            if rnd.random() < 0.25:
                dep = rnd.choice(deps[1:3])
                lines.append({"department_id": str(dep.id), "unit_price_gross": str(rnd.choice([D("2.50"), D("5.00"), D("8.00")]))})
            total = sum((D(ln["unit_price_gross"]) * D(ln.get("quantity", "1")) for ln in lines), D(0)).quantize(D("0.01"))
            total += sum((D(x["unit_price_gross"]) for x in pos.promo_lines(db, lines)), D(0))
            if rnd.random() < 0.45:
                pays = [{"method": "contanti", "amount": str(((total // 5) + 1) * 5)}]
            else:
                pays = [{"method": rnd.choice(["carta", "bancomat"]), "amount": str(total)}]
            d, _, _ = pos.create_sale(db, reg, user.id, {"client_uuid": str(uuid.uuid4()), "date": day.isoformat(), "lines": lines, "payments": pays})
            if back:
                d.created_at = datetime.combine(day, time(rnd.choice(hours), rnd.randint(0, 59)), timezone.utc) - timedelta(hours=1)
        if back:  # i giorni passati sono chiusi, con qualche centesimo di differenza ogni tanto
            expected = D(pos.session_summary(db, ses)["expected_cash"])
            pos.close_session(db, ses, user.id, expected - (D("0.50") if rnd.random() < 0.2 else 0), f"{1000 - back:04d}", None)
            ses.closed_at = datetime.combine(day, time(19, 30), timezone.utc)
    db.flush()
