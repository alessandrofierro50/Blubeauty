"""Motore di Business Intelligence: un cubo per ogni fatto (vendite, acquisti, scadenze, preventivi e ordini, magazzino).

Ogni cubo è una vista `bi_*` (security_invoker: passa dalla RLS) con dimensioni (chiave + etichetta, gerarchie per il
drill-down) e misure (aggregati SQL o rapporti calcolati sui totali). Le interrogazioni accettano solo nomi presenti
nel modello: nessun testo libero arriva all'SQL. Lo stesso motore serve dashboard, report builder, export ed email."""

import io
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from dateutil.relativedelta import relativedelta
from sqlalchemy import Integer, String, Table, cast, func, select
from sqlalchemy.orm import Session

MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
DAYS = ["", "lun", "mar", "mer", "gio", "ven", "sab", "dom"]


@dataclass
class Dimension:
    name: str
    label: str
    group: str
    key: Callable  # (colonna data, eventualmente spostata per il confronto) -> espressione chiave
    caption: Callable | None = None  # etichetta leggibile (se diversa dalla chiave)
    time: bool = False
    child: str | None = None  # livello successivo per il drill-down
    empty: str = "(non indicato)"
    pro: bool = False
    kind: str = "str"  # str | uuid | int | date: tipo dei valori nei filtri
    labels: dict | None = None  # etichette fisse per chiave (es. tipi di documento)


@dataclass
class Measure:
    name: str
    label: str
    fmt: str  # euro | numero | intero | percento | giorni
    expr: Callable | None = None  # aggregato SQL
    derived: Callable | None = None  # funzione sui valori già aggregati
    needs: list[str] = field(default_factory=list)
    pro: bool = False
    hint: str = ""


@dataclass
class Cube:
    name: str
    label: str
    description: str
    table: Table
    date_col: str
    dimensions: dict[str, Dimension]
    measures: dict[str, Measure]
    hierarchies: dict[str, list[str]]
    default_measure: str
    date_label: str = "Data"
    detail_cols: list[tuple[str, str, str]] = field(default_factory=list)  # (nome, colonna, formato)
    detail_label: Callable | None = None  # riga -> "Fattura 12/2026"
    pro: bool = False  # tutto il cubo solo nel pacchetto Pro

    @property
    def dd(self):
        return self.table.c[self.date_col]


def time_dimensions(group: str = "Tempo") -> list[Dimension]:
    return [
        Dimension("anno", "Anno", group, lambda dd: cast(func.extract("year", dd), Integer), time=True, child="trimestre", kind="int"),
        Dimension("trimestre", "Trimestre", group, lambda dd: func.to_char(dd, 'YYYY-"T"Q'), time=True, child="mese"),
        Dimension("mese", "Mese", group, lambda dd: func.to_char(dd, "YYYY-MM"), time=True, child="giorno"),
        Dimension("settimana", "Settimana", group, lambda dd: func.to_char(dd, 'IYYY-"S"IW'), time=True, child="giorno"),
        Dimension("giorno", "Giorno", group, lambda dd: dd, time=True, kind="date"),
        Dimension("giorno_settimana", "Giorno della settimana", group, lambda dd: cast(func.extract("isodow", dd), Integer), time=True, kind="int"),
    ]


def div(a, b):
    if a is None or not b:
        return None
    return Decimal(a) / Decimal(b)


class QueryError(ValueError):
    pass


@dataclass
class Query:
    measures: list[str]
    dimensions: list[str]
    date_from: date
    date_to: date
    filters: dict[str, list] = field(default_factory=dict)
    compare: str | None = None  # anno_precedente | periodo_precedente
    sort: str | None = None
    desc: bool = True
    limit: int = 100


def model(cube: Cube, pro: bool) -> dict:
    return {
        "name": cube.name, "label": cube.label, "description": cube.description, "date_label": cube.date_label,
        "dimensions": [{"name": d.name, "label": d.label, "group": d.group, "time": d.time, "child": d.child, "pro": d.pro,
                        "available": pro or not d.pro} for d in cube.dimensions.values()],
        "measures": [{"name": m.name, "label": m.label, "format": m.fmt, "hint": m.hint, "pro": m.pro, "available": pro or not m.pro,
                      "derived": m.derived is not None}
                     for m in cube.measures.values()],
        "hierarchies": cube.hierarchies, "default_measure": cube.default_measure,
        "limits": {"max_dimensions": 4 if pro else 2},
    }


