"""API scadenzario: /api/scadenzario/...  (modulo "scadenzario")."""

import io
import uuid
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import selectinload

from app.anagrafiche.models import Party
from app.core.deps import TenantContext, require_module
from app.documenti.models import Document
from app.saas.service import audit
from app.scadenzario import liquidity, reminders
from app.scadenzario import service as due
from app.scadenzario.models import FinancialAccount, Installment, InstallmentPayment, LiquiditySnapshot, PaymentReminder

router = APIRouter(prefix="/api/scadenzario", tags=["scadenzario"])
reader_base = require_module("scadenzario")


def reader(ctx: TenantContext = Depends(reader_base)) -> TenantContext:
    if ctx.user.role in ("cassa", "magazzino", "agente"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può consultare lo scadenzario")
    return ctx


def writer(ctx: TenantContext = Depends(reader)) -> TenantContext:
    if ctx.user.role == "vendite":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Il tuo ruolo non può registrare incassi e pagamenti")
    return ctx


def s(v):
    if isinstance(v, (Decimal, uuid.UUID)):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _xlsx(data: bytes, name: str) -> StreamingResponse:
    return StreamingResponse(io.BytesIO(data), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ====================================================================== conti


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field("banca", pattern="^(cassa|banca|carta|altro)$")
    iban: str | None = None
    opening_balance: Decimal = Decimal(0)
    opening_date: date | None = None
    is_default: bool = False
    active: bool = True


def account_out(ctx: TenantContext, a: FinancialAccount) -> dict:
    return {"id": str(a.id), "name": a.name, "kind": a.kind, "iban": a.iban, "opening_balance": s(a.opening_balance),
            "opening_date": s(a.opening_date), "is_default": a.is_default, "active": a.active,
            "balance": s(due.account_balance(ctx.db, a, date.today()))}


@router.get("/conti")
def list_accounts(ctx: TenantContext = Depends(reader)):
    return [account_out(ctx, a) for a in ctx.db.scalars(select(FinancialAccount).order_by(FinancialAccount.active.desc(), FinancialAccount.kind, FinancialAccount.name))]


def _save_account(ctx: TenantContext, a: FinancialAccount, body: AccountIn) -> dict:
    for k, v in body.model_dump().items():
        setattr(a, k, v)
    a.iban = (body.iban or "").replace(" ", "").upper() or None
    if body.is_default:
        for other in ctx.db.scalars(select(FinancialAccount).where(FinancialAccount.id != a.id, FinancialAccount.is_default)):
            other.is_default = False
    ctx.db.flush()
    return account_out(ctx, a)


@router.post("/conti", status_code=201)
def create_account(body: AccountIn, ctx: TenantContext = Depends(writer)):
    a = FinancialAccount(tenant_id=ctx.tenant_id)
    ctx.db.add(a)
    return _save_account(ctx, a, body)


@router.put("/conti/{aid}")
def update_account(aid: uuid.UUID, body: AccountIn, ctx: TenantContext = Depends(writer)):
    a = ctx.db.get(FinancialAccount, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conto non trovato")
    return _save_account(ctx, a, body)


@router.delete("/conti/{aid}")
def delete_account(aid: uuid.UUID, ctx: TenantContext = Depends(writer)):
    a = ctx.db.get(FinancialAccount, aid)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conto non trovato")
    if ctx.db.scalar(select(InstallmentPayment.id).where(InstallmentPayment.account_id == a.id).limit(1)):
        a.active = False
        return {"ok": True, "deactivated": True}
    ctx.db.delete(a)
    return {"ok": True}


# ====================================================================== scadenze


def inst_out(i: Installment, names: dict, docs: dict, full: bool = False) -> dict:
    today = date.today()
    res = due.residual(i)
    d = docs.get(i.document_id)
    out = {
        "id": str(i.id), "direction": i.direction, "party_id": s(i.party_id), "party_name": names.get(i.party_id),
        "document_id": s(i.document_id), "document": {"doc_type": d.doc_type, "direction": d.direction, "number": d.number,
                                                       "external_number": d.external_number} if d else None,
        "seq": i.seq, "total_seq": i.total_seq, "description": i.description, "issue_date": s(i.issue_date),
        "due_date": s(i.due_date), "amount": s(i.amount), "paid_amount": s(i.paid_amount), "residual": s(res),
        "method": i.method, "method_label": due.METHODS.get(i.method or "", i.method), "account_id": s(i.account_id),
        "status": i.status, "unpaid": i.unpaid, "overdue": i.status != "pagata" and i.due_date < today and res != 0,
        "days_late": (today - i.due_date).days if i.status != "pagata" and i.due_date < today else 0,
        "reminder_level": i.reminder_level, "notes": i.notes, "manual": i.document_id is None,
    }
    if full:
        out["payments"] = [{"id": str(p.id), "pay_date": s(p.pay_date), "amount": s(p.amount), "account_id": s(p.account_id),
                            "method": p.method, "notes": p.notes} for p in i.payments]
    return out


def _filtered(ctx: TenantContext, direzione, stato, party_id, date_from, date_to, method, account_id, q):
    stmt = select(Installment)
    today = date.today()
    if direzione:
        stmt = stmt.where(Installment.direction == direzione)
    if stato == "aperte":
        stmt = stmt.where(Installment.status != "pagata")
    elif stato == "scadute":
        stmt = stmt.where(Installment.status != "pagata", Installment.due_date < today)
    elif stato == "pagate":
        stmt = stmt.where(Installment.status == "pagata")
    elif stato == "insolute":
        stmt = stmt.where(Installment.unpaid.is_(True), Installment.status != "pagata")
    if party_id:
        stmt = stmt.where(Installment.party_id == party_id)
    if date_from:
        stmt = stmt.where(Installment.due_date >= date_from)
    if date_to:
        stmt = stmt.where(Installment.due_date <= date_to)
    if method:
        stmt = stmt.where(Installment.method == method)
    if account_id:
        stmt = stmt.where(Installment.account_id == account_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Installment.description.ilike(like), Installment.notes.ilike(like),
                              Installment.party_id.in_(select(Party.id).where(Party.name.ilike(like)))))
    return stmt


@router.get("/scadenze")
def list_installments(direzione: str | None = Query(None, pattern="^(attiva|passiva)$"),
                      stato: str = Query("aperte", pattern="^(aperte|scadute|pagate|insolute|tutte)$"),
                      party_id: uuid.UUID | None = None, date_from: date | None = None, date_to: date | None = None,
                      method: str | None = None, account_id: uuid.UUID | None = None, q: str | None = None,
                      page: int = Query(1, ge=1), page_size: int = Query(100, le=500), ctx: TenantContext = Depends(reader)):
    db = ctx.db
    stmt = _filtered(ctx, direzione, stato, party_id, date_from, date_to, method, account_id, q)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(Installment.due_date, Installment.created_at).offset((page - 1) * page_size).limit(page_size)).all()
    names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_({i.party_id for i in rows if i.party_id})))} if rows else {}
    docs = {d.id: d for d in db.scalars(select(Document).where(Document.id.in_({i.document_id for i in rows if i.document_id})))} if rows else {}
    # totali in testa: sempre sull'insieme aperto (indipendenti dal filtro di stato)
    today = date.today()
    res = Installment.amount - Installment.paid_amount
    tot_rows = db.execute(select(Installment.direction, func.sum(res), func.sum(case((Installment.due_date < today, res), else_=0)))
                          .where(Installment.status != "pagata").group_by(Installment.direction)).all()
    t = {"attiva": [Decimal(0), Decimal(0)], "passiva": [Decimal(0), Decimal(0)]}
    for direction, amt, late in tot_rows:
        t[direction] = [Decimal(amt or 0), Decimal(late or 0)]
    return {
        "total": total, "page": page, "page_size": page_size,
        "totals": {"receivable": s(t["attiva"][0]), "receivable_overdue": s(t["attiva"][1]), "payable": s(t["passiva"][0]),
                   "payable_overdue": s(t["passiva"][1]), "balance": s(t["attiva"][0] - t["passiva"][0])},
        "filtered_residual": s(sum((due.residual(i) * (1 if i.direction == "attiva" else -1) for i in rows), Decimal(0))),
        "rows": [inst_out(i, names, docs) for i in rows],
    }


