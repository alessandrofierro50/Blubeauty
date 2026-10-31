"""Vendita al banco: catalogo per la cassa, lettura codici (anche a peso), scontrini, resi, aperture e chiusure.

Lo scontrino è un documento di vendita "SCO" con prezzi IVA inclusa, intestato al "Cliente al banco" (o a un cliente
scelto), che scarica subito il magazzino. Ogni vendita arriva con un client_uuid generato dalla cassa: se la rete cade
la cassa la rimanda e il server non la registra due volte."""

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.anagrafiche import pricing
from app.anagrafiche.price_engine import _promo_price
from app.anagrafiche.models import AppSetting, Category, Item, ItemBarcode, ItemImage, ItemPrice, ItemVariant, Party, PriceList, Promotion, VatRate
from app.core import media
from app.core.models import Company
from app.documenti import service as docs
from app.documenti import vendite_service as sales
from app.documenti.models import Document, DocumentLine, DocumentLink
from app.pos import promos
from app.pos.models import PosCashMove, PosDepartment, PosPayment, PosRegister, PosSession
from app.scadenzario.models import FinancialAccount

CENT = Decimal("0.01")
METHODS = {"contanti": "Contanti", "carta": "Carta di credito", "bancomat": "Bancomat", "buono": "Buono / gift card",
           "buono_pasto": "Buoni pasto", "satispay": "Satispay", "altro": "Altro"}
CASH = "contanti"
DEFAULT_SETTINGS = {
    # EAN-13 delle bilance: 2 + codice PLU + valore + controllo. Valore = peso in grammi o prezzo in centesimi.
    "scale_barcode": {"enabled": True, "prefixes": ["20", "21", "22", "23", "24", "25", "26", "27", "28", "29"], "plu_digits": 5,
                      "value": "peso", "value_digits": 5},
    "lottery": False,  # chiedi il codice lotteria degli scontrini
    "allow_negative_price": False,
}


def fail(msg: str, code: int = status.HTTP_422_UNPROCESSABLE_ENTITY) -> HTTPException:
    return HTTPException(code, msg)


def _q(v) -> Decimal:
    return Decimal(v or 0)


def settings(db: Session, tenant_id) -> dict:
    s = db.get(AppSetting, (tenant_id, "pos"))
    out = {**DEFAULT_SETTINGS, **(s.value if s and s.value else {})}
    out["scale_barcode"] = {**DEFAULT_SETTINGS["scale_barcode"], **(out.get("scale_barcode") or {})}
    return out


def save_settings(db: Session, tenant_id, value: dict) -> dict:
    s = db.get(AppSetting, (tenant_id, "pos"))
    if s is None:
        s = AppSetting(tenant_id=tenant_id, key="pos", value={})
        db.add(s)
    s.value = {k: value[k] for k in DEFAULT_SETTINGS if k in value}
    db.flush()
    return settings(db, tenant_id)


def walk_in_customer(db: Session, tenant_id) -> Party:
    p = db.scalar(select(Party).where(Party.code == "BANCO"))
    if p is None:
        p = Party(tenant_id=tenant_id, code="BANCO", name="Cliente al banco", is_customer=True, is_supplier=False,
                  person_type="privato", country="IT", custom={}, notes="Cliente generico degli scontrini (creato da BluBeauty)")
        db.add(p)
        db.flush()
    return p


def _vat_map(db: Session) -> dict:
    return {v.id: v for v in db.scalars(select(VatRate))}


def _default_vat(db: Session) -> VatRate | None:
    return db.scalar(select(VatRate).where(VatRate.code == "22"))


def gross(net: Decimal, rate: Decimal) -> Decimal:
    return (net * (100 + rate) / 100).quantize(CENT, ROUND_HALF_UP)


# ====================================================================== catalogo per la cassa (anche offline)


def _price_list(db: Session, reg: PosRegister) -> PriceList | None:
    pl = db.get(PriceList, reg.price_list_id) if reg.price_list_id else None
    return pl or db.scalar(select(PriceList).where(PriceList.is_default)) or db.scalar(select(PriceList).order_by(PriceList.code))


