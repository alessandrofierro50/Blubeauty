"""Analisi del pacchetto Pro che vanno oltre un semplice raggruppamento: ABC/Pareto, salute del magazzino
(fermi, rotazione, copertura, valore al costo medio/ultimo/FIFO), clienti inattivi e frequenza, garanzie."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Item, Party
from app.bi import engine
from app.bi.facts import CUBES
from app.core.models import Warehouse
from app.documenti.models import Document
from app.magazzino.models import Serial, StockBalance, StockMovement

OUT_REASONS = ("vendita", "scarico", "omaggio", "scarto")
CENT = Decimal("0.01")


def _q2(v) -> str:
    return str(Decimal(v).quantize(CENT, ROUND_HALF_UP))


# ====================================================================== ABC / Pareto


def abc(db: Session, what: str, measure: str, d1: date, d2: date, a: float = 80, b: float = 95) -> dict:
    """Classifica con quota cumulata: A fino ad a% del totale, B fino a b%, C il resto (Pareto)."""
    cube = CUBES["acquisti" if what == "fornitore" else "vendite"]
    dim = what
    allowed = {"vendite": ("fatturato", "margine", "quantita"), "acquisti": ("spesa", "quantita")}[cube.name]
    if measure not in allowed:
        measure = allowed[0]
    extra = [m for m in (("fatturato", "margine", "margine_pct", "quantita", "documenti") if cube.name == "vendite" else ("spesa", "quantita", "documenti"))
             if m != measure]
    res = engine.execute(cube, db, engine.Query([measure, *extra], [dim], d1, d2, sort=measure, desc=True, limit=5000), True)
    rows = [r for r in res["rows"] if r["dims"][dim]["key"] is not None and Decimal(str(r["values"][measure] or 0)) > 0]
    total = sum((Decimal(str(r["values"][measure])) for r in rows), Decimal(0))
    out, cum = [], Decimal(0)
    classes = {k: {"count": 0, "value": Decimal(0)} for k in "ABC"}
    for n, r in enumerate(rows, start=1):
        v = Decimal(str(r["values"][measure]))
        before = cum / total * 100 if total else Decimal(0)
        cum += v
        share = v / total * 100 if total else Decimal(0)
        cls = "A" if before < Decimal(str(a)) else "B" if before < Decimal(str(b)) else "C"
        classes[cls]["count"] += 1
        classes[cls]["value"] += v
        out.append({"rank": n, "key": r["dims"][dim]["key"], "label": r["dims"][dim]["label"], "value": _q2(v), "share": _q2(share),
                    "cumulative": _q2(cum / total * 100 if total else 0), "class": cls, "values": r["values"]})
    n_all = len(out) or 1
    summary = [{"class": k, "count": c["count"], "count_share": _q2(Decimal(c["count"]) * 100 / n_all), "value": _q2(c["value"]),
                "value_share": _q2(c["value"] * 100 / total if total else 0)} for k, c in classes.items()]
    return {"what": what, "measure": measure, "measure_label": cube.measures[measure].label, "period": {"from": d1.isoformat(), "to": d2.isoformat()},
            "total": _q2(total), "thresholds": [a, b], "rows": out, "summary": summary,
            "excluded": len(res["rows"]) - len(rows)}


# ====================================================================== salute del magazzino


def stock_health(db: Session, days: int = 90, warehouse_id=None) -> dict:
    """Per articolo: giacenza, valore (costo medio, ultimo, FIFO), scarichi nel periodo, rotazione annua, giorni di copertura, fermi."""
    today = date.today()
    start = datetime.combine(today - timedelta(days=days - 1), time.min, timezone.utc)
    year = datetime.combine(today - timedelta(days=364), time.min, timezone.utc)
    bq = select(StockBalance.item_id, func.sum(StockBalance.on_hand)).group_by(StockBalance.item_id)
    mq = select(StockMovement.item_id,
                func.coalesce(-func.sum(StockMovement.quantity).filter(StockMovement.reason.in_(OUT_REASONS), StockMovement.moved_at >= start), 0),
                func.coalesce(-func.sum(StockMovement.quantity).filter(StockMovement.reason.in_(OUT_REASONS), StockMovement.moved_at >= year), 0),
                func.max(case((StockMovement.reason.in_(OUT_REASONS), StockMovement.moved_at))),
                func.max(case((StockMovement.quantity > 0, StockMovement.moved_at)))).group_by(StockMovement.item_id)
    if warehouse_id:
        bq = bq.where(StockBalance.warehouse_id == warehouse_id)
        mq = mq.where(StockMovement.warehouse_id == warehouse_id)
    on_hand = {i: Decimal(q or 0) for i, q in db.execute(bq)}
    moves = {r[0]: r[1:] for r in db.execute(mq)}
    # FIFO: la merce in giacenza è quella entrata per ultima → si valorizza con i carichi più recenti
    loads = defaultdict(list)
    fq = select(StockMovement.item_id, StockMovement.quantity, StockMovement.unit_cost).where(
        StockMovement.quantity > 0, StockMovement.reason.in_(("acquisto", "carico")), StockMovement.item_id.in_([i for i, q in on_hand.items() if q > 0]))
    if warehouse_id:
        fq = fq.where(StockMovement.warehouse_id == warehouse_id)
    for item_id, qty, cost in db.execute(fq.order_by(StockMovement.item_id, StockMovement.moved_at.desc())):
        loads[item_id].append((Decimal(qty), Decimal(cost) if cost is not None else None))
    items = {it.id: it for it in db.scalars(select(Item).where(Item.stock_managed, Item.id.in_(set(on_hand) | set(moves))))}
    rows = []
    tot = defaultdict(Decimal)
    for item_id, it in items.items():
        q = on_hand.get(item_id, Decimal(0))
        out_p, out_y, last_out, last_in = moves.get(item_id, (0, 0, None, None))
        out_p, out_y = Decimal(out_p or 0), Decimal(out_y or 0)
        if q == 0 and out_p == 0:
            continue
        avg = Decimal(it.avg_cost or it.last_cost or 0)
        last = Decimal(it.last_cost or it.avg_cost or 0)
        fifo, left = Decimal(0), q
        for lq, lc in loads.get(item_id, []):
            if left <= 0:
                break
            take = min(lq, left)
            fifo += take * (lc if lc is not None else avg)
            left -= take
        if left > 0:
            fifo += left * avg
        daily = out_p / days if out_p > 0 else Decimal(0)
        coverage = (q / daily).quantize(Decimal(1)) if daily > 0 and q > 0 else None
        rotation = (out_y / q).quantize(Decimal("0.1")) if q > 0 and out_y > 0 else (Decimal(0) if q > 0 else None)
        idle = q > 0 and out_p == 0
        v_avg, v_last = q * avg, q * last
        rows.append({"item_id": str(item_id), "code": it.code, "description": it.description, "unit": it.unit, "on_hand": str(q.normalize()),
                     "value_avg": _q2(v_avg), "value_last": _q2(v_last), "value_fifo": _q2(fifo), "out_period": str(out_p.normalize()),
                     "out_year": str(out_y.normalize()), "rotation": str(rotation) if rotation is not None else None,
                     "coverage_days": int(coverage) if coverage is not None else None, "idle": idle,
                     "last_out": last_out.date().isoformat() if last_out else None, "last_in": last_in.date().isoformat() if last_in else None,
                     "idle_days": (today - last_out.date()).days if last_out else None, "negative": q < 0})
        if q > 0:
            tot["value_avg"] += v_avg
            tot["value_last"] += v_last
            tot["value_fifo"] += fifo
            if idle:
                tot["idle_value"] += v_avg
                tot["idle_count"] += 1
            if coverage is not None and coverage > 180:
                tot["overstock_count"] += 1
    rows.sort(key=lambda r: -Decimal(r["value_avg"]))
    wh = db.get(Warehouse, warehouse_id) if warehouse_id else None
    return {"days": days, "warehouse": wh.name if wh else None, "rows": rows,
            "summary": {"value_avg": _q2(tot["value_avg"]), "value_last": _q2(tot["value_last"]), "value_fifo": _q2(tot["value_fifo"]),
                        "idle_value": _q2(tot["idle_value"]), "idle_count": int(tot["idle_count"]), "overstock_count": int(tot["overstock_count"]),
                        "items": sum(1 for r in rows if Decimal(r["on_hand"]) > 0)}}


# ====================================================================== clienti


def customers(db: Session, inactive_days: int = 90) -> dict:
    """Ultimo acquisto, frequenza, scontrino/fattura media negli ultimi 12 mesi; inattivi e a rischio."""
    today = date.today()
    year_ago = today - timedelta(days=365)
    sign = case((Document.doc_type.in_(("NC", "RSO")), -1), else_=1)
    q = (select(Party.id, Party.name, Party.city, Party.email, Party.mobile,
                func.min(Document.doc_date), func.max(Document.doc_date),
                func.count(func.distinct(Document.id)).filter(Document.doc_type.in_(("FTI", "FTD", "SCO")), Document.doc_date >= year_ago),
                func.coalesce(func.sum(sign * Document.taxable_total).filter(Document.doc_date >= year_ago), 0),
                func.count(func.distinct(Document.doc_date)).filter(Document.doc_type.in_(("FTI", "FTD", "SCO"))))
         .join(Document, Document.party_id == Party.id)
         .where(Document.direction == "vendita", Document.doc_type.in_(("FTI", "FTD", "NC", "SCO", "RSO")),
                Document.status.in_(("confermato", "evaso")), Party.code != "BANCO")
         .group_by(Party.id, Party.name, Party.city, Party.email, Party.mobile))
    rows = []
    counts = defaultdict(int)
    for pid, name, city, email, mobile, first, last, docs12, rev12, days_with in db.execute(q):
        since = (today - last).days
        gap = ((last - first).days / (days_with - 1)) if days_with and days_with > 1 else None
        if since > inactive_days:
            st = "inattivo"
        elif gap and since > max(30, gap * 1.5):
            st = "a_rischio"
        else:
            st = "attivo"
        counts[st] += 1
        rev = Decimal(rev12)
        rows.append({"party_id": str(pid), "name": name, "city": city, "email": email, "mobile": mobile, "first": first.isoformat(),
                     "last": last.isoformat(), "days_since": since, "docs_12m": docs12, "revenue_12m": _q2(rev),
                     "avg_ticket": _q2(rev / docs12) if docs12 else None, "avg_gap_days": int(round(gap)) if gap else None, "status": st})
    rows.sort(key=lambda r: (-Decimal(r["revenue_12m"]), r["name"]))
    return {"inactive_days": inactive_days, "rows": rows, "summary": {k: counts[k] for k in ("attivo", "a_rischio", "inattivo")}}


# ====================================================================== garanzie


def warranties(db: Session, days: int = 60) -> dict:
    today = date.today()
    q = (select(Serial, Item, Party).join(Item, Item.id == Serial.item_id).outerjoin(Party, Party.id == Serial.customer_id)
         .where(Serial.warranty_until.is_not(None), Serial.status == "venduto"))
    rows, active, expiring = [], 0, 0
    for s, it, p in db.execute(q.order_by(Serial.warranty_until)):
        left = (s.warranty_until - today).days
        if left >= 0:
            active += 1
        if 0 <= left <= days:
            expiring += 1
        if left >= -30:
            rows.append({"serial": s.serial_number, "item_code": it.code, "description": it.description, "customer": p.name if p else None,
                         "customer_id": str(p.id) if p else None, "sale_date": s.sale_date.isoformat() if s.sale_date else None,
                         "warranty_until": s.warranty_until.isoformat(), "days_left": left})
    return {"days": days, "active": active, "expiring": expiring, "rows": rows}
