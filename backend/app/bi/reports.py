"""Report builder: configurazione dei report salvati, esecuzione su periodo relativo, Excel (anche a tabella pivot) e invii programmati."""

import io
import logging
import re
from datetime import date, datetime, timezone
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bi import engine, periods
from app.bi.facts import CUBES
from app.bi.models import SavedReport

log = logging.getLogger("blubeauty.report")
CHARTS = ("tabella", "barre", "linee", "torta", "kpi")
FREQUENCIES = ("", "giornaliero", "settimanale", "mensile")
WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60] or "report"


def clean_config(cube: engine.Cube, cfg: dict, pro: bool) -> dict:
    rows = [d for d in (cfg.get("rows") or []) if d][:3]
    col = cfg.get("columns") or None
    measures = [m for m in (cfg.get("measures") or []) if m][:8]
    filters = {k: v for k, v in (cfg.get("filters") or {}).items() if v}
    per = cfg.get("period") or {}
    kind = per.get("kind") or "ultimi_12_mesi"
    if kind not in periods.PERIODS and kind != "personalizzato":
        raise engine.QueryError("Periodo non valido")
    d1 = date.fromisoformat(per["from"]) if per.get("from") else None
    d2 = date.fromisoformat(per["to"]) if per.get("to") else None
    if kind == "personalizzato" and not (d1 and d2):
        raise engine.QueryError("Indica le date del periodo")
    chart = cfg.get("chart") if cfg.get("chart") in CHARTS else "tabella"
    if col and col in rows:
        raise engine.QueryError("La stessa dimensione non può stare nelle righe e nelle colonne")
    out = {"rows": rows, "columns": col, "measures": measures, "filters": filters,
           "period": {"kind": kind, "from": d1.isoformat() if d1 else None, "to": d2.isoformat() if d2 else None},
           "compare": cfg.get("compare") or None, "chart": chart, "sort": cfg.get("sort") or None, "desc": cfg.get("desc", True) is not False,
           "limit": max(1, min(int(cfg.get("limit") or 200), 1000))}
    engine.validate(cube, query(out), pro)
    return out


def clean_schedule(s: dict) -> dict:
    freq = (s or {}).get("frequency") or ""
    if freq not in FREQUENCIES:
        raise engine.QueryError("Frequenza di invio non valida")
    if not freq:
        return {}
    emails = []
    for e in (s.get("emails") or [])[:10]:
        e = str(e).strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e):
            raise engine.QueryError(f"Indirizzo email non valido: {e}")
        emails.append(e)
    if not emails:
        raise engine.QueryError("Indica almeno un destinatario")
    return {"frequency": freq, "weekday": max(0, min(6, int(s.get("weekday") or 0))), "day": max(1, min(31, int(s.get("day") or 1))),
            "emails": emails}


def query(cfg: dict, today: date | None = None) -> engine.Query:
    per = cfg.get("period") or {}
    d1, d2 = periods.resolve(per.get("kind"), date.fromisoformat(per["from"]) if per.get("from") else None,
                             date.fromisoformat(per["to"]) if per.get("to") else None, today)
    dims = list(cfg.get("rows") or []) + ([cfg["columns"]] if cfg.get("columns") else [])
    return engine.Query(measures=list(cfg.get("measures") or []), dimensions=dims, date_from=d1, date_to=d2, filters=cfg.get("filters") or {},
                        compare=cfg.get("compare"), sort=cfg.get("sort"), desc=cfg.get("desc", True), limit=cfg.get("limit") or 200)


def schedule_label(s: dict) -> str | None:
    if not s or not s.get("frequency"):
        return None
    if s["frequency"] == "giornaliero":
        return "ogni giorno"
    if s["frequency"] == "settimanale":
        return f"ogni {WEEKDAYS[s.get('weekday', 0)]}"
    return f"il giorno {s.get('day', 1)} di ogni mese"