def catalog(db: Session, reg: PosRegister) -> dict:
    """Articoli vendibili con prezzo al pubblico (IVA inclusa) del listino della cassa e promozioni del giorno."""
    pl = _price_list(db, reg)
    vats = _vat_map(db)
    default_vat = _default_vat(db)
    today = date.today()
    items = db.scalars(select(Item).where(Item.active)).all()
    prices: dict = {}
    if pl is not None:
        for p in db.scalars(select(ItemPrice).where(ItemPrice.price_list_id == pl.id).order_by(ItemPrice.min_qty)):
            prices.setdefault(p.item_id, p)  # scaglione base (quantità minima più bassa)
    barcodes = defaultdict(list)
    for b in db.scalars(select(ItemBarcode)):
        barcodes[b.item_id].append({"code": b.barcode, "variant_id": str(b.variant_id) if b.variant_id else None, "quantity": str(b.quantity)})
    variants = defaultdict(list)
    for v in db.scalars(select(ItemVariant).where(ItemVariant.active)):
        variants[v.item_id].append({"id": str(v.id), "code": v.code, "label": " ".join(x for x in (v.color, v.size, v.format) if x) or v.code,
                                    "delta": str(v.price_delta) if v.price_delta else None})
    images = {}
    for im in db.scalars(select(ItemImage).order_by(ItemImage.sort_order)):
        images.setdefault(im.item_id, media.urls(im.file_name)["thumb_url"])
    cats = {c.id: c for c in db.scalars(select(Category))}
    promos = db.scalars(select(Promotion).where(Promotion.active, Promotion.date_from <= today, Promotion.date_to >= today,
                                                Promotion.customer_scope == "tutti", Promotion.min_qty <= 1, Promotion.mechanic == "prezzo")).all()
    chain_ids = _category_chains(db)
    out = []
    for it in items:
        v = vats.get(it.vat_rate_id) or default_vat
        rate = Decimal(v.rate) if v else Decimal(22)
        row = prices.get(it.id)
        net = None
        if row is not None:
            base = pricing.cascade(Decimal(row.price), row.discount1, row.discount2, row.discount3)
            net = pricing.net_of_vat(base, rate, pl.vat_included)
        promo = None
        chain = set()
        cid = it.category_id
        while cid and cid not in chain:
            chain.add(cid)
            cid = cats[cid].parent_id if cid in cats else None
        for p in promos:
            if p.item_scope == "articoli" and it.id not in (p.item_ids or []):
                continue
            if p.item_scope == "categorie" and not chain.intersection(p.category_ids or []):
                continue
            pp = _promo_price(p, net, rate)
            if pp is not None and (net is None or pp < net) and (promo is None or pp < promo[0]):
                promo = (pp, p.name)
        price_net = promo[0] if promo else net
        vlist = []
        for va in variants.get(it.id, []):  # maggiorazione della variante (non sui prezzi in promozione)
            vp = price_net
            if va["delta"] and vp is not None and not promo:
                vp = vp + pricing.net_of_vat(Decimal(va["delta"]), rate, pl.vat_included)
            vlist.append({**va, "price": str(gross(vp, rate)) if vp is not None else None})
        out.append({
            "id": str(it.id), "code": it.code, "description": it.description, "unit": it.unit, "plu": it.plu,
            "barcodes": barcodes.get(it.id, []), "variants": vlist, "has_variants": it.has_variants,
            "vat_rate_id": str(v.id) if v else None, "vat_rate": str(rate),
            "price": str(gross(price_net, rate)) if price_net is not None else None,
            "list_price": str(gross(net, rate)) if net is not None and promo else None, "promo": promo[1] if promo else None,
            "department_id": str(it.pos_department_id) if it.pos_department_id else None, "sold_by_weight": it.sold_by_weight,
            "lot_managed": it.lot_managed, "serial_managed": it.serial_managed, "stock_managed": it.stock_managed,
            "image": images.get(it.id), "active": it.active, "categories": sorted(chain_ids.get(it.category_id, set())),
        })
    deps = [{"id": str(d.id), "code": d.code, "name": d.name, "vat_rate_id": str(d.vat_rate_id) if d.vat_rate_id else None,
             "vat_rate": str(vats[d.vat_rate_id].rate) if d.vat_rate_id in vats else "22", "color": d.color, "rt_department": d.rt_department}
            for d in db.scalars(select(PosDepartment).where(PosDepartment.active).order_by(PosDepartment.sort_order, PosDepartment.code))]
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "items": out, "departments": deps,
            "vat_rates": [{"id": str(v.id), "code": v.code, "rate": str(v.rate), "nature": v.nature} for v in vats.values() if v.active],
            "settings": settings(db, reg.tenant_id), "price_list": pl.code if pl else None,
            "promotions": [promo_out(p) for p in active_cash_promotions(db)]}


