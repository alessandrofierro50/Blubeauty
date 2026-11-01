"""Ricevute stampate dalla cassa (copia di cortesia, ricevuta non fiscale al posto dello scontrino, reso non fiscale):
impostazioni di logo, intestazione e piede (AppSetting «ricevute») e layout come il documento commerciale del
registratore. Il risultato è il formato neutro dell'agent: `print.text` sulla termica, `rt.nonfiscal` sul registratore,
e la stessa pagina 80 mm stampata dal computer.

Sul registratore l'intestazione e il logo li stampa lui (programmati dal tecnico): le nostre righe d'intestazione hanno
`rt_skip`, a meno che l'opzione `header_on_rt` chieda di stamparle comunque. Il logo va solo sulla termica (immagine
raster ESC/POS) e sulla stampa dal computer.
"""

import base64
import io
import os
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import AppSetting
from app.core import media

KEY = "ricevute"
DEFAULTS = {
    "logo": "azienda",       # azienda (logo di Dati azienda) | proprio (caricato qui) | nessuno
    "logo_file": None,       # logo proprio delle ricevute
    "logo_width_mm": 40,     # larghezza del logo sulla termica
    "header": [],            # righe d'intestazione; vuoto = dai dati dell'azienda
    "footer": ["Grazie e arrivederci"],
    "header_on_rt": False,   # stampare la nostra intestazione anche sul registratore (di solito la stampa lui)
    "show_vat": True,        # colonna IVA come sul documento commerciale
}
TZ = ZoneInfo("Europe/Rome")
# Righe della ricevuta d'esempio (anteprima e stampa di prova): descrizione, prezzo, quantità
SAMPLE = [("Piega", "22.00", "1"), ("Colore + piega", "65.00", "1"), ("Shampoo riparatore 250 ml", "12.50", "2")]
ELECTRONIC = ("carta", "bancomat", "satispay")
LABELS = {"contanti": "Pagamento contante", "carta": "Pagamento elettronico", "bancomat": "Pagamento elettronico",
          "satispay": "Pagamento elettronico", "buono": "Buono", "buono_regalo": "Pagato con buono regalo", "buono_pasto": "Buono pasto", "altro": "Altro pagamento"}


def settings(db: Session, tenant_id) -> dict:
    s = db.get(AppSetting, (tenant_id, KEY))
    return {**DEFAULTS, **((s.value if s else None) or {})}


def save_settings(db: Session, tenant_id, value: dict) -> dict:
    """Unico punto che scrive le impostazioni delle ricevute."""
    s = db.get(AppSetting, (tenant_id, KEY))
    clean = {k: value[k] for k in DEFAULTS if k in value}
    if "header" in clean:
        clean["header"] = [str(x)[:60] for x in (clean["header"] or [])][:8]
    if "footer" in clean:
        clean["footer"] = [str(x)[:60] for x in (clean["footer"] or [])][:6]
    if "logo_width_mm" in clean:
        clean["logo_width_mm"] = max(15, min(70, int(clean["logo_width_mm"] or 40)))
    if "logo" in clean and clean["logo"] not in ("azienda", "proprio", "nessuno"):
        clean["logo"] = "azienda"
    if s is None:
        s = AppSetting(tenant_id=tenant_id, key=KEY, value={})
        db.add(s)
    s.value = {**DEFAULTS, **(s.value or {}), **clean}
    db.flush()
    return {**DEFAULTS, **s.value}


def company(db: Session):
    from app.core.models import Company
    return db.scalar(select(Company).order_by(Company.name))


def default_header(co) -> list[str]:
    if co is None:
        return []
    rows = [co.name]
    if co.address:
        rows.append(co.address)
    city = " ".join(x for x in [co.zip_code, co.city, f"({co.province})" if co.province else None] if x)
    if city:
        rows.append(city)
    if co.vat_number:
        rows.append(f"P.IVA {co.vat_number}")
    if co.phone:
        rows.append(f"Tel. {co.phone}")
    return rows


def logo_name(db: Session, cfg: dict) -> str | None:
    if cfg.get("logo") == "proprio":
        return cfg.get("logo_file")
    if cfg.get("logo") == "azienda":
        co = company(db)
        return co.logo_file if co else None
    return None


