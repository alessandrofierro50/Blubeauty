"""Motore prezzi: dato articolo, cliente, quantità e data, trova il prezzo da applicare e spiega da dove arriva.

Ordine:
  1. prezzo netto concordato con il cliente (valido alla data, scaglione più alto raggiunto);
  2. altrimenti il prezzo più conveniente per il cliente tra
     - listino del cliente (scaglioni, sconti di riga, poi sconti del cliente)
     - promozioni attive per quel cliente e quell'articolo;
Tutti i prezzi restituiti sono IVA esclusa, più il corrispondente IVA inclusa.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.anagrafiche import pricing
from app.anagrafiche.models import (
    Category,
    CustomerPrice,
    Item,
    ItemPrice,
    ItemVariant,
    Party,
    PriceList,
    Promotion,
    VatRate,
)

Q4 = Decimal("0.0001")
CENT = Decimal("0.01")


@dataclass
class PriceResult:
    unit_price: Decimal | None  # IVA esclusa, già scontato
    source: str  # cliente | promozione | listino | nessuno
    source_label: str
    vat_rate: Decimal
    list_price: Decimal | None = None  # listino IVA esclusa, prima degli sconti del cliente
    discounts: list[Decimal] = field(default_factory=list)  # sconti del cliente applicati al listino
    price_list_code: str | None = None
    promotion_id: str | None = None
    alternatives: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        def s(v):
            return None if v is None else str(v)

        with_vat = None
        if self.unit_price is not None:
            with_vat = (self.unit_price * (Decimal(100) + self.vat_rate) / Decimal(100)).quantize(CENT, ROUND_HALF_UP)
        return {
            "unit_price": s(self.unit_price),
            "unit_price_vat_included": s(with_vat),
            "vat_rate": s(self.vat_rate),
            "source": self.source,
            "source_label": self.source_label,
            "list_price": s(self.list_price),
            "price_list_code": self.price_list_code,
            "discounts": [s(d) for d in self.discounts],
            "promotion_id": self.promotion_id,
            "alternatives": self.alternatives,
        }


def _category_chain(db: Session, category_id) -> set:
    """La categoria dell'articolo e le sue categorie padre (una promo su "Uomo" vale anche per "Uomo › T-shirt")."""
    chain = set()
    while category_id and category_id not in chain:
        chain.add(category_id)
        category_id = db.scalar(select(Category.parent_id).where(Category.id == category_id))
    return chain


def _vat(db: Session, item: Item) -> Decimal:
    if item.vat_rate_id:
        v = db.get(VatRate, item.vat_rate_id)
        if v:
            return Decimal(v.rate)
    return Decimal(22)


def list_price(db: Session, item: Item, price_list: PriceList | None, qty: Decimal, variant_id=None,
               vat_rate: Decimal = Decimal(22)) -> Decimal | None:
    """Prezzo di listino IVA esclusa per la quantità (scaglione più alto raggiunto) con gli sconti di riga."""
    if price_list is None:
        return None
    rows = db.scalars(
        select(ItemPrice).where(ItemPrice.item_id == item.id, ItemPrice.price_list_id == price_list.id,
                                ItemPrice.min_qty <= qty).order_by(ItemPrice.min_qty.desc())
    ).all()
    if not rows:
        return None
    r = rows[0]
    price = Decimal(r.price)
    if variant_id:
        v = db.get(ItemVariant, variant_id)
        if v and v.price_delta:
            price += Decimal(v.price_delta)
    net = pricing.cascade(price, r.discount1, r.discount2, r.discount3)
    return pricing.net_of_vat(net, vat_rate, price_list.vat_included)


def _promo_price(p: Promotion, base_ex_vat: Decimal | None, vat_rate: Decimal) -> Decimal | None:
    v = Decimal(p.value)
    if p.price_type == "prezzo":
        return pricing.net_of_vat(v, vat_rate, p.vat_included)
    if base_ex_vat is None:
        return None
    if p.price_type == "sconto":
        return (base_ex_vat * (Decimal(100) - v) / Decimal(100)).quantize(Q4, ROUND_HALF_UP)
    if p.price_type == "importo":
        off = pricing.net_of_vat(v, vat_rate, p.vat_included)
        return max(Decimal(0), base_ex_vat - off).quantize(Q4, ROUND_HALF_UP)
    return None


