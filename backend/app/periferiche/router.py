"""API periferiche: /api/periferiche/...  (modulo "periferiche", pacchetto Plus)."""

import io
import time
import uuid
import zipfile
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.db import set_tenant
from app.core.deps import TenantContext, require_module
from app.documenti.models import Document
from app.periferiche import labels as lab
from app.periferiche import service as per
from app.periferiche.models import Agent, AgentKey, Device, DeviceJob, LabelTemplate
from app.pos.models import PosRegister
from app.saas.service import audit

router = APIRouter(prefix="/api/periferiche", tags=["periferiche"])
module = require_module("periferiche")
ADMINS = ("amministratore", "amministrazione")
def agent_dir() -> Path:
    from app.core.config import get_settings
    return Path(get_settings().agent_dir) if get_settings().agent_dir else Path(__file__).resolve().parents[3] / "agent"


def user(ctx: TenantContext = Depends(module)) -> TenantContext:
    if ctx.user.role == "agente":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non usa le periferiche del negozio")
    return ctx


def admin(ctx: TenantContext = Depends(module)) -> TenantContext:
    if ctx.user.role not in ADMINS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo l'amministrazione configura computer e periferiche")
    return ctx


def _get(ctx, model, id_):
    o = ctx.db.get(model, id_)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Non trovato")
    return o


def agent_out(ctx, a: Agent, code: str | None = None) -> dict:
    paired = ctx.db.scalar(select(AgentKey.key_hash).where(AgentKey.agent_id == a.id, AgentKey.kind == "token")) is not None
    return {"id": str(a.id), "name": a.name, "hostname": a.hostname, "version": a.version, "platform": a.platform, "paired": paired,
            "online": per.is_online(a), "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None, "active": a.active,
            "pairing_code": code, "devices": len(ctx.db.scalars(select(Device.id).where(Device.agent_id == a.id)).all())}


def device_out(ctx, d: Device, agents: dict | None = None) -> dict:
    a = (agents or {}).get(d.agent_id) or ctx.db.get(Agent, d.agent_id)
    return {"id": str(d.id), "name": d.name, "kind": d.kind, "kind_label": per.KINDS.get(d.kind, d.kind), "driver": d.driver,
            "driver_label": per.DRIVERS.get(d.driver, {}).get("label", d.driver), "address": d.address, "options": d.options or {},
            "active": d.active, "agent_id": str(d.agent_id), "agent_name": a.name if a else None, "agent_online": per.is_online(a) if a else False}


# ====================================================================== computer (agent)


class AgentIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    active: bool = True


@router.get("/computer")
def list_agents(ctx: TenantContext = Depends(user)):
    return [agent_out(ctx, a) for a in ctx.db.scalars(select(Agent).order_by(Agent.name))]


@router.post("/computer", status_code=201)
def create_agent(body: AgentIn, ctx: TenantContext = Depends(admin)):
    a = Agent(tenant_id=ctx.tenant_id, name=body.name.strip(), active=True)
    ctx.db.add(a)
    ctx.db.flush()
    code = per.new_pairing_code(ctx.db, a)
    audit(ctx.db, "agent", "creazione", a.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, after={"name": a.name})
    return agent_out(ctx, a, code)