@dataclass
class ScaleCode:
    plu: str
    quantity: Decimal | None = None
    amount: Decimal | None = None


def parse_scale_barcode(code: str, cfg: dict) -> ScaleCode | None:
    """EAN-13 della bilancia: 2X + PLU + peso (grammi) o prezzo (centesimi) + cifra di controllo."""
    sc = cfg.get("scale_barcode") or {}
    code = (code or "").strip()
    if not sc.get("enabled") or len(code) != 13 or not code.isdigit():
        return None
    if not any(code.startswith(p) for p in sc.get("prefixes") or []):
        return None
    plu_digits = int(sc.get("plu_digits", 5))
    value_digits = int(sc.get("value_digits", 5))
    plu = code[2:2 + plu_digits]
    raw = code[2 + plu_digits:2 + plu_digits + value_digits]
    if len(raw) != value_digits:
        return None
    if sc.get("value") == "prezzo":
        return ScaleCode(plu=plu.lstrip("0") or "0", amount=Decimal(raw) / 100)
    return ScaleCode(plu=plu.lstrip("0") or "0", quantity=Decimal(raw) / 1000)


def resolve_code(db: Session, reg: PosRegister, code: str) -> dict:
    """Barcode, codice articolo, PLU o codice a peso → articolo con quantità (e prezzo se il codice lo contiene)."""
    code = (code or "").strip()
    if not code:
        raise fail("Codice vuoto")
    b = db.scalar(select(ItemBarcode).where(ItemBarcode.barcode == code))
    if b is not None:
        return {"item_id": str(b.item_id), "variant_id": str(b.variant_id) if b.variant_id else None, "quantity": str(b.quantity or 1)}
    it = db.scalar(select(Item).where(Item.active, or_(func.upper(Item.code) == code.upper(), Item.plu == code)))
    if it is not None:
        return {"item_id": str(it.id), "variant_id": None, "quantity": "1"}
    sc = parse_scale_barcode(code, settings(db, reg.tenant_id))
    if sc is not None:
        it = db.scalar(select(Item).where(Item.active, or_(Item.plu == sc.plu, Item.plu == sc.plu.zfill(5))))
        if it is None:
            raise fail(f"Codice bilancia: nessun articolo con PLU {sc.plu}", status.HTTP_404_NOT_FOUND)
        return {"item_id": str(it.id), "variant_id": None, "quantity": str(sc.quantity) if sc.quantity is not None else "1",
                "amount": str(sc.amount) if sc.amount is not None else None, "scale": True}
    raise fail("Codice non trovato", status.HTTP_404_NOT_FOUND)


# ====================================================================== aperture e chiusure


def open_session(db: Session, reg: PosRegister, user_id, opening_float: Decimal) -> PosSession:
    cur = current_session(db, reg)
    if cur is not None:
        raise fail("La cassa è già aperta", status.HTTP_409_CONFLICT)
    s = PosSession(tenant_id=reg.tenant_id, register_id=reg.id, user_id=user_id, opening_float=opening_float, status="aperta", summary={})
    db.add(s)
    db.flush()
    return s


def current_session(db: Session, reg: PosRegister) -> PosSession | None:
    return db.scalar(select(PosSession).where(PosSession.register_id == reg.id, PosSession.status == "aperta"))


