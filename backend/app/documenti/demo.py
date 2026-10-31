"""Acquisti di esempio per le aziende demo: soglie di riordino, un ordine aperto, un DDT da fatturare, una fattura."""

import uuid
from datetime import date, timedelta
from decimal import Decimal as D

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Item, ItemPrice, Party
from app.core.db import set_tenant
from app.core.deps import TenantContext
from app.core.models import User
from app.documenti import service as docs
from app.documenti.acquisti_router import DocIn, LineIn, create_doc
from app.documenti.models import ContractLine, Document
from app.magazzino.models import StockBalance



def load_purchases_demo(db: Session, tenant_id: uuid.UUID) -> None:
    set_tenant(db, tenant_id)
    if db.scalar(select(Document.id).where(Document.tenant_id == tenant_id).limit(1)):
        return
    user = db.scalar(select(User).where(User.tenant_id == tenant_id).order_by(User.created_at))
    suppliers = list(db.scalars(select(Party).where(Party.tenant_id == tenant_id, Party.is_supplier).order_by(Party.code)))
    items = list(db.scalars(select(Item).where(
        Item.tenant_id == tenant_id, Item.stock_managed, Item.item_type == "articolo", Item.is_kit.is_(False),
        Item.has_variants.is_(False), Item.lot_managed.is_(False), Item.serial_managed.is_(False)).order_by(Item.code)))
    if user is None or not suppliers or len(items) < 3:
        return
    ctx = TenantContext(user=user, state=None, db=db)  # type: ignore[arg-type]
    today = date.today()

    # Soglie di riordino: metà degli articoli risulta da riordinare
    for n, it in enumerate(items):
        it.preferred_supplier_id = suppliers[n % len(suppliers)].id
        on_hand = db.scalar(select(func.coalesce(func.sum(StockBalance.on_hand), 0)).where(StockBalance.item_id == it.id)) or D(0)
        it.reorder_point = D(on_hand) + (D(15) if n % 2 == 0 else D(-1) if on_hand > 1 else D(0))
        it.reorder_qty = D(10)
    db.flush()

    def line(it: Item, q: int) -> LineIn:
        return LineIn(item_id=it.id, quantity=D(q), unit_price=it.last_cost or D("1.00"))

    s0, s1 = suppliers[0], suppliers[1 % len(suppliers)]
    # Ordine al fornitore confermato, ancora da ricevere
    o = create_doc(DocIn(doc_type="ORF", party_id=s0.id, doc_date=today - timedelta(days=6),
                         lines=[line(items[0], 12), line(items[2 % len(items)], 6)]), ctx)
    docs.confirm_purchase(db, db.get(Document, uuid.UUID(o["id"])), user.id)
    # DDT ricevuto, da fatturare a fine mese
    d = create_doc(DocIn(doc_type="DDTF", party_id=s1.id, doc_date=today - timedelta(days=3), external_number="245",
                         external_date=today - timedelta(days=4), lines=[line(items[1], 500 if (items[1].last_cost or 1) < D(1) else 4)]), ctx)
    docs.confirm_purchase(db, db.get(Document, uuid.UUID(d["id"])), user.id)
    # Fattura accompagnatoria già registrata
    f = create_doc(DocIn(doc_type="FTF", party_id=s0.id, doc_date=today - timedelta(days=15), external_number="1187",
                         external_date=today - timedelta(days=15), lines=[line(items[-1], 3)]), ctx)
    docs.confirm_purchase(db, db.get(Document, uuid.UUID(f["id"])), user.id)
    db.flush()