def active_promotions(db: Session, item: Item, party: Party | None, qty: Decimal, on: date) -> list[Promotion]:
    cats = _category_chain(db, item.category_id)
    promos = db.scalars(
        select(Promotion).where(Promotion.active, Promotion.mechanic == "prezzo", Promotion.date_from <= on,
                                Promotion.date_to >= on, Promotion.min_qty <= qty)
    ).all()
    out = []
    for p in promos:
        if p.item_scope == "articoli" and item.id not in (p.item_ids or []):
            continue
        if p.item_scope == "categorie" and not cats.intersection(p.category_ids or []):
            continue
        if p.customer_scope == "clienti" and (party is None or party.id not in (p.party_ids or [])):
            continue
        if p.customer_scope == "categorie" and (party is None or party.customer_category_id not in (p.customer_category_ids or [])):
            continue
        out.append(p)
    return out


def resolve_price(db: Session, item: Item, party: Party | None = None, qty: Decimal = Decimal(1),
                  on: date | None = None, variant_id=None) -> PriceResult:
    on = on or date.today()
    qty = Decimal(qty)
    vat_rate = _vat(db, item)

    # 1. prezzo netto del cliente
    if party is not None:
        rows = db.scalars(
            select(CustomerPrice).where(
                CustomerPrice.party_id == party.id, CustomerPrice.item_id == item.id, CustomerPrice.min_qty <= qty,
                or_(CustomerPrice.valid_from.is_(None), CustomerPrice.valid_from <= on),
                or_(CustomerPrice.valid_to.is_(None), CustomerPrice.valid_to >= on),
                or_(CustomerPrice.variant_id.is_(None), CustomerPrice.variant_id == variant_id),
            )
        ).all()
        if rows:
            # la variante specifica vince sul prezzo generico, poi lo scaglione più alto
            best = max(rows, key=lambda r: (r.variant_id is not None, r.min_qty))
            return PriceResult(unit_price=Decimal(best.net_price).quantize(Q4), source="cliente",
                               source_label="Prezzo netto concordato", vat_rate=vat_rate)

    # 2a. listino del cliente (o predefinito) con i suoi sconti
    pl = None
    if party is not None and party.price_list_id:
        pl = db.get(PriceList, party.price_list_id)
    if pl is None:
        pl = db.scalar(select(PriceList).where(PriceList.is_default)) or db.scalar(select(PriceList).order_by(PriceList.code))
    base = list_price(db, item, pl, qty, variant_id, vat_rate)
    if base is None and pl is not None and not pl.is_default:
        # il listino del cliente non ha l'articolo: si usa il listino predefinito (con gli sconti del cliente)
        default = db.scalar(select(PriceList).where(PriceList.is_default))
        if default is not None:
            fallback = list_price(db, item, default, qty, variant_id, vat_rate)
            if fallback is not None:
                pl, base = default, fallback
    candidates: list[PriceResult] = []
    if base is not None:
        discounts = [d for d in ((party.discount1, party.discount2) if party else ()) if d]
        net = pricing.cascade(base, *discounts) if discounts else base
        candidates.append(PriceResult(unit_price=net, source="listino", source_label=f"Listino {pl.code}",
                                      vat_rate=vat_rate, list_price=base, discounts=[Decimal(d) for d in discounts],
                                      price_list_code=pl.code))

    # 2b. promozioni (calcolate sul listino al lordo degli sconti cliente: non si cumulano)
    for p in active_promotions(db, item, party, qty, on):
        price = _promo_price(p, base, vat_rate)
        if price is not None:
            candidates.append(PriceResult(unit_price=price, source="promozione", source_label=p.name, vat_rate=vat_rate,
                                          list_price=base, price_list_code=pl.code if pl else None,
                                          promotion_id=str(p.id)))

    if not candidates:
        return PriceResult(unit_price=None, source="nessuno", source_label="Nessun prezzo definito", vat_rate=vat_rate)
    best = min(candidates, key=lambda c: c.unit_price)
    best.alternatives = [{"source": c.source, "label": c.source_label, "unit_price": str(c.unit_price)}
                         for c in candidates if c is not best]
    return best
