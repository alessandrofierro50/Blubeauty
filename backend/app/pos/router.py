"""API vendita al banco: /api/pos/...  (modulo "pos", pacchetto Plus)."""

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.anagrafiche.models import Party, VatRate
from app.core.deps import TenantContext, require_module
from app.core.models import User, Warehouse
from app.documenti.models import Document
from app.magazzino.models import Store
from app.pos import service as pos
from app.pos.models import PosCashMove, PosDepartment, PosPayment, PosRegister, PosSession
from app.saas.service import audit
from app.scadenzario.models import FinancialAccount

router = APIRouter(prefix="/api/pos", tags=["pos"])
operator = require_module("pos")
ADMINS = ("amministratore", "amministrazione")


def cashier(ctx: TenantContext = Depends(operator)) -> TenantContext:
    if ctx.user.role in ("magazzino", "agente"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può usare la cassa")
    return ctx


def admin(ctx: TenantContext = Depends(operator)) -> TenantContext:
    if ctx.user.role not in ADMINS:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo l'amministrazione configura casse e reparti")
    return ctx


def s(v):
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def _get(ctx, model, id_):
    o = ctx.db.get(model, id_)
    if o is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Non trovato")
    return o


# ====================================================================== impostazioni, reparti, casse


@router.get("/impostazioni")
def get_settings(ctx: TenantContext = Depends(cashier)):
    return pos.settings(ctx.db, ctx.tenant_id)


@router.put("/impostazioni")
def put_settings(body: dict, ctx: TenantContext = Depends(admin)):
    out = pos.save_settings(ctx.db, ctx.tenant_id, body)
    ctx.db.flush()
    return out


class DepartmentIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=60)
    vat_rate_id: uuid.UUID | None = None
    rt_department: int | None = Field(None, ge=1, le=99)
    color: str | None = None
    sort_order: int = 0
    active: bool = True


def dep_out(d: PosDepartment, vats: dict) -> dict:
    v = vats.get(d.vat_rate_id)
    return {"id": str(d.id), "code": d.code, "name": d.name, "vat_rate_id": s(d.vat_rate_id), "vat_label": v.description if v else None,
            "vat_rate": s(v.rate) if v else None, "rt_department": d.rt_department, "color": d.color, "sort_order": d.sort_order, "active": d.active}


@router.get("/reparti")
def list_departments(ctx: TenantContext = Depends(cashier)):
    vats = {v.id: v for v in ctx.db.scalars(select(VatRate))}
    return [dep_out(d, vats) for d in ctx.db.scalars(select(PosDepartment).order_by(PosDepartment.sort_order, PosDepartment.code))]