def report_out(r: SavedReport, user_id=None) -> dict:
    cube = CUBES.get(r.cube)
    per = (r.config or {}).get("period") or {}
    return {"id": str(r.id), "name": r.name, "cube": r.cube, "cube_label": cube.label if cube else r.cube, "config": r.config or {},
            "shared": r.shared, "schedule": r.schedule or {}, "schedule_label": schedule_label(r.schedule or {}),
            "period_label": periods.describe(per.get("kind"), date.fromisoformat(per["from"]) if per.get("from") else None,
                                             date.fromisoformat(per["to"]) if per.get("to") else None),
            "last_sent_at": r.last_sent_at.isoformat() if r.last_sent_at else None, "mine": r.owner_id == user_id,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None}


def run(db: Session, r: SavedReport, pro: bool, today: date | None = None) -> dict:
    cube = CUBES[r.cube]
    q = query(r.config, today)
    res = engine.execute(cube, db, q, pro)
    return {"report": report_out(r), "result": res, "model": engine.model(cube, pro)}


def excel(db: Session, r: SavedReport, pro: bool, today: date | None = None) -> bytes:
    cube = CUBES[r.cube]
    q = query(r.config, today)
    q.limit = 5000
    res = engine.execute(cube, db, q, pro)
    col = r.config.get("columns")
    if not col:
        return engine.to_excel(cube, q, res, r.name)
    return pivot_excel(cube, q, res, r.name, list(r.config.get("rows") or []), col)