@router.get("/scadenze/excel")
def export_installments(direzione: str | None = None, stato: str = "aperte", party_id: uuid.UUID | None = None,
                        date_from: date | None = None, date_to: date | None = None, method: str | None = None,
                        account_id: uuid.UUID | None = None, q: str | None = None, ctx: TenantContext = Depends(reader)):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    db = ctx.db
    rows = db.scalars(_filtered(ctx, direzione, stato, party_id, date_from, date_to, method, account_id, q).order_by(Installment.due_date)).all()
    names = {p.id: p.name for p in db.scalars(select(Party).where(Party.id.in_({i.party_id for i in rows if i.party_id})))} if rows else {}
    wb = Workbook()
    ws = wb.active
    ws.title = "Scadenze"
    header = ["Tipo", "Scadenza", "Soggetto", "Descrizione", "Modalità", "Importo", "Pagato", "Residuo", "Stato", "Insoluta"]
    for c, h in enumerate(header, start=1):
        cell = ws.cell(row=1, column=c, value=h)
        cell.font, cell.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="2340A8")
    for r, i in enumerate(rows, start=2):
        for c, v in enumerate(["Da incassare" if i.direction == "attiva" else "Da pagare", i.due_date, names.get(i.party_id, ""),
                               i.description, due.METHODS.get(i.method or "", i.method or ""), float(i.amount), float(i.paid_amount),
                               float(due.residual(i)), i.status, "sì" if i.unpaid else ""], start=1):
            cell = ws.cell(row=r, column=c, value=v)
            if c == 2:
                cell.number_format = "DD/MM/YYYY"
            if c in (6, 7, 8):
                cell.number_format = "#,##0.00"
    for col, w in zip("ABCDEFGHIJ", (13, 12, 30, 50, 14, 12, 12, 12, 10, 8)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    return _xlsx(buf.getvalue(), f"scadenzario-{date.today().isoformat()}.xlsx")


@router.get("/scadenze/{iid}")
def get_installment(iid: uuid.UUID, ctx: TenantContext = Depends(reader)):
    i = ctx.db.scalar(select(Installment).where(Installment.id == iid).options(selectinload(Installment.payments)))
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scadenza non trovata")
    names = {i.party_id: ctx.db.get(Party, i.party_id).name} if i.party_id else {}
    docs = {i.document_id: ctx.db.get(Document, i.document_id)} if i.document_id else {}
    return inst_out(i, names, docs, full=True)


class ManualIn(BaseModel):
    direction: str = Field(pattern="^(attiva|passiva)$")
    party_id: uuid.UUID | None = None
    description: str = Field(min_length=1, max_length=200)
    due_date: date
    amount: Decimal = Field(gt=0)
    method: str | None = None
    account_id: uuid.UUID | None = None
    notes: str | None = None
    repeat_months: int = Field(0, ge=0, le=12)  # 0 = una sola; 1 = ogni mese; 3 = ogni trimestre...
    repeat_count: int = Field(1, ge=1, le=120)


@router.post("/scadenze", status_code=201)
def create_manual(body: ManualIn, ctx: TenantContext = Depends(writer)):
    """Scadenze inserite a mano (affitti, F24, rate di finanziamento, stipendi), anche ripetute."""
    if body.party_id and ctx.db.get(Party, body.party_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Soggetto inesistente")
    count = body.repeat_count if body.repeat_months else 1
    out = []
    for n in range(count):
        when = body.due_date + relativedelta(months=body.repeat_months * n)
        i = Installment(tenant_id=ctx.tenant_id, direction=body.direction, party_id=body.party_id, document_id=None,
                        seq=n + 1, total_seq=count, description=body.description + (f" – {n + 1}/{count}" if count > 1 else ""),
                        issue_date=min(date.today(), when), due_date=when, amount=body.amount, paid_amount=Decimal(0),
                        method=body.method, account_id=body.account_id, notes=body.notes, status="aperta", created_by=ctx.user.id)
        ctx.db.add(i)
        out.append(i)
    ctx.db.flush()
    return {"created": len(out), "ids": [str(i.id) for i in out]}


class EditIn(BaseModel):
    due_date: date
    method: str | None = None
    account_id: uuid.UUID | None = None
    notes: str | None = None
    description: str | None = None
    amount: Decimal | None = None


@router.put("/scadenze/{iid}")
def update_installment(iid: uuid.UUID, body: EditIn, ctx: TenantContext = Depends(writer)):
    i = ctx.db.get(Installment, iid)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scadenza non trovata")
    i.due_date, i.method, i.account_id, i.notes = body.due_date, body.method, body.account_id, body.notes
    if i.document_id is None:  # le scadenze manuali si possono modificare del tutto
        if body.description:
            i.description = body.description
        if body.amount is not None:
            if body.amount <= 0 or abs(body.amount) < abs(Decimal(i.paid_amount)):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Importo non valido o inferiore a quanto già pagato")
            i.amount = body.amount
            due.refresh(ctx.db, i)
    return get_installment(iid, ctx)


@router.delete("/scadenze/{iid}")
def delete_installment(iid: uuid.UUID, ctx: TenantContext = Depends(writer)):
    i = ctx.db.get(Installment, iid)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scadenza non trovata")
    if i.document_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Le scadenze delle fatture si eliminano annullando la fattura")
    if Decimal(i.paid_amount) != 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "Elimina prima i pagamenti registrati")
    ctx.db.delete(i)
    return {"ok": True}


class PayIn(BaseModel):
    pay_date: date
    amount: Decimal | None = None  # vuoto = tutto il residuo
    account_id: uuid.UUID | None = None
    method: str | None = None
    notes: str | None = None


@router.post("/scadenze/{iid}/pagamenti", status_code=201)
def add_payment(iid: uuid.UUID, body: PayIn, ctx: TenantContext = Depends(writer)):
    i = ctx.db.scalar(select(Installment).where(Installment.id == iid).options(selectinload(Installment.payments)))
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scadenza non trovata")
    if body.pay_date > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Non si registrano incassi con data futura")
    due.pay(ctx.db, i, pay_date=body.pay_date, amount=body.amount, account_id=body.account_id, method=body.method,
            notes=body.notes, user_id=ctx.user.id)
    audit(ctx.db, "installment", "incasso" if i.direction == "attiva" else "pagamento", i.id, tenant_id=ctx.tenant_id,
          user_id=ctx.user.id, after={"data": body.pay_date.isoformat(), "importo": str(body.amount or "residuo")})
    return get_installment(iid, ctx)


class MultiPayIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1)
    pay_date: date
    account_id: uuid.UUID | None = None


