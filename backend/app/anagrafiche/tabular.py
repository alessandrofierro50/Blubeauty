"""Lettura e scrittura di fogli di calcolo (Excel .xlsx/.xls e CSV) per import ed export delle anagrafiche."""

import csv
import io
import re
import unicodedata
from datetime import date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse

MAX_ROWS = 20000

# Campi importabili: chiave -> (etichetta, sinonimi usati per riconoscere le intestazioni)
ITEM_FIELDS: dict[str, tuple[str, list[str]]] = {
    "code": ("Codice", ["codice", "cod", "codice articolo", "cod art", "sku", "articolo", "code"]),
    "description": ("Descrizione", ["descrizione", "desc", "descrizione articolo", "nome", "prodotto", "description"]),
    "long_description": ("Descrizione estesa", ["descrizione estesa", "descrizione lunga", "note articolo", "dettagli"]),
    "unit": ("Unità di misura", ["um", "u m", "unita di misura", "unita", "unit"]),
    "category": ("Categoria", ["categoria", "categ", "reparto", "gruppo", "category"]),
    "subcategory": ("Sottocategoria", ["sottocategoria", "sotto categoria", "sottogruppo"]),
    "brand": ("Marca", ["marca", "marchio", "brand", "produttore"]),
    "vat": ("Aliquota IVA", ["iva", "aliquota", "aliquota iva", "cod iva", "vat"]),
    "price": ("Prezzo di vendita", ["prezzo", "prezzo vendita", "prezzo al pubblico", "listino", "pvp", "prezzo ivato", "price"]),
    "last_cost": ("Costo d'acquisto", ["costo", "costo acquisto", "prezzo acquisto", "ultimo costo", "costo ultimo", "cost"]),
    "barcode": ("Codice a barre", ["barcode", "ean", "codice a barre", "ean13", "bar code"]),
    "supplier": ("Fornitore", ["fornitore", "supplier"]),
    "supplier_code": ("Codice fornitore", ["codice fornitore", "cod fornitore", "cod forn", "riferimento fornitore"]),
    "min_stock": ("Scorta minima", ["scorta minima", "scorta min", "minimo", "sottoscorta"]),
    "location": ("Ubicazione", ["ubicazione", "scaffale", "posizione", "location"]),
    "family": ("Famiglia", ["famiglia"]),
    "season": ("Stagione", ["stagione", "collezione"]),
    "weight_net": ("Peso netto", ["peso", "peso netto", "kg"]),
    "lot_managed": ("Gestione lotti (sì/no)", ["lotti", "gestione lotti", "lotto"]),
    "serial_managed": ("Gestione matricole (sì/no)", ["matricole", "gestione matricole", "matricola", "seriale"]),
    "warranty_months": ("Garanzia mesi", ["garanzia", "mesi garanzia", "garanzia mesi"]),
}