def logo_raster(name: str, width_mm: int) -> dict | None:
    """Logo in bianco e nero per la termica (8 punti per mm, 203 dpi): bit per riga, compatibile con GS v 0."""
    from PIL import Image, ImageOps
    path = os.path.join(media.media_dir(), f"{name}.webp")
    try:
        img = Image.open(path)
        img.load()
    except OSError:
        return None
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(bg, img)
    img = img.convert("L")
    width = max(8, min(576, int(width_mm) * 8)) // 8 * 8
    height = max(1, round(img.height * width / img.width))
    img = img.resize((width, min(height, 400)))
    img = ImageOps.autocontrast(img).convert("1")  # diffusione dell'errore: sfumature in punti
    data = bytes(b ^ 0xFF for b in img.tobytes())  # in PIL 1 = bianco, nella stampante 1 = punto nero
    return {"type": "image", "raster": base64.b64encode(data).decode(), "width_bytes": width // 8, "height": img.height,
            "align": "center", "rt_skip": True}


def _eur(v) -> str:
    return f"{Decimal(str(v or 0)).quantize(Decimal('0.01'), ROUND_HALF_UP):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def header_lines(db: Session, cfg: dict, co=None, logo: bool = True) -> list[dict]:
    """Logo e intestazione, centrati come sul documento commerciale."""
    co = co if co is not None else company(db)
    out = []
    name = logo_name(db, cfg) if logo else None
    if name:
        r = logo_raster(name, cfg.get("logo_width_mm") or 40)
        if r:
            out.append({**r, "logo_url": media.urls(name)["url"]})
    skip = not cfg.get("header_on_rt")
    rows = cfg.get("header") or default_header(co)
    for i, t in enumerate(rows):
        out.append({"text": t, "align": "center", "bold": i == 0, "size": 2 if i == 0 and len(t) <= 24 else 1, "rt_skip": skip})
    return out


def document_receipt(db: Session, d, pays: list, register_name: str = "") -> dict:
    """Ricevuta di uno scontrino/reso della cassa con il layout del documento commerciale."""
    from app.documenti import service as docs
    cfg = settings(db, d.tenant_id)
    nonfiscal = (d.fiscal or {}).get("nonfiscal")
    rt = (d.fiscal or {}).get("rt") or {}
    L = header_lines(db, cfg)
    title = {"SCO": "RICEVUTA NON FISCALE" if nonfiscal else "COPIA DI CORTESIA",
             "RSO": "RESO NON FISCALE" if nonfiscal else "COPIA DEL RESO",
             "FTI": f"COPIA FATTURA N. {d.number}/{d.year}"}.get(d.doc_type, d.doc_type)
    L += [{"type": "feed"}, {"text": title, "align": "center", "bold": True}]
    if d.doc_type == "SCO" and not nonfiscal and rt.get("status") == "emesso":
        L.append({"text": f"del documento commerciale {rt.get('z')}-{rt.get('number')}", "align": "center"})
    L.append({"type": "feed"})
    vs = (d.fiscal or {}).get("voucher_sale")
    multiuso_sale = bool(vs and vs.get("mode") == "multiuso")  # IVA dovuta all'utilizzo del buono, non ora
    vat = bool(cfg.get("show_vat")) and not multiuso_sale
    col = lambda rate, price: (f"{rate}%".rjust(4) + "  " if vat else "") + price.rjust(9)  # noqa: E731
    L.append({"text": "DESCRIZIONE", "right": (" IVA  " if vat else "") + "Prezzo(€)"})
    sign = -1 if d.doc_type == "RSO" else 1
    for ln in sorted(d.lines, key=lambda x: x.line_no):
        amount = docs.gross_amount(ln) if d.prices_vat_included else Decimal(str(ln.line_total))
        rate = Decimal(str(ln.vat_rate or 0)).normalize()
        L.append({"text": ln.description, "right": col(f"{rate:f}", _eur(amount * sign))})
        qty = Decimal(str(ln.quantity))
        if qty != 1:
            L.append({"text": f"  {qty.normalize():f} x {_eur(ln.unit_price_gross)}"})
        if ln.discount1:
            L.append({"text": f"  sconto {Decimal(str(ln.discount1)).normalize():f}%"})
    L += [{"type": "line"},
          {"text": "TOTALE COMPLESSIVO", "right": _eur(Decimal(str(d.total)) * sign), "bold": True},
          *([] if multiuso_sale else [{"text": "di cui IVA", "right": _eur(Decimal(str(d.vat_total or 0)) * sign)}])]
    change = Decimal(str((d.fiscal or {}).get("change") or 0))
    for p in pays:
        got = p.tendered if p.tendered is not None else p.amount
        if not got:  # pagato tutto con buono o pacchetto: niente riga «0,00»
            continue
        L.append({"text": LABELS.get(p.method, p.method.replace("_", " ").capitalize()), "right": _eur(abs(Decimal(str(got))))})
    if change > 0:
        L.append({"text": "Resto", "right": _eur(change)})
    L.append({"text": "Importo pagato" if d.doc_type != "RSO" else "Importo rimborsato", "right": _eur(abs(Decimal(str(d.total))))})
    if vs:  # vendita di un buono regalo: codice, intestatario, scadenza
        from datetime import date as _date
        L += [{"type": "line"}, {"text": f"Buono regalo {vs['code']}", "bold": True}]
        if vs.get("beneficiary"):
            L.append({"text": f"Intestato a {vs['beneficiary']}"})
        if vs.get("expires_on"):
            L.append({"text": f"Valido fino al {_date.fromisoformat(vs['expires_on']):%d/%m/%Y}"})
        if multiuso_sale:
            L.append({"text": "Lo scontrino fiscale si emette quando il buono viene utilizzato."})
        L.append({"type": "barcode", "data": vs["code"].replace("-", ""), "label": vs["code"], "align": "center", "rt_skip": True})
    prepaid = (d.fiscal or {}).get("prepaid")
    if prepaid:  # buono regalo e pacchetti: credito residuo e sedute rimaste
        from app.prepagati.service import receipt_lines
        L += [{"type": "line"}] + receipt_lines(prepaid)
    L.append({"type": "line"})
    when = d.created_at.astimezone(TZ).strftime("%d-%m-%Y %H:%M") if d.created_at else d.doc_date.strftime("%d-%m-%Y")
    num = f"{'RNF' if nonfiscal else d.doc_type} N. {d.number:04d}" if isinstance(d.number, int) else ""
    L.append({"text": when, "right": num})
    if register_name:
        L.append({"text": register_name, "align": "left"})
    if nonfiscal and nonfiscal.get("reason"):
        L.append({"text": f"Motivo: {nonfiscal['reason']}"})
    if d.number and d.doc_type == "SCO":
        L.append({"type": "barcode", "data": f"S{d.year % 100:02d}{d.number:07d}", "align": "center", "rt_skip": True})
    L.append({"type": "feed"})
    for t in cfg.get("footer") or []:
        L.append({"text": t, "align": "center"})
    L.append({"type": "cut"})  # niente dicitura «non valido come documento commerciale» (scelta del titolare, 2026-11-01)
    return {"lines": L}