def session_summary(db: Session, s: PosSession) -> dict:
    pays = db.execute(select(PosPayment.method, func.sum(PosPayment.amount), func.count()).where(PosPayment.session_id == s.id)
                      .group_by(PosPayment.method)).all()
    by_method = {m: {"label": METHODS.get(m, m), "amount": str(_q(a).quantize(CENT)), "count": n} for m, a, n in pays}
    moves = db.execute(select(PosCashMove.kind, func.sum(PosCashMove.amount)).where(PosCashMove.session_id == s.id)
                       .group_by(PosCashMove.kind)).all()
    mv = {k: _q(a) for k, a in moves}
    cash = _q(next((a for m, a, _ in pays if m == CASH), 0))
    expected = _q(s.opening_float) + cash + mv.get("versamento", Decimal(0)) - mv.get("prelievo", Decimal(0))
    docs_q = db.execute(select(Document.doc_type, func.count(), func.sum(Document.total)).where(
        Document.pos_session_id == s.id, Document.status != "annullato").group_by(Document.doc_type)).all()
    by_type = {t: {"count": n, "total": str(_q(tot).quantize(CENT))} for t, n, tot in docs_q}
    vat = defaultdict(lambda: [Decimal(0), Decimal(0)])
    for d in db.scalars(select(Document).where(Document.pos_session_id == s.id, Document.status != "annullato",
                                               Document.doc_type.in_(("SCO", "RSO"))).options(selectinload(Document.lines))):
        sign = -1 if d.doc_type == "RSO" else 1
        for r in docs.vat_summary(d):
            vat[str(r["rate"])][0] += r["taxable"] * sign
            vat[str(r["rate"])][1] += r["vat"] * sign
    sales_total = sum((_q(v["total"]) for t, v in by_type.items() if t in ("SCO", "FTI")), Decimal(0))
    returns_total = _q(by_type.get("RSO", {}).get("total"))
    return {
        "opening_float": str(_q(s.opening_float)), "by_method": by_method, "withdrawals": str(mv.get("prelievo", Decimal(0))),
        "deposits": str(mv.get("versamento", Decimal(0))), "expected_cash": str(expected.quantize(CENT)), "by_type": by_type,
        "sales_total": str(sales_total.quantize(CENT)), "returns_total": str(returns_total.quantize(CENT)),
        "net_total": str((sales_total - returns_total).quantize(CENT)),
        "receipts": by_type.get("SCO", {}).get("count", 0), "average": str((sales_total / by_type["SCO"]["count"]).quantize(CENT)) if by_type.get("SCO", {}).get("count") else "0.00",
        "vat": [{"rate": k, "taxable": str(v[0].quantize(CENT)), "vat": str(v[1].quantize(CENT))} for k, v in sorted(vat.items(), key=lambda x: -Decimal(x[0]))],
    }


def close_session(db: Session, s: PosSession, user_id, counted_cash: Decimal, z_number: str | None, notes: str | None) -> PosSession:
    if s.status != "aperta":
        raise fail("La cassa è già chiusa", status.HTTP_409_CONFLICT)
    summ = session_summary(db, s)
    s.expected_cash = Decimal(summ["expected_cash"])
    s.counted_cash = counted_cash
    s.difference = (counted_cash - s.expected_cash).quantize(CENT)
    s.z_number, s.notes = z_number, notes
    s.summary = summ
    s.status, s.closed_at, s.closed_by = "chiusa", datetime.now(timezone.utc), user_id
    db.flush()
    return s


# ====================================================================== scontrini e resi


def _account(db: Session, reg: PosRegister, method: str):
    if method == CASH:
        acc_id = reg.cash_account_id or db.scalar(select(FinancialAccount.id).where(FinancialAccount.kind == "cassa", FinancialAccount.active)
                                                   .order_by(FinancialAccount.is_default.desc()))
    else:
        acc_id = reg.card_account_id or db.scalar(select(FinancialAccount.id).where(FinancialAccount.kind == "banca", FinancialAccount.active)
                                                   .order_by(FinancialAccount.is_default.desc()))
    return acc_id


def _payments(total: Decimal, payments: list[dict]) -> list[dict]:
    """Controlla i pagamenti e calcola il resto: solo il contante può superare il dovuto."""
    if not payments:
        raise fail("Indica il pagamento")
    out, paid = [], Decimal(0)
    for p in payments:
        m = p.get("method")
        if m not in METHODS:
            raise fail(f"Metodo di pagamento non valido: {m}")
        amt = _q(p.get("amount")).quantize(CENT)
        if amt <= 0 and total > 0:
            raise fail("Importo del pagamento non valido")
        out.append({"method": m, "amount": amt})
        paid += amt
    change = (paid - total).quantize(CENT)
    if change < 0:
        raise fail(f"Mancano {(-change):.2f} € al totale")
    if change > 0:
        cash = next((p for p in out if p["method"] == CASH), None)
        if cash is None or cash["amount"] < change:
            raise fail("Il resto si dà solo sul contante: riduci l'importo pagato con carta o buoni")
        cash["tendered"] = cash["amount"]
        cash["amount"] -= change
    return [p for p in out if p["amount"] != 0 or total == 0] or out[:1], change


