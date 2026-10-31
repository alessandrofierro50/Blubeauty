"""Etichette: dati degli articoli per i modelli e traduzione dei modelli in ZPL (Zebra e compatibili).

Un modello è una lista di elementi posizionati in millimetri; lo stesso modello si vede nell'editor, si stampa su foglio
A4 dal browser oppure si manda in ZPL alla stampante di etichette."""

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche import pricing
from app.anagrafiche.models import Brand, Category, Item, ItemBarcode, ItemPrice, ItemVariant, PriceList, VatRate

FIELDS = {
    "description": "Descrizione", "code": "Codice articolo", "price": "Prezzo", "list_price": "Prezzo pieno (se in promozione)",
    "barcode": "Codice a barre", "unit": "Unità di misura", "brand": "Marca", "category": "Categoria", "variant": "Taglia/colore",
    "plu": "PLU", "date": "Data di stampa", "custom": "Testo fisso",
}
ELEMENT_TYPES = ("text", "barcode", "qr", "box")

DEFAULT_TEMPLATES = [
    {"name": "Scaffale 50×30", "width_mm": 50, "height_mm": 30, "elements": [
        {"type": "text", "field": "description", "x": 2, "y": 2, "w": 46, "size": 3.2, "lines": 2, "align": "left"},
        {"type": "text", "field": "price", "x": 2, "y": 10, "w": 46, "size": 7, "align": "right", "bold": True},
        {"type": "barcode", "field": "barcode", "x": 2, "y": 19, "h": 8, "module": 2, "text": "si"},
    ]},
    {"name": "Abbigliamento 40×60", "width_mm": 40, "height_mm": 60, "elements": [
        {"type": "text", "field": "brand", "x": 2, "y": 3, "w": 36, "size": 3, "align": "center", "bold": True},
        {"type": "text", "field": "description", "x": 2, "y": 9, "w": 36, "size": 3, "lines": 3, "align": "center"},
        {"type": "text", "field": "variant", "x": 2, "y": 21, "w": 36, "size": 4, "align": "center", "bold": True},
        {"type": "text", "field": "price", "x": 2, "y": 29, "w": 36, "size": 7, "align": "center", "bold": True},
        {"type": "barcode", "field": "barcode", "x": 4, "y": 42, "h": 10, "module": 2, "text": "si"},
    ]},
]


def money_it(v) -> str:
    q = Decimal(v).quantize(Decimal("0.01"), ROUND_HALF_UP)
    whole, dec = f"{q:.2f}".split(".")
    whole = f"{int(whole):,}".replace(",", ".")
    return f"€ {whole},{dec}"


def item_fields(db: Session, rows: list[dict], price_list_id=None) -> list[dict]:
    """[{item_id, variant_id?, quantity}] → dati per l'etichetta (prezzo al pubblico IVA inclusa del listino scelto)."""
    from app.pos.service import _default_vat  # stessa aliquota predefinita della cassa

    pl = db.get(PriceList, price_list_id) if price_list_id else None
    pl = pl or db.scalar(select(PriceList).where(PriceList.is_default)) or db.scalar(select(PriceList).order_by(PriceList.code))
    vats = {v.id: v for v in db.scalars(select(VatRate))}
    default_vat = _default_vat(db)
    today = date.today()
    expanded = []
    for r in rows:  # articolo con taglie/colori senza variante scelta: un'etichetta per ogni variante attiva
        it = db.get(Item, uuid.UUID(str(r["item_id"])))
        if it is None:
            continue
        if it.has_variants and not r.get("variant_id"):
            vs = db.scalars(select(ItemVariant).where(ItemVariant.item_id == it.id, ItemVariant.active).order_by(ItemVariant.code)).all()
            if vs:
                expanded += [{**r, "variant_id": str(v.id)} for v in vs]
                continue
        expanded.append(r)
    out = []
    for r in expanded:
        it = db.get(Item, uuid.UUID(str(r["item_id"])))
        var = db.get(ItemVariant, uuid.UUID(str(r["variant_id"]))) if r.get("variant_id") else None
        vat = vats.get(it.vat_rate_id) or default_vat
        rate = Decimal(vat.rate) if vat else Decimal(22)
        price = list_price = None
        row = db.scalar(select(ItemPrice).where(ItemPrice.item_id == it.id, ItemPrice.price_list_id == pl.id).order_by(ItemPrice.min_qty)) if pl else None
        if row is not None:
            base = Decimal(row.price) + (Decimal(var.price_delta) if var and var.price_delta else 0)
            net = pricing.net_of_vat(pricing.cascade(base, row.discount1, row.discount2, row.discount3), rate, pl.vat_included)
            from app.anagrafiche.price_engine import active_promotions, _promo_price
            promo = None
            for p in active_promotions(db, it, None, Decimal(1), today):
                if p.customer_scope != "tutti":
                    continue
                pp = _promo_price(p, net, rate)
                if pp is not None and pp < net and (promo is None or pp < promo):
                    promo = pp
            gross = lambda n: (n * (100 + rate) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)  # noqa: E731
            price = gross(promo if promo is not None else net)
            list_price = gross(net) if promo is not None else None
        bc = None
        if var:
            bc = db.scalar(select(ItemBarcode.barcode).where(ItemBarcode.item_id == it.id, ItemBarcode.variant_id == var.id).limit(1))
        bc = bc or db.scalar(select(ItemBarcode.barcode).where(ItemBarcode.item_id == it.id, ItemBarcode.variant_id.is_(None)).limit(1))
        brand = db.get(Brand, it.brand_id).name if it.brand_id and db.get(Brand, it.brand_id) else ""
        cat = db.get(Category, it.category_id).name if it.category_id and db.get(Category, it.category_id) else ""
        out.append({"item_id": str(it.id), "variant_id": str(var.id) if var else None, "quantity": int(r.get("quantity") or 1), "fields": {
            "description": it.description, "code": var.code if var else it.code, "price": money_it(price) if price is not None else "",
            "list_price": money_it(list_price) if list_price is not None else "", "barcode": bc or (var.code if var else it.code),
            "unit": it.unit or "", "brand": brand, "category": cat, "plu": it.plu or "",
            "variant": " ".join(x for x in ((var.color, var.size, var.format) if var else ()) if x), "date": today.strftime("%d/%m/%Y"),
        }})
    return out


