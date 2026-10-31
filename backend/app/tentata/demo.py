"""Tentata vendita di esempio (azienda demo con il modulo attivo): un agente, un furgone col suo giro clienti e
un ordine da consegnare, così il primo giro si può preparare, caricare e fare subito."""

import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Item, Party
from app.core.db import set_tenant
from app.core.models import User, Warehouse
from app.core.security import hash_password
from app.documenti import vendite_service as sales
from app.documenti.models import Document, DocumentLine
from app.scadenzario.models import FinancialAccount
from app.tentata import service as tv
from app.tentata.models import Van

AGENT_EMAIL = "agente@demo.blubeauty.it"
WAREHOUSE_EMAIL = "magazzino@demo.blubeauty.it"


def load_tentata_demo(db: Session, tenant_id: uuid.UUID, password: str) -> None:
    set_tenant(db, tenant_id)
    if db.scalar(select(Van.id).limit(1)):
        return
    agent = db.scalar(select(User).where(User.email == AGENT_EMAIL))
    if agent is None:
        agent = User(tenant_id=tenant_id, email=AGENT_EMAIL, full_name="Luca Agente", role="agente", password_hash=hash_password(password))
        db.add(agent)
    if db.scalar(select(User.id).where(User.email == WAREHOUSE_EMAIL)) is None:
        db.add(User(tenant_id=tenant_id, email=WAREHOUSE_EMAIL, full_name="Gino Magazzino", role="magazzino",
                    password_hash=hash_password(password)))
    db.flush()
    home = db.scalar(select(Warehouse).order_by(Warehouse.code))
    cash = db.scalar(select(FinancialAccount).where(FinancialAccount.kind == "cassa").order_by(FinancialAccount.name))
    van = tv.create_van(db, tenant_id, {"code": "F1", "name": "Ducato bianco", "vehicle": "Fiat Ducato", "plate": "FX123LE",
                                        "series": "A1", "home_warehouse_id": str(home.id), "agent_id": str(agent.id),
                                        "max_discount": "10", "cash_account_id": str(cash.id) if cash else None})
    customers = db.scalars(select(Party).where(Party.is_customer, Party.code != "BANCO").order_by(Party.code).limit(4)).all()
    tv.save_route(db, van, [{"party_id": str(p.id), "weekdays": [0, 1, 2, 3, 4, 5]} for p in customers])
    # un ordine da consegnare al primo cliente del giro: entra nella proposta di carico
    items = db.scalars(select(Item).where(Item.stock_managed, Item.active, Item.is_kit.is_(False), Item.has_variants.is_(False),
                                          Item.serial_managed.is_(False), Item.lot_managed.is_(False)).order_by(Item.code).limit(2)).all()
    if customers and items:
        from app.core.models import Company
        from datetime import date
        co = db.scalar(select(Company).order_by(Company.name))
        today = date.today()
        d = Document(tenant_id=tenant_id, company_id=co.id, direction="vendita", doc_type="ORC", series="", doc_date=today,
                     year=today.year, party_id=customers[0].id, warehouse_id=home.id, moves_stock=False, transport={},
                     attachment_ids=[], print_options={}, fiscal={}, delivery={}, reference="Ordine telefonico")
        db.add(d)
        for n, it in enumerate(items, start=1):
            d.lines.append(DocumentLine(tenant_id=tenant_id, line_no=n, item_id=it.id, description=it.description, unit=it.unit,
                                        quantity=Decimal(3 * n), unit_price=Decimal(it.last_cost or 10) * Decimal("1.6"),
                                        vat_rate_id=it.vat_rate_id, serials=[]))
        db.flush()
        sales.confirm_sale(db, d, None, force=True)
    db.flush()