def compare_shift(q: Query):
    if q.compare == "anno_precedente":
        shift = relativedelta(years=1)
        return q.date_from - shift, q.date_to - shift, shift
    if q.compare == "periodo_precedente":
        days = (q.date_to - q.date_from).days + 1
        shift = timedelta(days=days)
        return q.date_from - shift, q.date_to - shift, shift
    return None


def validate(cube: Cube, q: Query, pro: bool) -> None:
    if cube.pro and not pro:
        raise QueryError(f"L'analisi «{cube.label}» è nelle statistiche avanzate (pacchetto Pro)")
    if not q.measures:
        raise QueryError("Scegli almeno una misura")
    for m in q.measures:
        if m not in cube.measures:
            raise QueryError(f"Misura sconosciuta: {m}")
        if cube.measures[m].pro and not pro:
            raise QueryError(f"«{cube.measures[m].label}» è nelle statistiche avanzate (pacchetto Pro)")
    max_dims = 4 if pro else 2
    if len(q.dimensions) > max_dims:
        raise QueryError(f"Al massimo {max_dims} dimensioni insieme" + ("" if pro else " (di più nel pacchetto Pro)"))
    if len(set(q.dimensions)) != len(q.dimensions):
        raise QueryError("Dimensione ripetuta")
    for d in [*q.dimensions, *q.filters]:
        if d not in cube.dimensions:
            raise QueryError(f"Dimensione sconosciuta: {d}")
        if cube.dimensions[d].pro and not pro:
            raise QueryError(f"«{cube.dimensions[d].label}» è nelle statistiche avanzate (pacchetto Pro)")
    if q.date_to < q.date_from:
        raise QueryError("Il periodo finisce prima di iniziare")
    if (q.date_to - q.date_from).days > 3700:
        raise QueryError("Periodo troppo lungo (massimo 10 anni)")
    if q.compare not in (None, "anno_precedente", "periodo_precedente"):
        raise QueryError("Confronto non valido")
    if q.sort and q.sort not in q.measures and q.sort not in q.dimensions:
        raise QueryError("Ordinamento non valido")
    q.limit = max(1, min(int(q.limit or 100), 5000))


def _needed(cube: Cube, measures: list[str]) -> list[str]:
    out: list[str] = []
    for m in measures:
        for n in (cube.measures[m].needs or [m]):
            if n not in out:
                out.append(n)
    return out


def filter_cond(cube: Cube, name: str, values: list):
    """Condizione SQL per un filtro: valori tipizzati (interi, UUID, date) e «non indicato» (None)."""
    d = cube.dimensions[name]
    expr = d.key(cube.dd)
    non_null = [v for v in values if v is not None and v != ""]
    try:
        if d.kind == "int":
            non_null = [int(v) for v in non_null]
        elif d.kind == "uuid":
            non_null = [_uuid.UUID(str(v)) for v in non_null]
        elif d.kind == "date":
            non_null = [date.fromisoformat(str(v)[:10]) for v in non_null]
        else:
            non_null = [str(v) for v in non_null]
    except (ValueError, TypeError):
        raise QueryError(f"Valore non valido per il filtro «{d.label}»") from None
    conds = []
    if non_null:
        conds.append(expr.in_(non_null))
    if len(non_null) < len(values):
        conds.append(expr.is_(None))
    return conds[0] if len(conds) == 1 else (conds[0] | conds[1])


def _run(cube: Cube, db: Session, q: Query, date_from: date, date_to: date, shift=None) -> dict[tuple, dict]:
    """Aggregazione; con `shift` le date vengono spostate in avanti così le chiavi temporali si allineano al periodo attuale."""
    real = cube.dd
    dd = real if shift is None else (real + (func.make_interval(0, 0, 0, shift.days) if isinstance(shift, timedelta) else func.make_interval(shift.years)))
    base = _needed(cube, q.measures)
    cols, keys = [], []
    for name in q.dimensions:
        d = cube.dimensions[name]
        k = d.key(dd).label(f"k_{name}")
        cols.append(k)
        keys.append(k)
        if d.caption:
            cols.append(func.max(d.caption(dd)).label(f"c_{name}"))
    for m in base:
        cols.append(cube.measures[m].expr().label(f"m_{m}"))
    stmt = select(*cols).select_from(cube.table).where(real >= date_from, real <= date_to)
    for name, values in q.filters.items():
        if values:
            stmt = stmt.where(filter_cond(cube, name, values))  # i filtri si applicano sulle date reali
    if keys:
        stmt = stmt.group_by(*keys)
    out = {}
    for row in db.execute(stmt).mappings():
        key = tuple(row[f"k_{n}"] for n in q.dimensions)
        vals = {m: (Decimal(row[f"m_{m}"]) if row[f"m_{m}"] is not None else None) for m in base}
        out[key] = {"values": vals, "captions": {n: row.get(f"c_{n}") for n in q.dimensions}}
    return out


