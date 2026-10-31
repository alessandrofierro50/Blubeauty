"""API Business Intelligence: /api/bi/...

Base: cubo delle vendite con dashboard pronte (fino a 2 dimensioni). Pro (modulo statistiche_avanzate): margini, fino a 4
dimensioni, cubi di acquisti, scadenze, preventivi/ordini e magazzino, analisi ABC e di magazzino, report builder,
report programmati via email e dashboard personali."""

import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query as Q, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.bi import analyses, engine, periods
from app.bi import reports as rep
from app.bi.facts import CUBES
from app.bi.models import Dashboard, SavedReport
from app.core.deps import TenantContext, require_module

router = APIRouter(prefix="/api/bi", tags=["bi"])
base = require_module("statistiche_base")


def reader(ctx: TenantContext = Depends(base)) -> TenantContext:
    if ctx.user.role in ("cassa", "magazzino", "agente"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può vedere le statistiche di vendita")
    return ctx


def is_pro(ctx: TenantContext) -> bool:
    return "statistiche_avanzate" in ctx.state.modules and ctx.user.role in ("amministratore", "amministrazione", "contabilita")


def pro_reader(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if not is_pro(ctx):
        raise HTTPException(status.HTTP_403_FORBIDDEN, {"code": "modulo_non_incluso", "module": "statistiche_avanzate",
                                                        "message": "Disponibile nelle statistiche avanzate (pacchetto Pro)"})
    return ctx


class QueryIn(BaseModel):
    measures: list[str] = Field(min_length=1, max_length=12)
    dimensions: list[str] = Field(default_factory=list, max_length=4)
    date_from: date
    date_to: date
    filters: dict[str, list[str | int | None]] = Field(default_factory=dict)
    compare: str | None = None
    sort: str | None = None
    desc: bool = True
    limit: int = 100


def _q(body: QueryIn) -> engine.Query:
    return engine.Query(measures=body.measures, dimensions=body.dimensions, date_from=body.date_from, date_to=body.date_to,
                        filters={k: v for k, v in body.filters.items() if v}, compare=body.compare, sort=body.sort, desc=body.desc,
                        limit=body.limit)


def _cube(name: str) -> engine.Cube:
    if name not in CUBES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Analisi non trovata")
    return CUBES[name]


def _xlsx(data: bytes, name: str) -> StreamingResponse:
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


def _err(exc: engine.QueryError):
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


# ====================================================================== cubi (vendite nel Base, gli altri nel Pro)


@router.get("/cubi")
def cubes(ctx: TenantContext = Depends(reader)):
    pro = is_pro(ctx)
    return [{"name": c.name, "label": c.label, "description": c.description, "available": pro or not c.pro, "pro": c.pro} for c in CUBES.values()]


@router.get("/periodi")
def period_list(ctx: TenantContext = Depends(reader)):
    return [{"value": k, "label": v[0], **dict(zip(("from", "to"), [x.isoformat() for x in periods.resolve(k)])) } for k, v in periods.PERIODS.items()]


@router.get("/{cube_name}/modello")
def cube_model(cube_name: str, ctx: TenantContext = Depends(reader)):
    return engine.model(_cube(cube_name), is_pro(ctx))


@router.post("/{cube_name}/query")
def cube_query(cube_name: str, body: QueryIn, ctx: TenantContext = Depends(reader)):
    try:
        return engine.execute(_cube(cube_name), ctx.db, _q(body), is_pro(ctx))
    except engine.QueryError as exc:
        raise _err(exc) from None


@router.post("/{cube_name}/dettaglio")
def cube_detail(cube_name: str, body: QueryIn, ctx: TenantContext = Depends(reader)):
    try:
        return engine.detail(_cube(cube_name), ctx.db, _q(body), is_pro(ctx))
    except engine.QueryError as exc:
        raise _err(exc) from None


@router.get("/{cube_name}/valori/{dimension}")
def cube_values(cube_name: str, dimension: str, q: str | None = None, ctx: TenantContext = Depends(reader)):
    try:
        return engine.values(_cube(cube_name), ctx.db, dimension, q, is_pro(ctx))
    except engine.QueryError as exc:
        raise _err(exc) from None


@router.post("/{cube_name}/excel")
def cube_excel(cube_name: str, body: QueryIn, ctx: TenantContext = Depends(reader)):
    cube = _cube(cube_name)
    q = _q(body)
    q.limit = 5000
    try:
        res = engine.execute(cube, ctx.db, q, is_pro(ctx))
    except engine.QueryError as exc:
        raise _err(exc) from None
    return _xlsx(engine.to_excel(cube, q, res), f"analisi-{cube.name}-{q.date_from}-{q.date_to}.xlsx")


# ====================================================================== analisi Pro


@router.get("/analisi/abc")
def abc(oggetto: str = Q("articolo", pattern="^(articolo|cliente|fornitore)$"), misura: str = "fatturato",
        periodo: str = "ultimi_12_mesi", date_from: date | None = None, date_to: date | None = None,
        soglia_a: float = Q(80, gt=0, lt=100), soglia_b: float = Q(95, gt=0, le=100), ctx: TenantContext = Depends(pro_reader)):
    d1, d2 = periods.resolve(periodo, date_from, date_to)
    try:
        return analyses.abc(ctx.db, oggetto, misura, d1, d2, soglia_a, soglia_b)
    except engine.QueryError as exc:
        raise _err(exc) from None


@router.get("/analisi/magazzino")
def stock_health(giorni: int = Q(90, ge=7, le=730), magazzino: uuid.UUID | None = None, ctx: TenantContext = Depends(pro_reader)):
    return analyses.stock_health(ctx.db, giorni, magazzino)


@router.get("/analisi/clienti")
def customers(giorni_inattivo: int = Q(90, ge=15, le=1095), ctx: TenantContext = Depends(pro_reader)):
    return analyses.customers(ctx.db, giorni_inattivo)


@router.get("/analisi/garanzie")
def warranties(giorni: int = Q(60, ge=0, le=730), ctx: TenantContext = Depends(pro_reader)):
    return analyses.warranties(ctx.db, giorni)


# ====================================================================== report salvati


class ReportIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cube: str
    config: dict
    shared: bool = True
    schedule: dict = Field(default_factory=dict)


def _visible(ctx):
    return or_(SavedReport.shared, SavedReport.owner_id == ctx.user.id)


def _report(ctx, rid: uuid.UUID, write: bool = False) -> SavedReport:
    r = ctx.db.get(SavedReport, rid)
    if r is None or (not r.shared and r.owner_id != ctx.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report non trovato")
    if write and r.owner_id != ctx.user.id and ctx.user.role != "amministratore":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo chi ha creato il report (o l'amministratore) può modificarlo")
    return r


@router.get("/report")
def list_reports(ctx: TenantContext = Depends(pro_reader)):
    rows = ctx.db.scalars(select(SavedReport).where(_visible(ctx)).order_by(SavedReport.name)).all()
    return [rep.report_out(r, ctx.user.id) for r in rows]


def _save_report(ctx, r: SavedReport, body: ReportIn):
    try:
        cfg = rep.clean_config(_cube(body.cube), body.config, True)
        sched = rep.clean_schedule(body.schedule)
    except engine.QueryError as exc:
        raise _err(exc) from None
    r.name, r.cube, r.config, r.shared, r.schedule = body.name.strip(), body.cube, cfg, body.shared, sched
    ctx.db.flush()
    return rep.report_out(r, ctx.user.id)


@router.post("/report", status_code=201)
def create_report(body: ReportIn, ctx: TenantContext = Depends(pro_reader)):
    r = SavedReport(tenant_id=ctx.tenant_id, owner_id=ctx.user.id)
    ctx.db.add(r)
    return _save_report(ctx, r, body)


@router.get("/report/{rid}")
def get_report(rid: uuid.UUID, ctx: TenantContext = Depends(pro_reader)):
    return rep.report_out(_report(ctx, rid), ctx.user.id)


@router.put("/report/{rid}")
def update_report(rid: uuid.UUID, body: ReportIn, ctx: TenantContext = Depends(pro_reader)):
    return _save_report(ctx, _report(ctx, rid, write=True), body)


@router.delete("/report/{rid}", status_code=204)
def delete_report(rid: uuid.UUID, ctx: TenantContext = Depends(pro_reader)):
    r = _report(ctx, rid, write=True)
    for dash in ctx.db.scalars(select(Dashboard)):
        if any(w.get("report_id") == str(r.id) for w in dash.widgets or []):
            dash.widgets = [w for w in dash.widgets if w.get("report_id") != str(r.id)]
    ctx.db.delete(r)


@router.get("/report/{rid}/esegui")
def run_report(rid: uuid.UUID, ctx: TenantContext = Depends(pro_reader)):
    r = _report(ctx, rid)
    try:
        return rep.run(ctx.db, r, True)
    except engine.QueryError as exc:
        raise _err(exc) from None


@router.get("/report/{rid}/excel")
def report_excel(rid: uuid.UUID, ctx: TenantContext = Depends(pro_reader)):
    r = _report(ctx, rid)
    try:
        data = rep.excel(ctx.db, r, True)
    except engine.QueryError as exc:
        raise _err(exc) from None
    return _xlsx(data, f"{rep.slug(r.name)}.xlsx")


@router.post("/report/{rid}/invia")
def send_report(rid: uuid.UUID, ctx: TenantContext = Depends(pro_reader)):
    r = _report(ctx, rid)
    emails = (r.schedule or {}).get("emails") or [ctx.user.email]
    try:
        rep.send(ctx.db, r, emails)
    except engine.QueryError as exc:
        raise _err(exc) from None
    return {"sent_to": emails}


# ====================================================================== dashboard


class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    shared: bool = False
    widgets: list[dict] = Field(default_factory=list, max_length=24)


def _dash(ctx, did: uuid.UUID) -> Dashboard:
    d = ctx.db.get(Dashboard, did)
    if d is None or (not d.shared and d.owner_id != ctx.user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dashboard non trovata")
    return d


def dash_out(d: Dashboard, user_id) -> dict:
    return {"id": str(d.id), "name": d.name, "shared": d.shared, "widgets": d.widgets or [], "mine": d.owner_id == user_id}


@router.get("/dashboard")
def list_dashboards(ctx: TenantContext = Depends(pro_reader)):
    rows = ctx.db.scalars(select(Dashboard).where(or_(Dashboard.shared, Dashboard.owner_id == ctx.user.id)).order_by(Dashboard.name)).all()
    return [dash_out(d, ctx.user.id) for d in rows]


def _save_dash(ctx, d: Dashboard, body: DashboardIn):
    ids = {str(x) for x in ctx.db.scalars(select(SavedReport.id).where(_visible(ctx)))}
    widgets = []
    for w in body.widgets:
        if str(w.get("report_id")) in ids:
            widgets.append({"report_id": str(w["report_id"]), "width": max(1, min(4, int(w.get("width") or 2))),
                            "view": w.get("view") if w.get("view") in ("kpi", "grafico", "tabella") else "grafico"})
    d.name, d.shared, d.widgets = body.name.strip(), body.shared, widgets
    ctx.db.flush()
    return dash_out(d, ctx.user.id)


@router.post("/dashboard", status_code=201)
def create_dashboard(body: DashboardIn, ctx: TenantContext = Depends(pro_reader)):
    d = Dashboard(tenant_id=ctx.tenant_id, owner_id=ctx.user.id)
    ctx.db.add(d)
    return _save_dash(ctx, d, body)


@router.put("/dashboard/{did}")
def update_dashboard(did: uuid.UUID, body: DashboardIn, ctx: TenantContext = Depends(pro_reader)):
    d = _dash(ctx, did)
    if d.owner_id != ctx.user.id and ctx.user.role != "amministratore":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo chi ha creato la dashboard può modificarla")
    return _save_dash(ctx, d, body)


@router.delete("/dashboard/{did}", status_code=204)
def delete_dashboard(did: uuid.UUID, ctx: TenantContext = Depends(pro_reader)):
    d = _dash(ctx, did)
    if d.owner_id != ctx.user.id and ctx.user.role != "amministratore":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo chi ha creato la dashboard può eliminarla")
    ctx.db.delete(d)
