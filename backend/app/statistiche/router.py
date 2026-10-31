"""Statistiche di base (modulo "statistiche_base"): /api/statistiche/...

Fatturato = fatture immediate e differite meno note di credito (imponibile), per data documento.
Le righe della fattura differita contano qui (è lì che la vendita viene fatturata); i DDT non ancora fatturati
sono mostrati a parte."""

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Category, Item, Party
from app.core.deps import TenantContext, require_module
from app.core.models import Warehouse
from app.documenti.models import Document, DocumentLine
from app.magazzino.models import Lot, StockBalance
from app.scadenzario import liquidity

router = APIRouter(prefix="/api/statistiche", tags=["statistiche"])
base = require_module("statistiche_base")
INVOICES = ("FTI", "FTD", "NC")
MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def sales_reader(ctx: TenantContext = Depends(base)) -> TenantContext:
    if ctx.user.role in ("cassa", "magazzino", "agente"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può vedere le statistiche di vendita")
    return ctx


def stock_reader(ctx: TenantContext = Depends(base)) -> TenantContext:
    if ctx.user.role in ("cassa", "agente"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può vedere le statistiche di magazzino")
    return ctx


def s(v) -> str:
    return str(Decimal(v or 0).quantize(Decimal("0.01")))


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    today = date.today()
    a = date_from or today.replace(month=1, day=1)
    b = date_to or today
    if b < a:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Il periodo finisce prima di iniziare")
    if (b - a).days > 3700:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Periodo troppo lungo (massimo 10 anni)")
    return a, b


def _sign():
    return case((Document.doc_type == "NC", -1), else_=1)


def _invoice_filter(stmt, a: date, b: date):
    return stmt.where(Document.direction == "vendita", Document.doc_type.in_(INVOICES), Document.status.in_(("confermato", "evaso")),
                      Document.doc_date >= a, Document.doc_date <= b)


def _totals(db: Session, a: date, b: date) -> dict:
    row = db.execute(_invoice_filter(select(
        func.coalesce(func.sum(Document.taxable_total * _sign()), 0), func.coalesce(func.sum(Document.vat_total * _sign()), 0),
        func.count().filter(Document.doc_type != "NC"), func.count().filter(Document.doc_type == "NC"),
        func.count(func.distinct(Document.party_id))), a, b)).first()
    revenue, vat, n_inv, n_nc, customers = row
    return {"revenue": s(revenue), "vat": s(vat), "invoices": n_inv, "credit_notes": n_nc, "customers": customers,
            "avg_invoice": s(Decimal(revenue) / n_inv) if n_inv else "0.00"}


def sales_data(db: Session, a: date, b: date, limit: int = 20) -> dict:
    totals = _totals(db, a, b)
    prev = _totals(db, a - relativedelta(years=1), b - relativedelta(years=1))
    # per mese, con lo stesso mese dell'anno prima
    month = func.date_trunc("month", Document.doc_date)
    by_month = {r[0].date(): Decimal(r[1]) for r in db.execute(_invoice_filter(
        select(month, func.sum(Document.taxable_total * _sign())), a, b).group_by(month))}
    pa, pb = a - relativedelta(years=1), b - relativedelta(years=1)
    prev_month = {r[0].date(): Decimal(r[1]) for r in db.execute(_invoice_filter(
        select(month, func.sum(Document.taxable_total * _sign())), pa, pb).group_by(month))}
    months = []
    cur = a.replace(day=1)
    while cur <= b:
        months.append({"month": f"{MONTHS[cur.month - 1]} {str(cur.year)[2:]}", "start": cur.isoformat(),
                       "revenue": s(by_month.get(cur, 0)), "previous": s(prev_month.get(cur - relativedelta(years=1), 0))})
        cur += relativedelta(months=1)
    # clienti
    cust = db.execute(_invoice_filter(select(Document.party_id, func.sum(Document.taxable_total * _sign()), func.count()), a, b)
                      .group_by(Document.party_id).order_by(func.sum(Document.taxable_total * _sign()).desc()).limit(limit)).all()
    names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_([c[0] for c in cust])))} if cust else {}
    total = Decimal(totals["revenue"]) or Decimal(1)
    customers = [{"party_id": str(pid), "name": names.get(pid), "revenue": s(rev), "documents": n, "share": s(Decimal(rev) / total * 100)}
                 for pid, rev, n in cust]
    # articoli e categorie (righe delle fatture)
    sign = _sign()
    line_rev = func.sum(DocumentLine.line_total * sign)
    line_qty = func.sum(DocumentLine.quantity * sign)
    lines = _invoice_filter(select(DocumentLine.item_id, line_rev, line_qty, func.count(func.distinct(Document.id)))
                            .join(Document, Document.id == DocumentLine.document_id), a, b).where(DocumentLine.line_total != 0)
    item_rows = db.execute(lines.group_by(DocumentLine.item_id).order_by(line_rev.desc())).all()
    items_by_id = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_([r[0] for r in item_rows if r[0]])))} if item_rows else {}
    items = []
    for item_id, rev, qty, n in item_rows[:limit]:
        it = items_by_id.get(item_id)
        items.append({"item_id": str(item_id) if item_id else None, "code": it.code if it else "",
                      "description": it.description if it else "Righe libere (servizi, spese)", "unit": it.unit if it else None,
                      "quantity": s(qty) if it else None, "revenue": s(rev), "documents": n, "share": s(Decimal(rev) / total * 100)})
    cats = {c.id: c for c in db.scalars(select(Category))}

    def root_name(cid):
        seen = set()
        while cid in cats and cats[cid].parent_id and cid not in seen:
            seen.add(cid)
            cid = cats[cid].parent_id
        return cats[cid].name if cid in cats else "Senza categoria"

    by_cat: dict = {}
    for item_id, rev, _qty, _n in item_rows:
        it = items_by_id.get(item_id)
        key = root_name(it.category_id) if it and it.category_id else ("Senza categoria" if it else "Righe libere")
        by_cat[key] = by_cat.get(key, Decimal(0)) + Decimal(rev)
    categories = [{"name": k, "revenue": s(v), "share": s(v / total * 100)} for k, v in sorted(by_cat.items(), key=lambda x: -x[1])]
    # DDT consegnati e non ancora fatturati
    ddt = db.execute(select(func.coalesce(func.sum(Document.taxable_total), 0), func.count()).where(
        Document.direction == "vendita", Document.doc_type == "DDT", Document.status == "confermato")).first()
    # acquisti nel periodo (imponibile fatture fornitore − note di credito)
    purchases = db.scalar(select(func.coalesce(func.sum(Document.taxable_total * case((Document.doc_type == "NCF", -1), else_=1)), 0)).where(
        Document.direction == "acquisto", Document.doc_type.in_(("FTF", "NCF")), Document.status.in_(("confermato", "evaso")),
        Document.doc_date >= a, Document.doc_date <= b))
    return {"from": a.isoformat(), "to": b.isoformat(), "totals": totals, "previous": prev,
            "growth": s((Decimal(totals["revenue"]) / Decimal(prev["revenue"]) - 1) * 100) if Decimal(prev["revenue"]) else None,
            "months": months, "customers": customers, "items": items, "categories": categories,
            "ddt_to_invoice": {"amount": s(ddt[0]), "count": ddt[1]}, "purchases": s(purchases)}