def _finish(cube: Cube, vals: dict, measures: list[str]) -> dict:
    return {m: (cube.measures[m].derived(vals) if cube.measures[m].derived else vals.get(m)) for m in measures}


def fmt(v, kind: str):
    if v is None:
        return None
    if kind == "intero":
        return int(v)
    q = Decimal("0.01") if kind in ("euro", "percento") else Decimal("0.1") if kind == "giorni" else Decimal("0.001")
    return str(Decimal(v).quantize(q, ROUND_HALF_UP))


def label(cube: Cube, name: str, key, caption) -> str:
    d = cube.dimensions[name]
    if key is None:
        return d.empty
    if d.labels and str(key) in d.labels:
        return d.labels[str(key)]
    if name == "mese":
        y, m = str(key).split("-")
        return f"{MONTHS[int(m) - 1]} {y}"
    if name == "trimestre":
        y, t = str(key).split("-")
        return f"{t[1]}° trim. {y}"
    if name == "settimana":
        y, w = str(key).split("-")
        return f"sett. {w[1:]} {y}"
    if name == "giorno":
        return key.strftime("%d/%m/%Y") if hasattr(key, "strftime") else str(key)
    if name == "giorno_settimana":
        return DAYS[int(key)]
    if name == "fascia_oraria":
        return f"{int(key):02d}–{(int(key) + 1) % 24:02d}"
    return str(caption) if caption else str(key)


def _key_out(v):
    if v is None:
        return None
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v if isinstance(v, (int, str)) else str(v)


def delta(cur, prev):
    if cur is None or prev is None or Decimal(prev) == 0:
        return None
    return str(((Decimal(cur) - Decimal(prev)) / abs(Decimal(prev)) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP))


def execute(cube: Cube, db: Session, q: Query, pro: bool) -> dict:
    validate(cube, q, pro)
    M = cube.measures
    cur = _run(cube, db, q, q.date_from, q.date_to)
    cmp_range = compare_shift(q)
    prev = _run(cube, db, q, cmp_range[0], cmp_range[1], cmp_range[2]) if cmp_range else {}
    totals_q = Query(q.measures, [], q.date_from, q.date_to, q.filters)
    tot = _run(cube, db, totals_q, q.date_from, q.date_to).get((), {"values": {m: Decimal(0) for m in _needed(cube, q.measures)}})
    tot_prev = _run(cube, db, totals_q, cmp_range[0], cmp_range[1]).get((), None) if cmp_range else None

    rows = []
    any_time = bool(q.dimensions) and any(cube.dimensions[d].time for d in q.dimensions)
    keys = list(cur.keys()) + ([k for k in prev.keys() if k not in cur] if any_time else [])
    for key in keys:
        r = cur.get(key) or {"values": {m: Decimal(0) for m in _needed(cube, q.measures)}, "captions": prev.get(key, {}).get("captions", {})}
        values = _finish(cube, r["values"], q.measures)
        row = {"dims": {n: {"key": _key_out(key[i]), "label": label(cube, n, key[i], r["captions"].get(n))} for i, n in enumerate(q.dimensions)},
               "values": {m: fmt(values[m], M[m].fmt) for m in q.measures}}
        if cmp_range:
            p = prev.get(key)
            pv = _finish(cube, p["values"], q.measures) if p else {m: None for m in q.measures}
            row["compare"] = {m: fmt(pv[m], M[m].fmt) for m in q.measures}
            row["delta"] = {m: delta(values[m], pv[m]) for m in q.measures}
        rows.append(row)

    def sort_key(r):
        if q.sort in q.measures:
            v = r["values"][q.sort]
            return Decimal(str(v)) if v is not None else Decimal("-1e30")
        name = q.sort or (q.dimensions[0] if q.dimensions else None)
        if name is None:
            return 0
        k = r["dims"][name]["key"]
        return (k is None, str(k) if not isinstance(k, int) else f"{k:012d}")

    time_first = q.dimensions and cube.dimensions[q.dimensions[0]].time and not q.sort
    rows.sort(key=sort_key, reverse=False if time_first or (q.sort and q.sort in q.dimensions) else q.desc)
    if time_first:
        rows.sort(key=lambda r: (r["dims"][q.dimensions[0]]["key"] is None, str(r["dims"][q.dimensions[0]]["key"] or "").zfill(12)))
    truncated = len(rows) > q.limit
    rows = rows[:q.limit]
    tv = _finish(cube, tot["values"], q.measures)
    out = {"rows": rows, "truncated": truncated, "totals": {m: fmt(tv[m], M[m].fmt) for m in q.measures},
           "period": {"from": q.date_from.isoformat(), "to": q.date_to.isoformat()}}
    if cmp_range:
        pv = _finish(cube, tot_prev["values"], q.measures) if tot_prev else {m: None for m in q.measures}
        out["totals_compare"] = {m: fmt(pv[m], M[m].fmt) for m in q.measures}
        out["totals_delta"] = {m: delta(tv[m], pv[m]) for m in q.measures}
        out["compare_period"] = {"from": cmp_range[0].isoformat(), "to": cmp_range[1].isoformat()}
    return out