def pivot_excel(cube: engine.Cube, q: engine.Query, res: dict, title: str, rows: list[str], col: str) -> bytes:
    """Tabella pivot: le righe a sinistra, un gruppo di colonne per ogni valore della dimensione in colonna."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    cols, seen = [], set()
    for r in res["rows"]:
        k = r["dims"][col]["key"]
        if k not in seen:
            seen.add(k)
            cols.append((k, r["dims"][col]["label"]))
    if cube.dimensions[col].time:
        cols.sort(key=lambda x: str(x[0]))
    grid: dict = {}
    for r in res["rows"]:
        rk = tuple(r["dims"][d]["key"] for d in rows)
        grid.setdefault(rk, {"labels": [r["dims"][d]["label"] for d in rows], "cells": {}})["cells"][r["dims"][col]["key"]] = r["values"]
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([f"{title} · {q.date_from.strftime('%d/%m/%Y')} – {q.date_to.strftime('%d/%m/%Y')}"])
    meas = q.measures
    head = [cube.dimensions[d].label for d in rows]
    for _, lab in cols:
        head += [f"{lab} · {cube.measures[m].label}" if len(meas) > 1 else lab for m in meas]
    head += [f"Totale · {cube.measures[m].label}" if len(meas) > 1 else "Totale" for m in meas]
    ws.append(head)
    for cell in ws[2]:
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2340A8")
    additive = {m for m in meas if cube.measures[m].expr is not None and cube.measures[m].fmt in ("euro", "numero", "intero")}

    def num(v):
        return float(v) if isinstance(v, str) else v

    for rk, g in grid.items():
        line = list(g["labels"])
        totals = {m: 0.0 for m in meas}
        for k, _ in cols:
            vals = g["cells"].get(k, {})
            for m in meas:
                v = num(vals.get(m))
                line.append(v)
                if v is not None and m in additive:
                    totals[m] += v
        line += [round(totals[m], 2) if m in additive else None for m in meas]
        ws.append(line)
    for i in range(len(head)):
        ws.column_dimensions[get_column_letter(i + 1)].width = 30 if i < len(rows) else 15
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _html(r: SavedReport, res: dict, cube: engine.Cube, q: engine.Query) -> str:
    M = cube.measures

    def show(m, v):
        if v is None:
            return "—"
        if M[m].fmt == "euro":
            return f"€ {float(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        if M[m].fmt == "percento":
            return f"{float(v):.1f}%".replace(".", ",")
        return str(v).replace(".", ",")

    tot = "".join(f"<td style='padding:6px 12px'><div style='color:#666;font-size:12px'>{escape(M[m].label)}</div>"
                  f"<div style='font-size:20px;font-weight:700'>{show(m, res['totals'][m])}</div></td>" for m in q.measures)
    head = "".join(f"<th style='text-align:left;padding:4px 8px;border-bottom:1px solid #ddd'>{escape(cube.dimensions[d].label)}</th>" for d in q.dimensions)
    head += "".join(f"<th style='text-align:right;padding:4px 8px;border-bottom:1px solid #ddd'>{escape(M[m].label)}</th>" for m in q.measures)
    body = ""
    for row in res["rows"][:15]:
        body += "<tr>" + "".join(f"<td style='padding:4px 8px'>{escape(row['dims'][d]['label'])}</td>" for d in q.dimensions)
        body += "".join(f"<td style='padding:4px 8px;text-align:right'>{show(m, row['values'][m])}</td>" for m in q.measures) + "</tr>"
    more = f"<p style='color:#666'>… e altre {len(res['rows']) - 15} righe nel file Excel allegato.</p>" if len(res["rows"]) > 15 else ""
    return (f"<div style='font-family:Arial,sans-serif'><h2 style='margin:0'>{escape(r.name)}</h2>"
            f"<p style='color:#666'>{escape(cube.label)} · {q.date_from.strftime('%d/%m/%Y')} – {q.date_to.strftime('%d/%m/%Y')}</p>"
            f"<table><tr>{tot}</tr></table>"
            + (f"<table style='border-collapse:collapse;margin-top:12px;font-size:13px'><tr>{head}</tr>{body}</table>{more}" if q.dimensions else "")
            + "<p style='color:#999;font-size:12px'>Report inviato automaticamente da BluBeauty.</p></div>")


def send(db: Session, r: SavedReport, emails: list[str], today: date | None = None) -> None:
    from app.core.mailer import send_email

    cube = CUBES[r.cube]
    q = query(r.config, today)
    res = engine.execute(cube, db, q, True)
    data = excel(db, r, True, today)
    send_email(emails, f"Report: {r.name}", _html(r, res, cube, q),
               attachments=[(f"{slug(r.name)}.xlsx", data, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")])


def is_due(r: SavedReport, on: date) -> bool:
    s = r.schedule or {}
    if not s.get("frequency") or not s.get("emails"):
        return False
    if r.last_sent_at and r.last_sent_at.date() >= on:
        return False
    if s["frequency"] == "giornaliero":
        return True
    if s["frequency"] == "settimanale":
        return on.weekday() == int(s.get("weekday", 0))
    import calendar
    last = calendar.monthrange(on.year, on.month)[1]
    return on.day == min(int(s.get("day", 1)), last)


def run_scheduled(session_factory, on: date) -> dict:
    """Job giornaliero: invia i report programmati per oggi (un'azienda per transazione)."""
    from app.core.db import set_tenant
    from app.core.models import Tenant
    from app.saas.service import tenant_state

    db = session_factory()
    try:
        tenants = [t.id for t in db.scalars(select(Tenant))
                   if (st := tenant_state(t, on)).access == "full" and "statistiche_avanzate" in st.modules]
    finally:
        db.close()
    out = {}
    for tid in tenants:
        db = session_factory()
        try:
            set_tenant(db, tid)
            n = 0
            for r in db.scalars(select(SavedReport)):
                if is_due(r, on):
                    try:
                        send(db, r, r.schedule["emails"], on)
                        r.last_sent_at = datetime.now(timezone.utc)
                        n += 1
                    except Exception:  # noqa: BLE001 — un report sbagliato non blocca gli altri
                        log.exception("Report programmato %s non inviato", r.id)
            db.commit()
            if n:
                out[str(tid)] = n
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("Report programmati: errore per l'azienda %s", tid)
        finally:
            db.close()
    return out