@router.post("/incasso-multiplo")
def pay_many(body: MultiPayIn, ctx: TenantContext = Depends(writer)):
    """Chiude per intero più scadenze (es. distinta Ri.Ba. accreditata, bonifici della giornata)."""
    if body.pay_date > date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Non si registrano incassi con data futura")
    n = 0
    total = Decimal(0)
    for iid in body.ids:
        i = ctx.db.scalar(select(Installment).where(Installment.id == iid).options(selectinload(Installment.payments)))
        if i is None or i.status == "pagata":
            continue
        total += due.residual(i)
        due.pay(ctx.db, i, pay_date=max(body.pay_date, i.issue_date), account_id=body.account_id, user_id=ctx.user.id)
        n += 1
    return {"paid": n, "total": s(total)}


@router.delete("/pagamenti/{pid}")
def remove_payment(pid: uuid.UUID, ctx: TenantContext = Depends(writer)):
    p = ctx.db.get(InstallmentPayment, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pagamento non trovato")
    iid = p.installment_id
    due.delete_payment(ctx.db, p)
    audit(ctx.db, "installment", "storno_pagamento", iid, tenant_id=ctx.tenant_id, user_id=ctx.user.id)
    return get_installment(iid, ctx)


class UnpaidIn(BaseModel):
    unpaid: bool


@router.post("/scadenze/{iid}/insoluta")
def set_unpaid(iid: uuid.UUID, body: UnpaidIn, ctx: TenantContext = Depends(writer)):
    """Insoluto (es. Ri.Ba. respinta): se c'era un incasso lo storna e la scadenza torna aperta, segnata come insoluta."""
    i = ctx.db.scalar(select(Installment).where(Installment.id == iid).options(selectinload(Installment.payments)))
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Scadenza non trovata")
    if body.unpaid and i.payments:
        for p in list(i.payments):
            i.payments.remove(p)
        ctx.db.flush()
        due.refresh(ctx.db, i)
    i.unpaid = body.unpaid
    return get_installment(iid, ctx)


@router.get("/soggetti/{party_id}/situazione")
def party_situation(party_id: uuid.UUID, ctx: TenantContext = Depends(reader)):
    return {k: s(v) for k, v in {**due.party_position(ctx.db, party_id, "attiva"),
                                 **{f"payable_{k}": v for k, v in due.party_position(ctx.db, party_id, "passiva").items()}}.items()}


# ====================================================================== liquidità


@router.get("/liquidita")
def get_liquidity(as_of: date | None = None, weeks: int = Query(8, ge=1, le=26), months: int = Query(6, ge=1, le=24),
                  ctx: TenantContext = Depends(reader)):
    return liquidity.snapshot(ctx.db, as_of or date.today(), weeks, months)


@router.get("/liquidita/excel")
def liquidity_excel(as_of: date | None = None, ctx: TenantContext = Depends(reader)):
    on = as_of or date.today()
    return _xlsx(liquidity.to_excel(liquidity.snapshot(ctx.db, on), "Fotografia della liquidità"), f"liquidita-{on.isoformat()}.xlsx")


class SnapshotIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    as_of: date


@router.get("/fotografie")
def list_snapshots(ctx: TenantContext = Depends(reader)):
    return [{"id": str(x.id), "name": x.name, "as_of": s(x.as_of), "created_at": x.created_at.isoformat(),
             "liquidity": x.data.get("liquidity"), "net_position": x.data.get("net_position")}
            for x in ctx.db.scalars(select(LiquiditySnapshot).order_by(LiquiditySnapshot.as_of.desc(), LiquiditySnapshot.created_at.desc()))]


@router.post("/fotografie", status_code=201)
def save_snapshot(body: SnapshotIn, ctx: TenantContext = Depends(writer)):
    x = LiquiditySnapshot(tenant_id=ctx.tenant_id, name=body.name, as_of=body.as_of, created_by=ctx.user.id,
                          data=liquidity.snapshot(ctx.db, body.as_of))
    ctx.db.add(x)
    ctx.db.flush()
    return {"id": str(x.id), "name": x.name, "as_of": s(x.as_of), "data": x.data}


@router.get("/fotografie/{sid}")
def get_snapshot(sid: uuid.UUID, ctx: TenantContext = Depends(reader)):
    x = ctx.db.get(LiquiditySnapshot, sid)
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fotografia non trovata")
    return {"id": str(x.id), "name": x.name, "as_of": s(x.as_of), "created_at": x.created_at.isoformat(), "data": x.data}


@router.get("/fotografie/{sid}/excel")
def snapshot_excel(sid: uuid.UUID, ctx: TenantContext = Depends(reader)):
    x = ctx.db.get(LiquiditySnapshot, sid)
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fotografia non trovata")
    return _xlsx(liquidity.to_excel(x.data, f"Fotografia «{x.name}»"), f"fotografia-{x.as_of.isoformat()}.xlsx")


@router.delete("/fotografie/{sid}")
def delete_snapshot(sid: uuid.UUID, ctx: TenantContext = Depends(writer)):
    x = ctx.db.get(LiquiditySnapshot, sid)
    if x is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fotografia non trovata")
    ctx.db.delete(x)
    return {"ok": True}


# ====================================================================== solleciti


@router.get("/solleciti/impostazioni")
def get_reminder_settings(ctx: TenantContext = Depends(reader)):
    return due.settings(ctx.db, ctx.tenant_id)


class TemplateIn(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)


class ReminderSettingsIn(BaseModel):
    auto: bool = False
    days: list[int] = Field(min_length=3, max_length=3)
    block_overdue_days: int | None = Field(None, ge=1)
    templates: dict[str, TemplateIn]
    whatsapp: str


@router.put("/solleciti/impostazioni")
def put_reminder_settings(body: ReminderSettingsIn, ctx: TenantContext = Depends(writer)):
    if sorted(body.days) != body.days or body.days[0] < 1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "I giorni dei tre livelli devono essere crescenti")
    return due.save_settings(ctx.db, ctx.tenant_id, body.model_dump())