@router.get("/vendite")
def sales(date_from: date | None = None, date_to: date | None = None, limit: int = Query(20, ge=5, le=100),
          ctx: TenantContext = Depends(sales_reader)):
    a, b = _period(date_from, date_to)
    return sales_data(ctx.db, a, b, limit)


def stock_data(db: Session, warehouse_id: uuid.UUID | None = None, days: int = 60) -> dict:
    cost = func.coalesce(Item.avg_cost, Item.last_cost, 0)
    q = (select(StockBalance.warehouse_id, Item.category_id, func.sum(StockBalance.on_hand * cost), func.sum(StockBalance.on_hand))
         .join(Item, Item.id == StockBalance.item_id).where(StockBalance.on_hand != 0))
    if warehouse_id:
        q = q.where(StockBalance.warehouse_id == warehouse_id)
    rows = db.execute(q.group_by(StockBalance.warehouse_id, Item.category_id)).all()
    whs = {w.id: w.name for w in db.scalars(select(Warehouse))}
    cats = {c.id: c for c in db.scalars(select(Category))}

    def root(cid):
        while cid in cats and cats[cid].parent_id:
            cid = cats[cid].parent_id
        return cats[cid].name if cid in cats else "Senza categoria"

    by_wh: dict = {}
    by_cat: dict = {}
    total = Decimal(0)
    for wid, cid, value, _qty in rows:
        v = Decimal(value or 0)
        total += v
        by_wh[whs.get(wid, "?")] = by_wh.get(whs.get(wid, "?"), Decimal(0)) + v
        by_cat[root(cid)] = by_cat.get(root(cid), Decimal(0)) + v
    # articoli sotto scorta / a giacenza negativa
    tq = (select(Item.id, Item.code, Item.description, Item.unit, Item.min_stock, func.coalesce(func.sum(StockBalance.on_hand), 0))
          .outerjoin(StockBalance, StockBalance.item_id == Item.id).where(Item.active, Item.stock_managed, Item.is_kit.is_(False))
          .group_by(Item.id))
    under, negative = [], []
    for iid, code, desc, unit, min_stock, oh in db.execute(tq):
        if Decimal(oh) < 0:
            negative.append({"item_id": str(iid), "code": code, "description": desc, "unit": unit, "on_hand": s(oh)})
        elif min_stock is not None and Decimal(oh) < Decimal(min_stock):
            under.append({"item_id": str(iid), "code": code, "description": desc, "unit": unit, "on_hand": s(oh), "min_stock": s(min_stock)})
    # lotti in scadenza (con giacenza)
    today = date.today()
    lq = (select(Lot.id, Lot.lot_number, Lot.expiry_date, Item.id, Item.code, Item.description, Item.unit, func.sum(StockBalance.on_hand))
          .join(StockBalance, StockBalance.lot_id == Lot.id).join(Item, Item.id == Lot.item_id)
          .where(Lot.expiry_date.is_not(None), Lot.expiry_date <= today + timedelta(days=days), StockBalance.on_hand > 0))
    if warehouse_id:
        lq = lq.where(StockBalance.warehouse_id == warehouse_id)
    lots = [{"lot_number": n, "expiry_date": e.isoformat(), "days": (e - today).days, "item_id": str(iid), "code": code,
             "description": desc, "unit": unit, "on_hand": s(q)}
            for _lid, n, e, iid, code, desc, unit, q in db.execute(lq.group_by(Lot.id, Item.id).order_by(Lot.expiry_date))]
    return {"value": s(total), "by_warehouse": [{"name": k, "value": s(v)} for k, v in sorted(by_wh.items(), key=lambda x: -x[1])],
            "by_category": [{"name": k, "value": s(v), "share": s(v / total * 100) if total else "0.00"} for k, v in sorted(by_cat.items(), key=lambda x: -x[1])],
            "under_min": sorted(under, key=lambda r: r["code"])[:200], "negative": negative[:200], "expiring_lots": lots[:200],
            "expired_count": sum(1 for x in lots if x["days"] < 0)}