def _build_lines(db: Session, d: Document, lines: list[dict], vat_included: bool, negative_ok: set | None = None) -> None:
    """Righe del documento. Prezzi negativi solo per le righe di sconto delle promozioni di cassa (o il loro reso)."""
    vats = _vat_map(db)
    default_vat = _default_vat(db)
    for n, ln in enumerate(lines, start=1):
        it = db.get(Item, uuid.UUID(str(ln["item_id"]))) if ln.get("item_id") else None
        dep = db.get(PosDepartment, uuid.UUID(str(ln["department_id"]))) if ln.get("department_id") else None
        if ln.get("item_id") and it is None:
            raise fail("Articolo inesistente")
        if it is None and dep is None and not ln.get("description"):
            raise fail(f"Riga {n}: indica articolo, reparto o descrizione")
        qty = _q(ln.get("quantity") or 1)
        if qty <= 0:
            raise fail(f"Riga {n}: quantità non valida")
        price = _q(ln.get("unit_price_gross"))
        promo_line = bool(ln.get("_promo")) or (negative_ok is not None and str(ln.get("origin_line_id")) in negative_ok)
        if price < 0 and not (promo_line and it is None and dep is None):
            raise fail(f"Riga {n}: prezzo non valido")
        if it is not None and it.has_variants and not ln.get("variant_id") and it.stock_managed:
            raise fail(f"{it.code}: scegli taglia/colore")
        vat_id = (uuid.UUID(str(ln["vat_rate_id"])) if ln.get("vat_rate_id") else None) or (it.vat_rate_id if it else None) \
            or (dep.vat_rate_id if dep else None) or (default_vat.id if default_vat else None)
        disc = _q(ln.get("discount")) or None
        row = DocumentLine(
            tenant_id=d.tenant_id, line_no=n, item_id=it.id if it else None,
            variant_id=uuid.UUID(str(ln["variant_id"])) if ln.get("variant_id") else None,
            description=(ln.get("description") or (it.description if it else dep.name))[:500], unit=it.unit if it else None,
            quantity=qty, discount1=disc, vat_rate_id=vat_id, department_id=dep.id if dep else (it.pos_department_id if it else None),
            lot_number=(ln.get("lot_number") or "").strip().upper() or None, serials=[s.strip().upper() for s in ln.get("serials") or [] if s.strip()],
            origin_line_id=uuid.UUID(str(ln["origin_line_id"])) if ln.get("origin_line_id") else None,
            price_source=("Promo cassa" if price < 0 else (ln.get("price_source") or "Banco"))[:60],
        )
        if vat_included:
            row.unit_price_gross = price
        else:  # fattura al banco: prezzo netto ricavato da quello al pubblico
            rate = _q(vats[vat_id].rate) if vat_id in vats else Decimal(22)
            row.unit_price = (price * 100 / (100 + rate)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        d.lines.append(row)
    db.flush()
    docs.recompute(db, d)


# ====================================================================== promozioni di cassa


def active_cash_promotions(db: Session, on: date | None = None) -> list[Promotion]:
    on = on or date.today()
    return list(db.scalars(select(Promotion).where(Promotion.active, Promotion.mechanic.in_(promos.MECHANICS), Promotion.date_from <= on,
                                                   Promotion.date_to >= on, Promotion.customer_scope == "tutti")
                           .order_by(Promotion.name)))


def promo_out(p: Promotion) -> dict:
    return {"id": str(p.id), "name": p.name, "mechanic": p.mechanic, "item_scope": p.item_scope,
            "item_ids": [str(x) for x in p.item_ids or []], "category_ids": [str(x) for x in p.category_ids or []],
            "buy_qty": p.buy_qty, "pay_qty": p.pay_qty, "value": str(p.value), "price_type": p.price_type,
            "threshold": str(p.threshold) if p.threshold is not None else None}


def _to_ppromo(p: Promotion) -> promos.PPromo:
    return promos.PPromo(id=str(p.id), name=p.name, mechanic=p.mechanic, item_scope=p.item_scope,
                         item_ids={str(x) for x in p.item_ids or []}, category_ids={str(x) for x in p.category_ids or []},
                         buy_qty=p.buy_qty, pay_qty=p.pay_qty, value=Decimal(p.value), price_type=p.price_type,
                         threshold_cents=promos.rhu(Decimal(p.threshold) * 100) if p.threshold is not None else None)


def _category_chains(db: Session) -> dict:
    cats = {c.id: c.parent_id for c in db.scalars(select(Category))}
    out = {}
    for cid in cats:
        chain, cur = set(), cid
        while cur and cur not in chain:
            chain.add(cur)
            cur = cats.get(cur)
        out[cid] = {str(x) for x in chain}
    return out


def line_cents(price: Decimal, qty: Decimal, discount: Decimal | None) -> int:
    g = pricing.cascade(Decimal(price), discount)
    return promos.rhu(g * Decimal(qty) * 100)


def promo_lines(db: Session, lines: list[dict]) -> list[dict]:
    """Righe di sconto (negative) per le righe di uno scontrino, già pronte per _build_lines."""
    active = active_cash_promotions(db)
    if not active:
        return []
    chains = _category_chains(db)
    items = {str(i.id): i for i in db.scalars(select(Item).where(Item.id.in_([uuid.UUID(str(l["item_id"])) for l in lines if l.get("item_id")])))}
    deps = {str(d.id): d for d in db.scalars(select(PosDepartment))}
    default_vat = _default_vat(db)
    plines = []
    for n, ln in enumerate(lines):
        it = items.get(str(ln.get("item_id"))) if ln.get("item_id") else None
        dep = deps.get(str(ln.get("department_id"))) if ln.get("department_id") else None
        vat = (it.vat_rate_id if it else None) or (dep.vat_rate_id if dep else None) or (default_vat.id if default_vat else None)
        price, qty, disc = _q(ln.get("unit_price_gross")), _q(ln.get("quantity") or 1), _q(ln.get("discount"))
        plines.append(promos.PLine(key=str(n), item_id=str(it.id) if it else None, price_cents=promos.rhu(price * 100), quantity=qty,
                                   amount_cents=line_cents(price, qty, disc or None), vat_rate_id=str(vat) if vat else None,
                                   categories=chains.get(it.category_id, set()) if it else set(), manual_discount=disc > 0))
    return [{"_promo": True, "description": r["description"], "quantity": "1", "unit_price_gross": str(Decimal(r["amount_cents"]) / 100),
             "vat_rate_id": r["vat_rate_id"], "promotion_id": r["promotion_id"]}
            for r in promos.compute(plines, [_to_ppromo(p) for p in active])]


def _existing(db: Session, client_uuid) -> Document | None:
    return db.scalar(select(Document).where(Document.client_uuid == client_uuid)) if client_uuid else None


def _session_for(db: Session, reg: PosRegister, session_id) -> PosSession:
    s = db.get(PosSession, session_id) if session_id else current_session(db, reg)
    if s is None or s.register_id != reg.id:
        raise fail("La cassa non è aperta", status.HTTP_409_CONFLICT)
    if s.status != "aperta":
        raise fail("Questa apertura di cassa è già chiusa: riapri la cassa", status.HTTP_409_CONFLICT)
    return s


def create_sale(db: Session, reg: PosRegister, user_id, body: dict) -> tuple[Document, Decimal, bool]:
    """Scontrino (o fattura al banco se c'è il cliente da fatturare). Restituisce documento, resto, già registrato."""
    client_uuid = uuid.UUID(str(body["client_uuid"])) if body.get("client_uuid") else None
    prev = _existing(db, client_uuid)
    if prev is not None:
        return prev, Decimal(prev.fiscal.get("change") or 0), True
    s = _session_for(db, reg, body.get("session_id"))
    invoice_to = body.get("invoice_party_id")
    party = db.get(Party, uuid.UUID(str(invoice_to))) if invoice_to else None
    if invoice_to and (party is None or not party.is_customer):
        raise fail("Cliente da fatturare non valido")
    if not body.get("lines"):
        raise fail("Lo scontrino è vuoto")
    co = db.scalar(select(Company).order_by(Company.name))
    when = date.fromisoformat(body["date"][:10]) if body.get("date") else date.today()
    customer = party or (db.get(Party, uuid.UUID(str(body["customer_id"]))) if body.get("customer_id") else None) or walk_in_customer(db, reg.tenant_id)
    d = Document(tenant_id=reg.tenant_id, company_id=co.id, direction="vendita", doc_type="FTI" if party else "SCO", series="",
                 doc_date=when, year=when.year, party_id=customer.id, warehouse_id=reg.warehouse_id, store_id=reg.store_id,
                 register_id=reg.id, pos_session_id=s.id, client_uuid=client_uuid, moves_stock=True, prices_vat_included=not party,
                 payment_term_id=None, created_by=user_id, transport={}, attachment_ids=[], print_options={},
                 fiscal={"lottery": (body.get("lottery_code") or "").strip().upper() or None}, reference=None)
    db.add(d)
    lines = [ln for ln in body["lines"] if not ln.get("_promo") and _q(ln.get("unit_price_gross")) >= 0]
    _build_lines(db, d, lines + promo_lines(db, lines), vat_included=not party)
    total = _q(d.total)
    payments = body.get("payments") or []
    if party and payments:  # fattura al banco: lo scorporo per riga può spostare qualche centesimo rispetto alla cassa
        paid = sum((_q(p.get("amount")) for p in payments), Decimal(0))
        if paid != total and abs(paid - total) <= Decimal("0.05") and not any(p.get("method") == CASH for p in payments):
            payments = [*payments[:-1], {**payments[-1], "amount": str(_q(payments[-1]["amount"]) + total - paid)}]
    pays, change = _payments(total, payments)
    sales.confirm_sale(db, d, user_id, force=True)
    d.fiscal = {**d.fiscal, "change": str(change), "rt": None, "simulated": True}
    for p in pays:
        db.add(PosPayment(tenant_id=reg.tenant_id, session_id=s.id, document_id=d.id, method=p["method"], amount=p["amount"],
                          tendered=p.get("tendered"), account_id=None if party else _account(db, reg, p["method"])))
    db.flush()
    if not party:  # documento commerciale sul registratore telematico (o già stampato dalla cassa senza rete)
        from app.periferiche import service as per
        per.fiscalize(db, reg, d, user_id, local_result=body.get("rt_result"))
    if party:  # fattura al banco: già incassata
        from app.scadenzario import service as due
        for inst in db.scalars(select(due.Installment).where(due.Installment.document_id == d.id)):
            method = pays[0]["method"]
            due.pay(db, inst, pay_date=when, account_id=_account(db, reg, method), method="MP01" if method == CASH else "MP08", user_id=user_id)
    db.flush()
    return d, change, False


def create_return(db: Session, reg: PosRegister, user_id, body: dict) -> Document:
    """Reso o annullo al banco: rientro merce (se richiesto) e rimborso, con riferimento allo scontrino d'origine."""
    client_uuid = uuid.UUID(str(body["client_uuid"])) if body.get("client_uuid") else None
    prev = _existing(db, client_uuid)
    if prev is not None:
        return prev
    s = _session_for(db, reg, body.get("session_id"))
    orig = db.get(Document, uuid.UUID(str(body["original_id"]))) if body.get("original_id") else None
    if body.get("original_id") and (orig is None or orig.doc_type != "SCO"):
        raise fail("Scontrino d'origine non trovato")
    if not body.get("lines"):
        raise fail("Indica cosa viene reso")
    if orig is not None:  # non si rende più di quanto venduto
        sold = {str(l.id): l for l in orig.lines}
        for ln in body["lines"]:
            o = sold.get(str(ln.get("origin_line_id") or ""))
            if o is not None and _q(ln.get("quantity")) > _q(o.quantity) - _q(o.qty_processed):
                raise fail(f"{o.description}: si possono rendere al massimo {(_q(o.quantity) - _q(o.qty_processed)).normalize()}")
    co = db.scalar(select(Company).order_by(Company.name))
    d = Document(tenant_id=reg.tenant_id, company_id=co.id, direction="vendita", doc_type="RSO", series="", doc_date=date.today(),
                 year=date.today().year, party_id=orig.party_id if orig else walk_in_customer(db, reg.tenant_id).id,
                 warehouse_id=reg.warehouse_id, store_id=reg.store_id, register_id=reg.id, pos_session_id=s.id, client_uuid=client_uuid,
                 moves_stock=bool(body.get("restock", True)), prices_vat_included=True, created_by=user_id, transport={},
                 attachment_ids=[], print_options={}, reference=(f"Reso scontrino n. {orig.number} del {orig.doc_date.strftime('%d/%m/%Y')}" if orig else body.get("reason")),
                 fiscal={"kind": "annullo" if body.get("void") else "reso", "reason": body.get("reason"),
                         "original": {"number": orig.number, "date": orig.doc_date.isoformat(), "rt": (orig.fiscal or {}).get("rt")} if orig else None})
    db.add(d)
    neg = set()
    if orig is not None:
        for o in orig.lines:
            if o.unit_price_gross is not None and o.unit_price_gross < 0:
                neg.add(str(o.id))
        for ln in body["lines"]:  # la riga di sconto si rende al suo importo, non a uno inventato
            o = next((x for x in orig.lines if str(x.id) == str(ln.get("origin_line_id") or "")), None)
            if o is not None and str(o.id) in neg:
                ln["unit_price_gross"], ln["item_id"], ln["department_id"] = str(o.unit_price_gross), None, None
                ln["description"], ln["vat_rate_id"] = o.description, str(o.vat_rate_id) if o.vat_rate_id else None
    _build_lines(db, d, body["lines"], vat_included=True, negative_ok=neg)
    total = _q(d.total)
    if total < 0:
        raise fail("Il reso non può essere negativo: rendi anche gli articoli a cui si riferisce lo sconto")
    method = body.get("refund_method") or CASH
    if method not in METHODS:
        raise fail("Metodo di rimborso non valido")
    sales.confirm_sale(db, d, user_id, force=True)
    db.add(PosPayment(tenant_id=reg.tenant_id, session_id=s.id, document_id=d.id, method=method, amount=-total,
                      account_id=_account(db, reg, method)))
    if orig is not None:
        db.add(DocumentLink(tenant_id=reg.tenant_id, from_id=orig.id, to_id=d.id))
    db.flush()
    from app.periferiche import service as per
    per.fiscalize(db, reg, d, user_id, local_result=body.get("rt_result"))
    db.flush()
    return d


def receipt_out(db: Session, d: Document) -> dict:
    pays = db.scalars(select(PosPayment).where(PosPayment.document_id == d.id)).all()
    return {
        "id": str(d.id), "doc_type": d.doc_type, "number": d.number, "year": d.year, "date": d.doc_date.isoformat(),
        "created_at": d.created_at.isoformat() if d.created_at else None, "status": d.status, "client_uuid": str(d.client_uuid) if d.client_uuid else None,
        "party_id": str(d.party_id), "party_name": db.get(Party, d.party_id).name, "total": str(d.total), "taxable": str(d.taxable_total),
        "vat": str(d.vat_total), "vat_summary": [{k: str(v) if v is not None else None for k, v in r.items()} for r in docs.vat_summary(d)],
        "lines": [{"id": str(l.id), "item_id": str(l.item_id) if l.item_id else None, "description": l.description, "quantity": str(l.quantity),
                   "unit": l.unit, "unit_price_gross": str(l.unit_price_gross) if l.unit_price_gross is not None else None,
                   "unit_price": str(l.unit_price), "discount": str(l.discount1) if l.discount1 else None,
                   "total": str(docs.gross_amount(l)) if d.prices_vat_included else str(l.line_total), "vat_rate": str(l.vat_rate),
                   "returnable": str(_q(l.quantity) - _q(l.qty_processed)), "lot_number": l.lot_number, "serials": l.serials or []} for l in d.lines],
        "payments": [{"method": p.method, "label": METHODS.get(p.method, p.method), "amount": str(p.amount),
                      "tendered": str(p.tendered) if p.tendered is not None else None} for p in pays],
        "change": (d.fiscal or {}).get("change"), "fiscal": d.fiscal or {}, "reference": d.reference,
    }