def raster_png(line: dict) -> bytes:
    """Anteprima del logo come uscirà sulla termica (per la pagina delle impostazioni)."""
    from PIL import Image
    w, h = line["width_bytes"] * 8, line["height"]
    data = bytes(b ^ 0xFF for b in base64.b64decode(line["raster"]))
    img = Image.frombytes("1", (w, h), data)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def sample_receipt(db: Session, tenant_id) -> dict:
    """Anteprima e stampa di prova: una ricevuta non fiscale d'esempio con le impostazioni attuali."""
    from datetime import date, datetime
    from types import SimpleNamespace as NS


    def line(no, desc, price, qty="1", rate="22", disc=None):
        return NS(line_no=no, description=desc, unit_price_gross=Decimal(price), quantity=Decimal(qty), vat_rate=Decimal(rate),
                  discount1=Decimal(disc) if disc else None, discount2=None, discount3=None, line_total=Decimal(price))
    lines = [line(i + 1, desc, price, qty=qty) for i, (desc, price, qty) in enumerate(SAMPLE)]
    total = sum((Decimal(p) * Decimal(q) for _, p, q in SAMPLE), Decimal(0))
    vat = (total - total / Decimal("1.22")).quantize(Decimal("0.01"), ROUND_HALF_UP)
    given = (total / 10).to_integral_value(rounding="ROUND_CEILING") * 10
    d = NS(tenant_id=tenant_id, fiscal={"nonfiscal": {"reason": "Esempio di stampa"}, "change": str(given - total)}, doc_type="SCO", number=12,
           year=date.today().year, lines=lines, prices_vat_included=True, total=total, vat_total=vat,
           created_at=datetime.now(TZ), doc_date=date.today())
    pays = [NS(method="contanti", amount=total, tendered=given)]
    return document_receipt(db, d, pays, "Cassa")


def for_screen(payload: dict) -> dict:
    """Per la stampa dal computer: il logo come indirizzo dell'immagine, senza i dati raster della termica."""
    return {"lines": [{k: v for k, v in x.items() if k != "raster"} for x in payload["lines"]]}