@router.get("/solleciti/proposta")
def reminder_proposal(ctx: TenantContext = Depends(reader)):
    return reminders.proposal(ctx.db, ctx.tenant_id, date.today())


class SendIn(BaseModel):
    party_ids: list[uuid.UUID] = Field(min_length=1)
    level: int | None = Field(None, ge=1, le=3)  # vuoto = livello successivo per ogni cliente


@router.post("/solleciti/invia")
def send_reminders(body: SendIn, ctx: TenantContext = Depends(writer)):
    out = []
    for pid in body.party_ids:
        r = reminders.send(ctx.db, ctx.tenant_id, pid, body.level, date.today(), ctx.user.id)
        p = ctx.db.get(Party, pid)
        out.append({"party_id": str(pid), "name": p.name if p else "", "status": r.status, "error": r.error, "level": r.level})
    return {"results": out, "sent": sum(1 for r in out if r["status"] == "inviato")}


class WaIn(BaseModel):
    party_id: uuid.UUID
    level: int | None = Field(None, ge=1, le=3)


@router.post("/solleciti/whatsapp")
def reminder_whatsapp(body: WaIn, ctx: TenantContext = Depends(writer)):
    return reminders.whatsapp(ctx.db, ctx.tenant_id, body.party_id, body.level, date.today(), ctx.user.id)