def detail(cube: Cube, db: Session, q: Query, pro: bool, limit: int = 300) -> list[dict]:
    """Drill-through: le righe che compongono il numero selezionato."""
    validate(cube, Query([cube.default_measure], [], q.date_from, q.date_to, q.filters), pro)
    t = cube.table.c
    cols = [t[c] for _, c, _ in cube.detail_cols]
    stmt = select(*cols).where(cube.dd >= q.date_from, cube.dd <= q.date_to)
    for name, values in q.filters.items():
        if values:
            stmt = stmt.where(filter_cond(cube, name, values))
    rows = db.execute(stmt.order_by(cube.dd.desc()).limit(limit)).mappings().all()
    out = []
    for r in rows:
        item = {}
        for name, col, kind in cube.detail_cols:
            v = r[col]
            item[name] = fmt(v, kind) if kind in ("euro", "numero", "intero", "giorni", "percento") else (v.isoformat() if hasattr(v, "isoformat") else (str(v) if isinstance(v, _uuid.UUID) else v))
        if cube.detail_label:
            item["label"] = cube.detail_label(r)
        out.append(item)
    return out


def values(cube: Cube, db: Session, name: str, text: str | None, pro: bool, limit: int = 50) -> list[dict]:
    """Valori di una dimensione (per scegliere i filtri), con ricerca nel nome."""
    if name not in cube.dimensions:
        raise QueryError(f"Dimensione sconosciuta: {name}")
    d = cube.dimensions[name]
    if (d.pro or cube.pro) and not pro:
        raise QueryError("Disponibile nelle statistiche avanzate (pacchetto Pro)")
    k = d.key(cube.dd).label("k")
    cap = (d.caption(cube.dd) if d.caption else d.key(cube.dd))
    stmt = select(k, func.max(cap).label("c")).group_by(k).order_by(func.count().desc()).limit(limit)
    if text:
        stmt = stmt.where(cast(cap, String).ilike(f"%{text.strip()}%"))
    rows = db.execute(stmt).all()
    return [{"key": _key_out(r.k), "label": label(cube, name, r.k, r.c)} for r in rows]


def to_excel(cube: Cube, q: Query, res: dict, title: str | None = None) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = (title or f"Analisi {cube.label}")[:31]
    dims = [cube.dimensions[d].label for d in q.dimensions]
    meas = [cube.measures[m].label for m in q.measures]
    header = dims + meas + ([f"{m} (confronto)" for m in meas] + [f"{m} Δ%" for m in meas] if q.compare else [])
    ws.append([(title + " · " if title else "") + f"Periodo {q.date_from.strftime('%d/%m/%Y')} – {q.date_to.strftime('%d/%m/%Y')}"
               + (f" · filtri: {', '.join(cube.dimensions[k].label for k in q.filters)}" if q.filters else "")])
    ws.append(header)
    for cell in ws[2]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2340A8")

    def num(v):
        return float(v) if isinstance(v, str) else v

    for r in res["rows"]:
        line = [r["dims"][d]["label"] for d in q.dimensions] + [num(r["values"][m]) for m in q.measures]
        if q.compare:
            line += [num(r["compare"][m]) for m in q.measures] + [num(r["delta"][m]) for m in q.measures]
        ws.append(line)
    ws.append(["Totale"] + [""] * (len(dims) - 1 if dims else 0) + [num(res["totals"][m]) for m in q.measures])
    for cell in ws[ws.max_row]:
        cell.font = Font(bold=True)
    for i in range(len(header)):
        ws.column_dimensions[get_column_letter(i + 1)].width = 34 if i < len(dims) else 16
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