PARTY_FIELDS: dict[str, tuple[str, list[str]]] = {
    "code": ("Codice", ["codice", "cod", "codice cliente", "codice fornitore"]),
    "name": ("Ragione sociale / Nome", ["ragione sociale", "denominazione", "nome", "cliente", "fornitore", "nominativo"]),
    "person_type": ("Tipo (azienda/privato/pa)", ["tipo", "tipo soggetto"]),
    "vat_number": ("Partita IVA", ["partita iva", "p iva", "piva", "p.iva", "vat"]),
    "tax_code": ("Codice fiscale", ["codice fiscale", "cf", "c f", "cod fiscale"]),
    "sdi_code": ("Codice SDI", ["sdi", "codice sdi", "codice destinatario", "cod destinatario"]),
    "pec": ("PEC", ["pec", "posta certificata"]),
    "email": ("Email", ["email", "e mail", "mail"]),
    "phone": ("Telefono", ["telefono", "tel"]),
    "mobile": ("Cellulare", ["cellulare", "cell", "mobile"]),
    "address": ("Indirizzo", ["indirizzo", "via", "sede"]),
    "zip_code": ("CAP", ["cap"]),
    "city": ("Città", ["citta", "comune", "localita"]),
    "province": ("Provincia", ["provincia", "prov", "pr"]),
    "country": ("Nazione", ["nazione", "paese", "stato"]),
    "iban": ("IBAN", ["iban"]),
    "is_customer": ("È cliente (sì/no)", ["cliente si no", "e cliente"]),
    "is_supplier": ("È fornitore (sì/no)", ["fornitore si no", "e fornitore"]),
}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def suggest_mapping(headers: list[str], fields: dict[str, tuple[str, list[str]]]) -> dict[str, str | None]:
    """Per ogni colonna propone il campo corrispondente (prima corrispondenza esatta, poi parziale)."""
    used: set[str] = set()
    mapping: dict[str, str | None] = {}
    norm_headers = [_norm(h) for h in headers]
    for exact in (True, False):
        for idx, h in enumerate(norm_headers):
            if str(idx) in mapping or not h:
                continue
            for key, (label, syn) in fields.items():
                if key in used:
                    continue
                names = [_norm(key), _norm(label), *[_norm(s) for s in syn]]
                if (exact and h in names) or (not exact and any(n and (n == h or (len(n) > 3 and n in h)) for n in names)):
                    mapping[str(idx)] = key
                    used.add(key)
                    break
    return {str(i): mapping.get(str(i)) for i in range(len(headers))}


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


def read_table(filename: str, data: bytes) -> tuple[list[str], list[list[str]]]:
    """Restituisce intestazioni e righe come testo. La prima riga non vuota è l'intestazione."""
    name = (filename or "").lower()
    rows: list[list[str]] = []
    try:
        if name.endswith((".xlsx", ".xlsm")):
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            ws = wb.worksheets[0]
            for r in ws.iter_rows(values_only=True):
                rows.append([_cell(v) for v in r])
                if len(rows) > MAX_ROWS + 1:
                    break
        elif name.endswith(".xls"):
            import xlrd

            ws = xlrd.open_workbook(file_contents=data).sheet_by_index(0)
            rows = [[_cell(v) for v in ws.row_values(i)] for i in range(min(ws.nrows, MAX_ROWS + 1))]
        else:
            text = None
            for enc in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    text = data.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            first = text.splitlines()[0] if text and text.strip() else ""
            try:
                dialect = csv.Sniffer().sniff(first, delimiters=";,\t|")
            except csv.Error:
                dialect = csv.excel
            rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text or ""), dialect)][: MAX_ROWS + 1]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "File non leggibile: usa Excel (.xlsx, .xls) o CSV") from None
    rows = [r for r in rows if any(c for c in r)]
    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Il file è vuoto")
    headers = rows[0]
    width = max(len(r) for r in rows)
    headers = [h or f"Colonna {i + 1}" for i, h in enumerate(headers + [""] * (width - len(headers)))]
    body = [r + [""] * (width - len(r)) for r in rows[1:]]
    return headers, body


def apply_mapping(headers: list[str], rows: list[list[str]], mapping: dict[str, str | None]) -> list[dict]:
    cols = {int(i): f for i, f in mapping.items() if f}
    return [{f: (r[i] if i < len(r) else "") for i, f in cols.items()} for r in rows]


def xlsx_response(title: str, header: list[str], rows: list[list], filename: str, money_cols: set[int] = frozenset()) -> StreamingResponse:
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="2340A8")
        c.alignment = Alignment(vertical="center")
    for r in rows:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in r])
    for idx in money_cols:
        for cell in ws.iter_cols(min_col=idx + 1, max_col=idx + 1, min_row=2):
            for c in cell:
                c.number_format = "#,##0.00"
    for i, col in enumerate(ws.columns, start=1):
        width = max((len(str(c.value)) if c.value is not None else 0) for c in col)
        ws.column_dimensions[get_column_letter(i)].width = min(max(10, width + 2), 60)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})