@router.post("/solleciti/anteprima")
def reminder_preview(body: WaIn, ctx: TenantContext = Depends(reader)):
    rows = reminders.overdue_by_party(ctx.db, date.today(), [body.party_id]).get(body.party_id, [])
    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nessuna scadenza scaduta")
    level = body.level or min(max(max(i.reminder_level for i in rows) + 1, 1), 3)
    tpl = due.settings(ctx.db, ctx.tenant_id)["templates"][str(level)]
    c = reminders._context(ctx.db, ctx.db.get(Party, body.party_id), rows, date.today())
    return {"level": level, "subject": reminders.render(tpl["subject"], c), "html": reminders.render(tpl["body"], c)}


@router.get("/solleciti/storico")
def reminder_history(party_id: uuid.UUID | None = None, ctx: TenantContext = Depends(reader)):
    stmt = select(PaymentReminder)
    if party_id:
        stmt = stmt.where(PaymentReminder.party_id == party_id)
    rows = ctx.db.scalars(stmt.order_by(PaymentReminder.sent_at.desc()).limit(200)).all()
    names = {p.id: p.name for p in ctx.db.scalars(select(Party).where(Party.id.in_({r.party_id for r in rows})))} if rows else {}
    return [{"id": str(r.id), "party_id": str(r.party_id), "name": names.get(r.party_id), "level": r.level,
             "level_label": reminders.LEVELS.get(r.level), "channel": r.channel, "recipients": r.recipients, "total": s(r.total),
             "status": r.status, "error": r.error, "automatic": r.automatic, "sent_at": r.sent_at.isoformat()} for r in rows]