@router.get("/magazzino")
def stock(warehouse_id: uuid.UUID | None = None, days: int = Query(60, ge=1, le=365), ctx: TenantContext = Depends(stock_reader)):
    return stock_data(ctx.db, warehouse_id, days)


@router.get("/riepilogo")
def summary(ctx: TenantContext = Depends(sales_reader)):
    """Numeri per la home: mese e anno in corso, crediti e debiti aperti."""
    today = date.today()
    month = _totals(ctx.db, today.replace(day=1), today)
    year = _totals(ctx.db, today.replace(month=1, day=1), today)
    prev_year = _totals(ctx.db, today.replace(month=1, day=1) - relativedelta(years=1), today - relativedelta(years=1))
    snap = liquidity.snapshot(ctx.db, today, weeks=1, months=1)
    return {"month": month, "year": year, "previous_year": prev_year, "liquidity": snap["liquidity"],
            "receivables": snap["receivables"], "payables": snap["payables"]}


@router.get("/excel")
def export(date_from: date | None = None, date_to: date | None = None, ctx: TenantContext = Depends(sales_reader)):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    a, b = _period(date_from, date_to)
    d = sales_data(ctx.db, a, b, limit=100)
    m = stock_data(ctx.db)
    wb = Workbook()
    head, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2340A8")

    def sheet(title, header, rows, widths):
        ws = wb.create_sheet(title)
        ws.append(header)
        for c in ws[1]:
            c.font, c.fill = head, fill
        for r in rows:
            ws.append([float(v) if isinstance(v, str) and _num(v) else v for v in r])
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w

    wb.remove(wb.active)
    t = d["totals"]
    sheet("Riepilogo", ["Voce", "Valore"], [
        ["Periodo", f"{a.strftime('%d/%m/%Y')} – {b.strftime('%d/%m/%Y')}"], ["Fatturato (imponibile)", t["revenue"]],
        ["Stesso periodo anno precedente", d["previous"]["revenue"]], ["Fatture", t["invoices"]], ["Note di credito", t["credit_notes"]],
        ["Clienti fatturati", t["customers"]], ["Fattura media", t["avg_invoice"]], ["DDT da fatturare", d["ddt_to_invoice"]["amount"]],
        ["Acquisti (imponibile)", d["purchases"]], ["Valore di magazzino", m["value"]]], [34, 22])
    sheet("Per mese", ["Mese", "Fatturato", "Anno precedente"], [[x["month"], x["revenue"], x["previous"]] for x in d["months"]], [14, 16, 16])
    sheet("Clienti", ["Cliente", "Fatturato", "Documenti", "% sul totale"], [[x["name"], x["revenue"], x["documents"], x["share"]] for x in d["customers"]], [40, 16, 12, 12])
    sheet("Articoli", ["Codice", "Descrizione", "Quantità", "Fatturato", "% sul totale"],
          [[x["code"], x["description"], x["quantity"], x["revenue"], x["share"]] for x in d["items"]], [14, 44, 12, 16, 12])
    sheet("Categorie", ["Categoria", "Fatturato", "% sul totale"], [[x["name"], x["revenue"], x["share"]] for x in d["categories"]], [30, 16, 12])
    sheet("Magazzino", ["Categoria", "Valore", "%"], [[x["name"], x["value"], x["share"]] for x in m["by_category"]], [30, 16, 10])
    sheet("Lotti in scadenza", ["Articolo", "Descrizione", "Lotto", "Scadenza", "Giacenza"],
          [[x["code"], x["description"], x["lot_number"], x["expiry_date"], x["on_hand"]] for x in m["expiring_lots"]], [14, 40, 16, 12, 12])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="statistiche-{a.isoformat()}-{b.isoformat()}.xlsx"'})


def _num(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False