def _save_dep(ctx, d: PosDepartment, body: DepartmentIn):
    for k, v in body.model_dump().items():
        setattr(d, k, v)
    d.code = body.code.strip().upper()
    if ctx.db.scalar(select(PosDepartment.id).where(PosDepartment.code == d.code, PosDepartment.id != d.id) if d.id else
                     select(PosDepartment.id).where(PosDepartment.code == d.code)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esiste già un reparto con codice {d.code}")
    ctx.db.flush()
    return dep_out(d, {v.id: v for v in ctx.db.scalars(select(VatRate))})


@router.post("/reparti", status_code=201)
def create_department(body: DepartmentIn, ctx: TenantContext = Depends(admin)):
    d = PosDepartment(tenant_id=ctx.tenant_id)
    ctx.db.add(d)
    return _save_dep(ctx, d, body)


@router.put("/reparti/{dep_id}")
def update_department(dep_id: uuid.UUID, body: DepartmentIn, ctx: TenantContext = Depends(admin)):
    return _save_dep(ctx, _get(ctx, PosDepartment, dep_id), body)


@router.delete("/reparti/{dep_id}", status_code=204)
def delete_department(dep_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    from app.documenti.models import DocumentLine
    d = _get(ctx, PosDepartment, dep_id)
    if ctx.db.scalar(select(func.count()).select_from(DocumentLine).where(DocumentLine.department_id == d.id)):
        d.active = False  # usato negli scontrini: si disattiva soltanto
    else:
        ctx.db.delete(d)
    ctx.db.flush()


class RegisterIn(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    name: str = Field(min_length=1, max_length=60)
    store_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID
    price_list_id: uuid.UUID | None = None
    mode: str = Field("negozio", pattern="^(negozio|supermercato)$")
    cash_account_id: uuid.UUID | None = None
    card_account_id: uuid.UUID | None = None
    quick_keys: list[dict] = []
    settings: dict = {}
    devices: dict = {}  # {"rt": id, "printer": id, "scale": id}
    active: bool = True


def reg_out(ctx, r: PosRegister) -> dict:
    cur = pos.current_session(ctx.db, r)
    wh = ctx.db.get(Warehouse, r.warehouse_id)
    st = ctx.db.get(Store, r.store_id) if r.store_id else None
    return {"id": str(r.id), "code": r.code, "name": r.name, "store_id": s(r.store_id), "store_name": st.name if st else None,
            "warehouse_id": s(r.warehouse_id), "warehouse_name": wh.name if wh else None, "price_list_id": s(r.price_list_id),
            "mode": r.mode, "cash_account_id": s(r.cash_account_id), "card_account_id": s(r.card_account_id),
            "quick_keys": r.quick_keys or [], "settings": r.settings or {}, "devices": r.devices or {}, "active": r.active,
            "session": session_out(ctx, cur, brief=True) if cur else None}


@router.get("/casse")
def list_registers(ctx: TenantContext = Depends(cashier)):
    return [reg_out(ctx, r) for r in ctx.db.scalars(select(PosRegister).order_by(PosRegister.code))]


@router.get("/casse/{reg_id}")
def get_register(reg_id: uuid.UUID, ctx: TenantContext = Depends(cashier)):
    return reg_out(ctx, _get(ctx, PosRegister, reg_id))


def _save_reg(ctx, r: PosRegister, body: RegisterIn):
    if ctx.db.get(Warehouse, body.warehouse_id) is None:
        raise HTTPException(422, "Magazzino non valido")
    for acc in (body.cash_account_id, body.card_account_id):
        if acc and ctx.db.get(FinancialAccount, acc) is None:
            raise HTTPException(422, "Conto non valido")
    keys = []
    for k in body.quick_keys[:60]:
        if k.get("type") in ("item", "department") and k.get("id"):
            keys.append({"type": k["type"], "id": str(k["id"]), "label": (k.get("label") or "")[:30], "color": k.get("color")})
    devices = {}
    for role, kind in (("rt", "rt"), ("printer", "stampante"), ("scale", "bilancia")):
        dev_id = (body.devices or {}).get(role)
        if dev_id:
            from app.periferiche.models import Device
            dev = ctx.db.get(Device, uuid.UUID(str(dev_id)))
            if dev is None or dev.kind != kind:
                raise HTTPException(422, "Periferica della cassa non valida")
            devices[role] = str(dev.id)
    for f, v in body.model_dump().items():
        setattr(r, f, v)
    r.code = body.code.strip().upper()
    r.quick_keys = keys
    r.devices = devices
    dup = select(PosRegister.id).where(PosRegister.code == r.code)
    if ctx.db.scalar(dup.where(PosRegister.id != r.id) if r.id else dup):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Esiste già una cassa con codice {r.code}")
    ctx.db.flush()
    return reg_out(ctx, r)


@router.post("/casse", status_code=201)
def create_register(body: RegisterIn, ctx: TenantContext = Depends(admin)):
    r = PosRegister(tenant_id=ctx.tenant_id, devices={})
    ctx.db.add(r)
    return _save_reg(ctx, r, body)


@router.put("/casse/{reg_id}")
def update_register(reg_id: uuid.UUID, body: RegisterIn, ctx: TenantContext = Depends(admin)):
    return _save_reg(ctx, _get(ctx, PosRegister, reg_id), body)


@router.delete("/casse/{reg_id}", status_code=204)
def delete_register(reg_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    r = _get(ctx, PosRegister, reg_id)
    if ctx.db.scalar(select(func.count()).select_from(PosSession).where(PosSession.register_id == r.id)):
        r.active = False
    else:
        ctx.db.delete(r)
    ctx.db.flush()


# ====================================================================== in cassa


def _register(ctx, reg_id) -> PosRegister:
    r = _get(ctx, PosRegister, reg_id)
    if not r.active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cassa disattivata")
    return r


@router.get("/casse/{reg_id}/catalogo")
def get_catalog(reg_id: uuid.UUID, ctx: TenantContext = Depends(cashier)):
    return pos.catalog(ctx.db, _register(ctx, reg_id))


@router.get("/casse/{reg_id}/codice")
def lookup_code(reg_id: uuid.UUID, code: str = Query(..., min_length=1), ctx: TenantContext = Depends(cashier)):
    return pos.resolve_code(ctx.db, _register(ctx, reg_id), code)


@router.get("/clienti")
def search_customers(q: str = Query("", max_length=60), ctx: TenantContext = Depends(cashier)):
    from sqlalchemy import or_
    stmt = select(Party).where(Party.is_customer, Party.active, Party.code != "BANCO")
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Party.name.ilike(like), Party.code.ilike(like), Party.vat_number.ilike(like), Party.tax_code.ilike(like),
                              Party.phone.ilike(like), Party.mobile.ilike(like)))
    return [{"id": str(p.id), "code": p.code, "name": p.name, "vat_number": p.vat_number, "tax_code": p.tax_code, "city": p.city,
             "can_invoice": bool((p.vat_number or p.tax_code) and p.address and p.zip_code and p.city)}
            for p in ctx.db.scalars(stmt.order_by(Party.name).limit(20))]


def session_out(ctx, ses: PosSession, brief: bool = False) -> dict:
    u = ctx.db.get(User, ses.user_id) if ses.user_id else None
    out = {"id": str(ses.id), "register_id": str(ses.register_id), "status": ses.status, "opened_at": s(ses.opened_at),
           "opened_by": (u.full_name or u.email) if u else None, "opening_float": s(ses.opening_float), "closed_at": s(ses.closed_at),
           "expected_cash": s(ses.expected_cash), "counted_cash": s(ses.counted_cash), "difference": s(ses.difference),
           "z_number": ses.z_number, "notes": ses.notes}
    if not brief:
        out["summary"] = ses.summary if ses.status == "chiusa" else pos.session_summary(ctx.db, ses)
        out["moves"] = [{"id": str(m.id), "kind": m.kind, "amount": s(m.amount), "reason": m.reason, "created_at": s(m.created_at)}
                        for m in ctx.db.scalars(select(PosCashMove).where(PosCashMove.session_id == ses.id).order_by(PosCashMove.created_at))]
    return out


class OpenIn(BaseModel):
    opening_float: Decimal = Field(Decimal(0), ge=0)


@router.post("/casse/{reg_id}/apri", status_code=201)
def open_register(reg_id: uuid.UUID, body: OpenIn, ctx: TenantContext = Depends(cashier)):
    ses = pos.open_session(ctx.db, _register(ctx, reg_id), ctx.user.id, body.opening_float)
    ctx.db.flush()
    return session_out(ctx, ses)


@router.get("/aperture/{ses_id}")
def get_session(ses_id: uuid.UUID, ctx: TenantContext = Depends(cashier)):
    return session_out(ctx, _get(ctx, PosSession, ses_id))


@router.get("/aperture")
def list_sessions(register_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                  ctx: TenantContext = Depends(cashier)):
    q = select(PosSession).order_by(PosSession.opened_at.desc()).limit(200)
    if register_id:
        q = q.where(PosSession.register_id == register_id)
    if date_from:
        q = q.where(PosSession.opened_at >= datetime.combine(date_from, time.min, timezone.utc))
    if date_to:
        q = q.where(PosSession.opened_at <= datetime.combine(date_to, time.max, timezone.utc))
    regs = {r.id: r for r in ctx.db.scalars(select(PosRegister))}
    out = []
    for ses in ctx.db.scalars(q):
        o = session_out(ctx, ses, brief=True)
        o["register_name"] = regs[ses.register_id].name if ses.register_id in regs else None
        tot = ctx.db.scalar(select(func.coalesce(func.sum(PosPayment.amount), 0)).where(PosPayment.session_id == ses.id))
        o["takings"] = s(Decimal(tot))
        out.append(o)
    return out


class MoveIn(BaseModel):
    kind: str = Field(pattern="^(prelievo|versamento)$")
    amount: Decimal = Field(gt=0)
    reason: str | None = Field(None, max_length=120)


@router.post("/aperture/{ses_id}/movimenti", status_code=201)
def cash_move(ses_id: uuid.UUID, body: MoveIn, ctx: TenantContext = Depends(cashier)):
    ses = _get(ctx, PosSession, ses_id)
    if ses.status != "aperta":
        raise HTTPException(status.HTTP_409_CONFLICT, "La cassa è chiusa")
    ctx.db.add(PosCashMove(tenant_id=ctx.tenant_id, session_id=ses.id, kind=body.kind, amount=body.amount, reason=body.reason, user_id=ctx.user.id))
    ctx.db.flush()
    return session_out(ctx, ses)


class CloseIn(BaseModel):
    counted_cash: Decimal = Field(ge=0)
    z_number: str | None = Field(None, max_length=20)
    notes: str | None = None


@router.post("/aperture/{ses_id}/chiudi")
def close_register(ses_id: uuid.UUID, body: CloseIn, ctx: TenantContext = Depends(cashier)):
    ses = pos.close_session(ctx.db, _get(ctx, PosSession, ses_id), ctx.user.id, body.counted_cash, body.z_number, body.notes)
    if not body.z_number and "periferiche" in ctx.state.modules:  # chiusura giornaliera sul registratore
        from app.periferiche import service as per
        per.close_fiscal_day(ctx.db, ctx.db.get(PosRegister, ses.register_id), ses, ctx.user.id)
    audit(ctx.db, "pos_session", "chiusura", ses.id, tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          after={"expected": s(ses.expected_cash), "counted": s(ses.counted_cash), "difference": s(ses.difference)})
    ctx.db.flush()
    return session_out(ctx, ses)


class LineIn(BaseModel):
    item_id: uuid.UUID | None = None
    variant_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    description: str | None = Field(None, max_length=500)
    quantity: Decimal = Decimal(1)
    unit_price_gross: Decimal
    discount: Decimal | None = Field(None, ge=0, le=100)
    vat_rate_id: uuid.UUID | None = None
    lot_number: str | None = None
    serials: list[str] = []
    origin_line_id: uuid.UUID | None = None
    price_source: str | None = None


class PaymentIn(BaseModel):
    method: str
    amount: Decimal


class SaleIn(BaseModel):
    client_uuid: uuid.UUID
    session_id: uuid.UUID | None = None
    customer_id: uuid.UUID | None = None
    invoice_party_id: uuid.UUID | None = None  # fattura al banco
    lottery_code: str | None = Field(None, max_length=8)
    lines: list[LineIn]
    payments: list[PaymentIn]
    rt_result: dict | None = None  # documento già stampato dall'agent locale (cassa senza rete)


def _dump(m: BaseModel) -> dict:
    return m.model_dump(mode="json")


@router.post("/casse/{reg_id}/vendite")
def sell(reg_id: uuid.UUID, body: SaleIn, ctx: TenantContext = Depends(cashier)):
    reg = _register(ctx, reg_id)
    try:
        with ctx.db.begin_nested():
            d, change, replay = pos.create_sale(ctx.db, reg, ctx.user.id, _dump(body))
    except IntegrityError:  # stessa vendita arrivata due volte in parallelo
        d = ctx.db.scalar(select(Document).where(Document.client_uuid == body.client_uuid))
        if d is None:
            raise
        replay = True
    out = pos.receipt_out(ctx.db, d)
    out["replayed"] = replay
    return out


class ReturnIn(BaseModel):
    client_uuid: uuid.UUID
    session_id: uuid.UUID | None = None
    original_id: uuid.UUID | None = None
    void: bool = False
    restock: bool = True
    reason: str | None = Field(None, max_length=200)
    refund_method: str = "contanti"
    lines: list[LineIn]
    rt_result: dict | None = None


@router.post("/casse/{reg_id}/resi")
def refund(reg_id: uuid.UUID, body: ReturnIn, ctx: TenantContext = Depends(cashier)):
    reg = _register(ctx, reg_id)
    d = pos.create_return(ctx.db, reg, ctx.user.id, _dump(body))
    return pos.receipt_out(ctx.db, d)


@router.get("/scontrini")
def list_receipts(register_id: uuid.UUID | None = None, session_id: uuid.UUID | None = None, day: date | None = None,
                  q: str | None = None, limit: int = Query(50, le=200), ctx: TenantContext = Depends(cashier)):
    stmt = (select(Document).where(Document.register_id.is_not(None)).options(selectinload(Document.lines))
            .order_by(Document.created_at.desc()).limit(limit))
    if register_id:
        stmt = stmt.where(Document.register_id == register_id)
    if session_id:
        stmt = stmt.where(Document.pos_session_id == session_id)
    if day:
        stmt = stmt.where(Document.doc_date == day)
    if q and q.strip():
        t = q.strip()
        if t.isdigit():
            stmt = stmt.where(Document.number == int(t))
    rows = ctx.db.scalars(stmt).all()
    return [{"id": str(d.id), "doc_type": d.doc_type, "number": d.number, "date": s(d.doc_date), "created_at": s(d.created_at),
             "total": s(d.total), "status": d.status, "lines": len(d.lines), "party_name": ctx.db.get(Party, d.party_id).name} for d in rows]


@router.get("/scontrini/{doc_id}")
def get_receipt(doc_id: uuid.UUID, ctx: TenantContext = Depends(cashier)):
    d = _get(ctx, Document, doc_id)
    if d.register_id is None:
        raise HTTPException(404, "Non è un documento della cassa")
    return pos.receipt_out(ctx.db, d)


class FiscalRetryIn(BaseModel):
    force: bool = False


@router.post("/scontrini/{doc_id}/fiscale")
def retry_fiscal(doc_id: uuid.UUID, body: FiscalRetryIn, ctx: TenantContext = Depends(cashier)):
    """Ripete l'invio del documento commerciale al registratore (dopo un errore, es. carta finita)."""
    from app.periferiche import service as per
    from app.periferiche.models import DeviceJob
    d = _get(ctx, Document, doc_id)
    if d.register_id is None or d.doc_type not in ("SCO", "RSO"):
        raise HTTPException(422, "Non è uno scontrino della cassa")
    if ((d.fiscal or {}).get("rt") or {}).get("status") == "emesso":
        raise HTTPException(409, "Il documento commerciale è già stato emesso")
    last = ctx.db.scalar(select(DeviceJob).where(DeviceJob.document_id == d.id).order_by(DeviceJob.created_at.desc()))
    if last is not None:
        per.retry(ctx.db, last, ctx.user.id, body.force)
    else:
        per.fiscalize(ctx.db, ctx.db.get(PosRegister, d.register_id), d, ctx.user.id)
    ctx.db.flush()
    return pos.receipt_out(ctx.db, d)


@router.post("/scontrini/{doc_id}/stampa")
def print_courtesy(doc_id: uuid.UUID, ctx: TenantContext = Depends(cashier)):
    """Ricevuta di cortesia sulla stampante termica della cassa."""
    from app.core.models import Company
    from app.periferiche import service as per
    d = _get(ctx, Document, doc_id)
    reg = ctx.db.get(PosRegister, d.register_id) if d.register_id else None
    dev = per.register_device(ctx.db, reg, "printer") if reg else None
    if dev is None:
        raise HTTPException(422, "La cassa non ha una stampante di ricevute")
    pays = list(ctx.db.scalars(select(PosPayment).where(PosPayment.document_id == d.id)))
    co = ctx.db.scalar(select(Company).order_by(Company.name))
    j = per.enqueue(ctx.db, dev, "print.text", per.text_receipt(d, co, pays, reg.name), document_id=d.id, user_id=ctx.user.id)
    return {"job_id": str(j.id)}