def load_sales_demo(db: Session, tenant_id: uuid.UUID) -> None:
    """Vendite di esempio: un preventivo, un ordine aperto, un DDT da fatturare, una fattura, un contratto ricorrente."""
    from app.documenti import vendite_router as vr
    from app.documenti import vendite_service as sales
    from app.documenti.models import Contract

    set_tenant(db, tenant_id)
    if db.scalar(select(Document.id).where(Document.tenant_id == tenant_id, Document.direction == "vendita").limit(1)):
        return
    user = db.scalar(select(User).where(User.tenant_id == tenant_id).order_by(User.created_at))
    customers = list(db.scalars(select(Party).where(Party.tenant_id == tenant_id, Party.is_customer).order_by(Party.code)))
    items = list(db.scalars(select(Item).where(
        Item.tenant_id == tenant_id, Item.item_type == "articolo", Item.is_kit.is_(False),
        Item.has_variants.is_(False), Item.lot_managed.is_(False), Item.serial_managed.is_(False),
        Item.id.in_(select(ItemPrice.item_id))).order_by(Item.code)))
    if user is None or not customers or not items:
        return
    ctx = TenantContext(user=user, state=None, db=db)  # type: ignore[arg-type]
    today = date.today()
    c0, c1 = customers[0], customers[1 % len(customers)]

    def lines(*pairs):
        return [vr.LineIn(item_id=items[i % len(items)].id, quantity=D(q)) for i, q in pairs]

    def make(doc_type, party, days_ago, pairs, confirm=True, **kw):
        out = vr.create_doc(vr.DocIn(doc_type=doc_type, party_id=party.id, doc_date=today - timedelta(days=days_ago),
                                     lines=lines(*pairs), **kw), ctx)
        d = db.get(Document, uuid.UUID(out["id"]))
        if confirm:
            sales.confirm_sale(db, d, user.id, force=True)
        return d

    from app.anagrafiche.models import PaymentTerm
    bb0 = db.scalar(select(PaymentTerm.id).where(PaymentTerm.code == "BB0"))
    make("FTI", c1, 75, [(0, 10), (1, 20)], payment_term_id=bb0)  # scaduta da tempo: da sollecitare
    make("FTI", c0, 40, [(2, 4)], payment_term_id=bb0)
    make("FTI", c0, 12, [(0, 2), (1, 3)])
    make("DDT", c1, 5, [(1, 2)], transport={"causale": "Vendita", "porto": "Franco", "a_cura": "Mittente", "colli": 1})
    make("ORC", c0, 2, [(0, 1), (2, 2)], reference="Ordine telefonico")
    make("PRV", c1, 1, [(0, 5), (1, 5), (2, 5)], valid_until=today + timedelta(days=30),
         print_options={"long_descriptions": True}, confirm=True)
    make("PRV", c0, 0, [(2, 1)], confirm=False)
    db.add(Contract(tenant_id=tenant_id, code="CT00001", party_id=c0.id, description="Assistenza e manutenzione",
                    start_date=today.replace(day=1), frequency_months=1, billing="anticipata", next_invoice_date=today,
                    auto_confirm=False, active=True,
                    lines=[ContractLine(tenant_id=tenant_id, line_no=1, description="Canone mensile di assistenza",
                                        quantity=D(1), unit_price=D("49.00"))]))
    db.flush()


def load_due_demo(db: Session, tenant_id: uuid.UUID) -> None:
    """Scadenzario di esempio: cassa e banca, un incasso parziale, affitto e F24 inseriti a mano."""
    from app.scadenzario import service as due
    from app.scadenzario.models import FinancialAccount, Installment

    set_tenant(db, tenant_id)
    if db.scalar(select(Installment.id).where(Installment.tenant_id == tenant_id, Installment.document_id.is_(None)).limit(1)):
        return
    today = date.today()
    due.backfill(db, tenant_id)
    first = db.scalar(select(Installment).where(Installment.direction == "attiva").order_by(Installment.issue_date.desc()))
    if first is not None and first.status != "pagata":
        due.pay(db, first, pay_date=today, amount=(D(first.amount) / 2).quantize(D("0.01")))
    for n in range(6):
        when = (today.replace(day=1) + timedelta(days=32 * (n + 1))).replace(day=5)
        db.add(Installment(tenant_id=tenant_id, direction="passiva", description=f"Affitto locale – {n + 1}/6", issue_date=today,
                           due_date=when, amount=D("1200"), paid_amount=D(0), method="MP05", status="aperta", seq=n + 1, total_seq=6))
    f24 = (today.replace(day=1) + timedelta(days=32)).replace(day=16)
    db.add(Installment(tenant_id=tenant_id, direction="passiva", description="F24 IVA e ritenute", issue_date=today, due_date=f24,
                       amount=D("2350"), paid_amount=D(0), method="MP05", status="aperta"))
    db.flush()


def load_accounts_demo(db: Session, tenant_id: uuid.UUID) -> None:
    """Prima dei documenti: cassa e banca (le scadenze nascono con la banca d'appoggio) ed email fittizie ai clienti."""
    from app.scadenzario.models import FinancialAccount

    set_tenant(db, tenant_id)
    if db.scalar(select(FinancialAccount.id).where(FinancialAccount.tenant_id == tenant_id).limit(1)):
        return
    today = date.today()
    db.add(FinancialAccount(tenant_id=tenant_id, name="Cassa", kind="cassa", opening_balance=D("350"),
                            opening_date=today - timedelta(days=120)))
    db.add(FinancialAccount(tenant_id=tenant_id, name="Banca Popolare Pugliese", kind="banca", iban="IT60X0542811101000000123456",
                            opening_balance=D("12500"), opening_date=today - timedelta(days=120), is_default=True))
    for n, p in enumerate(db.scalars(select(Party).where(Party.tenant_id == tenant_id, Party.is_customer, Party.email.is_(None))), start=1):
        p.email = f"cliente{n}@example.com"  # dominio riservato: nessuna email reale
    for p in db.scalars(select(Party).where(Party.tenant_id == tenant_id, Party.address.is_(None))):
        p.address, p.zip_code, p.city, p.province = "Via del Municipio 1", "73100", "Lecce", "LE"  # dati completi per la FE
    db.flush()