def _dots(mm, dpi: int) -> int:
    return int((Decimal(str(mm)) * dpi / Decimal("25.4")).to_integral_value(ROUND_HALF_UP))


def _zpl_text(s: str) -> str:
    return (s or "").replace("^", " ").replace("~", " ").replace("\n", " ")


def _ean_ok(s: str) -> bool:
    if not s.isdigit() or len(s) not in (8, 13):
        return False
    digits = [int(c) for c in s]
    check = digits.pop()
    total = sum(d * (3 if i % 2 else 1) for i, d in enumerate(digits)) if len(s) == 13 else sum(d * (1 if i % 2 else 3) for i, d in enumerate(digits))
    return (10 - total % 10) % 10 == check


def element_value(el: dict, fields: dict) -> str:
    v = el.get("text", "") if el.get("field") == "custom" else fields.get(el.get("field", ""), "")
    return f"{el.get('prefix') or ''}{v}" if v else ""


def to_zpl(tpl: dict, labels: list[dict]) -> str:
    """Modello + dati → ZPL: un'etichetta per articolo, ripetuta con ^PQ per la quantità."""
    dpi = int(tpl.get("dpi") or 203)
    out = []
    for lab in labels:
        f = lab["fields"]
        z = ["^XA", "^CI28", f"^PW{_dots(tpl['width_mm'], dpi)}", f"^LL{_dots(tpl['height_mm'], dpi)}", "^LH0,0"]
        for el in tpl.get("elements", []):
            x, y = _dots(el.get("x", 0), dpi), _dots(el.get("y", 0), dpi)
            t = el.get("type")
            if t == "box":
                th = max(1, _dots(el.get("thickness", 0.3), dpi))
                z.append(f"^FO{x},{y}^GB{max(th, _dots(el.get('w', 10), dpi))},{max(th, _dots(el.get('h', 0.3), dpi))},{th}^FS")
                continue
            value = element_value(el, f)
            if not value:
                continue
            if t == "text":
                h = max(10, _dots(el.get("size", 3), dpi))
                w = _dots(el.get("w", Decimal(str(tpl["width_mm"])) - Decimal(str(el.get("x", 0)))), dpi)
                al = {"left": "L", "center": "C", "right": "R"}.get(el.get("align", "left"), "L")
                cmd = f"^A0N,{h},{h}^FB{w},{int(el.get('lines', 1))},0,{al},0^FD{_zpl_text(value)}^FS"
                z.append(f"^FO{x},{y}{cmd}")
                if el.get("bold"):  # il carattere 0 non ha il grassetto: si ripassa spostato di un punto
                    z.append(f"^FO{x + 2},{y}{cmd}")
            elif t == "barcode":
                h = max(20, _dots(el.get("h", 10), dpi))
                hr = "Y" if el.get("text", True) else "N"
                data = _zpl_text(value)
                if el.get("symbology", "auto") in ("auto", "ean13") and _ean_ok(data) and len(data) == 13:
                    z.append(f"^FO{x},{y}^BY{int(el.get('module', 2))}^BEN,{h},{hr},N^FD{data[:12]}^FS")
                else:
                    z.append(f"^FO{x},{y}^BY{int(el.get('module', 2))}^BCN,{h},{hr},N,N^FD{data}^FS")
            elif t == "qr":
                z.append(f"^FO{x},{y}^BQN,2,{max(1, min(10, int(el.get('size', 4))))}^FDQA,{_zpl_text(value)}^FS")
        z += [f"^PQ{max(1, int(lab.get('quantity') or 1))}", "^XZ"]
        out.append("".join(z))
    return "\n".join(out)