@router.post("/computer/{agent_id}/codice")
def new_code(agent_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    a = _get(ctx, Agent, agent_id)
    return agent_out(ctx, a, per.new_pairing_code(ctx.db, a))


@router.put("/computer/{agent_id}")
def update_agent(agent_id: uuid.UUID, body: AgentIn, ctx: TenantContext = Depends(admin)):
    a = _get(ctx, Agent, agent_id)
    a.name, a.active = body.name.strip(), body.active
    ctx.db.flush()
    return agent_out(ctx, a)


@router.delete("/computer/{agent_id}", status_code=204)
def delete_agent(agent_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    a = _get(ctx, Agent, agent_id)
    ctx.db.execute(AgentKey.__table__.delete().where(AgentKey.agent_id == a.id))  # il token non vale più
    ctx.db.delete(a)
    audit(ctx.db, "agent", "eliminazione", agent_id, tenant_id=ctx.tenant_id, user_id=ctx.user.id, before={"name": a.name})


@router.get("/agent/scarica")
def download_agent(ctx: TenantContext = Depends(user)):
    """Pacchetto da installare sul computer del negozio: agent, istruzioni e avvio automatico."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("blubeauty_agent.py", "LEGGIMI.txt", "avvia-agent.bat", "blubeauty-agent.service"):
            p = agent_dir() / name
            if p.exists():
                z.write(p, f"BluBeautyAgent/{name}")
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="BluBeautyAgent.zip"'})


# ====================================================================== dispositivi


class DeviceIn(BaseModel):
    agent_id: uuid.UUID
    name: str = Field(min_length=1, max_length=60)
    driver: str
    address: str | None = Field(None, max_length=200)
    options: dict = {}
    active: bool = True


@router.get("/driver")
def drivers(ctx: TenantContext = Depends(user)):
    return {"kinds": per.KINDS, "drivers": per.DRIVERS}


@router.get("/dispositivi")
def list_devices(kind: str | None = None, ctx: TenantContext = Depends(user)):
    agents = {a.id: a for a in ctx.db.scalars(select(Agent))}
    q = select(Device).order_by(Device.kind, Device.name)
    if kind:
        q = q.where(Device.kind == kind)
    return [device_out(ctx, d, agents) for d in ctx.db.scalars(q)]


def _save_device(ctx, d: Device, body: DeviceIn):
    if body.driver not in per.DRIVERS:
        raise HTTPException(422, "Tipo di collegamento non valido")
    if ctx.db.get(Agent, body.agent_id) is None:
        raise HTTPException(422, "Computer non valido")
    spec = per.DRIVERS[body.driver]
    needs_address = not body.driver.startswith("simulatore")
    if needs_address and not (body.address or "").strip():
        raise HTTPException(422, f"Indica {spec['address'].lower()}")
    d.agent_id, d.name, d.driver, d.kind = body.agent_id, body.name.strip(), body.driver, spec["kind"]
    d.address = (body.address or "").strip() or None
    d.options = {**spec["options"], **(body.options or {})}
    d.active = body.active
    ctx.db.flush()
    return device_out(ctx, d)


@router.post("/dispositivi", status_code=201)
def create_device(body: DeviceIn, ctx: TenantContext = Depends(admin)):
    d = Device(tenant_id=ctx.tenant_id)
    ctx.db.add(d)
    return _save_device(ctx, d, body)


@router.put("/dispositivi/{device_id}")
def update_device(device_id: uuid.UUID, body: DeviceIn, ctx: TenantContext = Depends(admin)):
    return _save_device(ctx, _get(ctx, Device, device_id), body)


@router.delete("/dispositivi/{device_id}", status_code=204)
def delete_device(device_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    d = _get(ctx, Device, device_id)
    for reg in ctx.db.scalars(select(PosRegister)):
        if str(d.id) in [str(v) for v in (reg.devices or {}).values()]:
            raise HTTPException(409, f"Il dispositivo è collegato alla cassa «{reg.name}»: toglilo prima dalla cassa")
    ctx.db.delete(d)


def _wait(ctx: TenantContext, job_id: uuid.UUID, seconds: float) -> DeviceJob:
    """Aspetta l'esito di un lavoro (prova, bilancia): si conferma la richiesta e si rilegge finché l'agent risponde."""
    tid = ctx.tenant_id
    ctx.db.commit()
    end = time.monotonic() + seconds
    while True:
        set_tenant(ctx.db, tid)
        j = ctx.db.get(DeviceJob, job_id, populate_existing=True)
        if j.status in ("eseguito", "errore") or time.monotonic() >= end:
            return j
        ctx.db.commit()  # nuova transazione: si vedono gli esiti salvati dall'agent
        time.sleep(0.3)


TEST_PAGE = {"lines": [{"text": "BluBeauty", "align": "center", "bold": True, "size": 2}, {"text": "Prova di stampa riuscita", "align": "center"},
                       {"type": "line"}, {"text": "Articolo di prova", "right": "1,00"}, {"type": "barcode", "data": "123456789012", "align": "center"},
                       {"type": "cut"}]}


@router.post("/dispositivi/{device_id}/prova")
def test_device(device_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    d = _get(ctx, Device, device_id)
    if d.kind == "stampante":
        kind, payload = "print.text", TEST_PAGE
    elif d.kind == "etichette":
        tpl = {"width_mm": 50, "height_mm": 30, "elements": lab.DEFAULT_TEMPLATES[0]["elements"]}
        kind, payload = "print.zpl", {"zpl": lab.to_zpl(tpl, [{"quantity": 1, "fields": {"description": "Etichetta di prova BluBeauty",
                                                                                          "price": "€ 1,00", "barcode": "8001234567897"}}])}
    elif d.kind == "bilancia":
        kind, payload = "scale.read", {}
    else:
        kind, payload = "status", {}
    j = per.enqueue(ctx.db, d, kind, payload, user_id=ctx.user.id)
    j = _wait(ctx, j.id, 12)
    agent = ctx.db.get(Agent, d.agent_id)
    if j.status == "in_coda":
        per.cancel(ctx.db, j)
        return {"ok": False, "error": f"Il computer «{agent.name}» non risponde: controlla che l'agent sia avviato e collegato a internet"}
    return {"ok": j.status == "eseguito", "result": j.result, "error": j.error, "status": j.status}


@router.post("/bilancia/{device_id}/leggi")
def read_scale(device_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    d = _get(ctx, Device, device_id)
    if d.kind != "bilancia":
        raise HTTPException(422, "Non è una bilancia")
    j = per.enqueue(ctx.db, d, "scale.read", {}, user_id=ctx.user.id)
    j = _wait(ctx, j.id, 8)
    if j.status == "in_coda":
        per.cancel(ctx.db, j)
        raise HTTPException(504, "La bilancia non risponde: il computer a cui è collegata è spento o non collegato")
    if j.status != "eseguito":
        raise HTTPException(422, j.error or "Lettura non riuscita")
    return j.result


# ====================================================================== coda dei lavori


@router.get("/lavori")
def list_jobs(device_id: uuid.UUID | None = None, stato: str | None = None, document_id: uuid.UUID | None = None,
              limit: int = Query(100, le=500), ctx: TenantContext = Depends(user)):
    q = select(DeviceJob).order_by(DeviceJob.created_at.desc()).limit(limit)
    if device_id:
        q = q.where(DeviceJob.device_id == device_id)
    if stato:
        q = q.where(DeviceJob.status == stato)
    if document_id:
        q = q.where(DeviceJob.document_id == document_id)
    devs = {d.id: d for d in ctx.db.scalars(select(Device))}
    return [per.job_out(j, devs.get(j.device_id)) for j in ctx.db.scalars(q)]


@router.get("/lavori/{job_id}")
def get_job(job_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    j = _get(ctx, DeviceJob, job_id)
    return per.job_out(j, ctx.db.get(Device, j.device_id))


class RetryIn(BaseModel):
    force: bool = False


@router.post("/lavori/{job_id}/riprova")
def retry_job(job_id: uuid.UUID, body: RetryIn, ctx: TenantContext = Depends(user)):
    j = per.retry(ctx.db, _get(ctx, DeviceJob, job_id), ctx.user.id, body.force)
    return per.job_out(j, ctx.db.get(Device, j.device_id))


@router.post("/lavori/{job_id}/annulla")
def cancel_job(job_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    j = _get(ctx, DeviceJob, job_id)
    if j.status != "in_coda":
        raise HTTPException(409, "Si annullano solo i lavori ancora in coda")
    per.cancel(ctx.db, j)
    return per.job_out(j, ctx.db.get(Device, j.device_id))


# ====================================================================== etichette


class ElementIn(BaseModel):
    type: str
    field: str | None = None
    text: str | None = Field(None, max_length=200)
    prefix: str | None = Field(None, max_length=20)
    x: float = 0
    y: float = 0
    w: float | None = None
    h: float | None = None
    size: float | None = None
    lines: int | None = None
    align: str | None = None
    bold: bool | None = None
    module: int | None = None
    symbology: str | None = None
    thickness: float | None = None


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    width_mm: Decimal = Field(gt=5, le=300)
    height_mm: Decimal = Field(gt=5, le=300)
    dpi: int = Field(203, ge=150, le=600)
    gap_mm: Decimal = Field(Decimal(3), ge=0, le=20)
    elements: list[ElementIn] = Field(default_factory=list, max_length=40)
    is_default: bool = False


def tpl_out(t: LabelTemplate) -> dict:
    return {"id": str(t.id), "name": t.name, "width_mm": float(t.width_mm), "height_mm": float(t.height_mm), "dpi": t.dpi,
            "gap_mm": float(t.gap_mm), "elements": t.elements or [], "is_default": t.is_default}


def _ensure_templates(ctx) -> None:
    if ctx.db.scalar(select(LabelTemplate.id).limit(1)) is None:
        for n, t in enumerate(lab.DEFAULT_TEMPLATES):
            ctx.db.add(LabelTemplate(tenant_id=ctx.tenant_id, name=t["name"], width_mm=t["width_mm"], height_mm=t["height_mm"], dpi=203,
                                     gap_mm=3, elements=t["elements"], is_default=n == 0))
        ctx.db.flush()


@router.get("/etichette/campi")
def label_fields(ctx: TenantContext = Depends(user)):
    return {"fields": lab.FIELDS, "types": lab.ELEMENT_TYPES}


@router.get("/etichette/modelli")
def list_templates(ctx: TenantContext = Depends(user)):
    if ctx.user.role in ADMINS:
        _ensure_templates(ctx)
    return [tpl_out(t) for t in ctx.db.scalars(select(LabelTemplate).order_by(LabelTemplate.is_default.desc(), LabelTemplate.name))]


def _save_tpl(ctx, t: LabelTemplate, body: TemplateIn):
    for el in body.elements:
        if el.type not in lab.ELEMENT_TYPES or (el.type != "box" and el.field not in lab.FIELDS):
            raise HTTPException(422, "Elemento dell'etichetta non valido")
    t.name, t.width_mm, t.height_mm, t.dpi, t.gap_mm = body.name.strip(), body.width_mm, body.height_mm, body.dpi, body.gap_mm
    t.elements = [el.model_dump(exclude_none=True) for el in body.elements]
    if body.is_default:
        for o in ctx.db.scalars(select(LabelTemplate).where(LabelTemplate.id != t.id, LabelTemplate.is_default)):
            o.is_default = False
    t.is_default = body.is_default
    ctx.db.flush()
    return tpl_out(t)


@router.post("/etichette/modelli", status_code=201)
def create_template(body: TemplateIn, ctx: TenantContext = Depends(admin)):
    t = LabelTemplate(tenant_id=ctx.tenant_id)
    ctx.db.add(t)
    return _save_tpl(ctx, t, body)


@router.put("/etichette/modelli/{tpl_id}")
def update_template(tpl_id: uuid.UUID, body: TemplateIn, ctx: TenantContext = Depends(admin)):
    return _save_tpl(ctx, _get(ctx, LabelTemplate, tpl_id), body)


@router.delete("/etichette/modelli/{tpl_id}", status_code=204)
def delete_template(tpl_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    ctx.db.delete(_get(ctx, LabelTemplate, tpl_id))


class LabelRow(BaseModel):
    item_id: uuid.UUID
    variant_id: uuid.UUID | None = None
    quantity: int = Field(1, ge=0, le=999)


class LabelsIn(BaseModel):
    rows: list[LabelRow] = Field(min_length=1, max_length=500)
    price_list_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None


@router.post("/etichette/dati")
def label_data(body: LabelsIn, ctx: TenantContext = Depends(user)):
    return lab.item_fields(ctx.db, [r.model_dump(mode="json") for r in body.rows if r.quantity > 0], body.price_list_id)


@router.post("/etichette/stampa")
def print_labels(body: LabelsIn, ctx: TenantContext = Depends(user)):
    if not body.device_id or not body.template_id:
        raise HTTPException(422, "Scegli il modello e la stampante di etichette")
    t = _get(ctx, LabelTemplate, body.template_id)
    d = _get(ctx, Device, body.device_id)
    if d.kind != "etichette":
        raise HTTPException(422, "Il dispositivo scelto non è una stampante di etichette")
    data = lab.item_fields(ctx.db, [r.model_dump(mode="json") for r in body.rows if r.quantity > 0], body.price_list_id)
    zpl = lab.to_zpl(tpl_out(t), data)
    j = per.enqueue(ctx.db, d, "print.zpl", {"zpl": zpl, "copies": 1}, user_id=ctx.user.id)
    return {"job": per.job_out(j, d), "labels": sum(x["quantity"] for x in data)}


@router.get("/etichette/da-documento/{doc_id}")
def labels_from_document(doc_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    """Righe di un documento (es. DDT o fattura del fornitore appena caricati) → etichette da stampare."""
    d = _get(ctx, Document, doc_id)
    rows = {}
    for ln in d.lines:
        if not ln.item_id or not ln.quantity or ln.quantity <= 0:
            continue
        k = (str(ln.item_id), str(ln.variant_id) if ln.variant_id else None)
        rows[k] = rows.get(k, 0) + int(Decimal(ln.quantity).to_integral_value())
    return [{"item_id": k[0], "variant_id": k[1], "quantity": q} for k, q in rows.items() if q > 0]


# ====================================================================== cassa


@router.get("/cassa/{register_id}")
def register_devices(register_id: uuid.UUID, ctx: TenantContext = Depends(user)):
    """Periferiche della cassa e dati per l'agent locale (usato quando manca internet)."""
    reg = _get(ctx, PosRegister, register_id)
    out = {}
    for role in ("rt", "printer", "scale"):
        d = per.register_device(ctx.db, reg, role)
        if d:
            a = ctx.db.get(Agent, d.agent_id)
            out[role] = {**device_out(ctx, d), "local_key": a.local_key if a else None}
    return {"devices": out, "local_port": 8765}
