"""API buoni regalo e pacchetti di sedute: /api/prepagati/... (modulo «pos», pacchetto SALONE)."""

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.anagrafiche.models import Party
from app.core.deps import TenantContext, require_module
from app.prepagati import service as svc
from app.prepagati.models import ClientPackage, GiftVoucher, ServicePackage

router = APIRouter(prefix="/api/prepagati", tags=["prepagati"])
operator = require_module("pos")


def writer(ctx: TenantContext = Depends(operator)) -> TenantContext:
    return ctx


def admin(ctx: TenantContext = Depends(operator)) -> TenantContext:
    if ctx.user.role != "amministratore":
        raise HTTPException(403, "Solo l'amministratore")
    return ctx


class PaymentIn(BaseModel):
    method: str
    amount: Decimal = Field(ge=0)


def _pays(ps: list[PaymentIn]) -> list[dict]:
    return [{"method": p.method, "amount": str(p.amount)} for p in ps]


def _sale_out(ctx, d, change) -> dict:
    from app.pos import service as pos
    return {"receipt": pos.receipt_out(ctx.db, d), "change": str(change)}


# ------------------------------------------------------------------------------------------------------------ buoni
class VoucherIn(BaseModel):
    client_uuid: uuid.UUID
    kind: Literal["importo", "servizio"] = "importo"
    amount: Decimal | None = Field(None, gt=0, le=5000)
    service_id: uuid.UUID | None = None
    purchaser_id: uuid.UUID | None = None
    beneficiary_id: uuid.UUID | None = None  # chi lo riceve, se è già cliente: il buono va nella sua scheda
    beneficiary_name: str | None = Field(None, max_length=120)
    message: str | None = Field(None, max_length=300)
    months: int | None = Field(12, ge=1, le=60)  # vuoto = senza scadenza
    register_id: uuid.UUID | None = None
    payments: list[PaymentIn] = Field(min_length=1)


@router.get("/buoni")
def list_vouchers(q: str | None = None, stato: str | None = None, limit: int = Query(100, le=500), ctx: TenantContext = Depends(operator)):
    stmt = select(GiftVoucher).order_by(GiftVoucher.created_at.desc()).limit(limit)
    if q and q.strip():
        t = q.strip()
        n = svc.normalize_code(t)
        stmt = stmt.outerjoin(Party, Party.id == GiftVoucher.purchaser_party_id).where(or_(
            GiftVoucher.code.ilike(f"%{t}%"), GiftVoucher.beneficiary_name.ilike(f"%{t}%"), Party.name.ilike(f"%{t}%"),
            GiftVoucher.code.ilike(f"%{n[:2]}-{n[2:6]}%") if len(n) >= 6 else GiftVoucher.code.ilike(f"%{t}%")))
    out = [svc.voucher_out(ctx.db, v) for v in ctx.db.scalars(stmt)]
    return [v for v in out if not stato or v["status"] == stato]


@router.post("/buoni", status_code=201)
def sell_voucher(body: VoucherIn, ctx: TenantContext = Depends(writer)):
    """Vendita di un buono regalo: scontrino per l'intero valore (buono monouso)."""
    v, d, change = svc.sell_voucher(ctx.db, ctx.tenant_id, ctx.user.id, kind=body.kind, amount=body.amount, service_id=body.service_id,
                                    purchaser_id=body.purchaser_id, beneficiary_name=body.beneficiary_name, message=body.message,
                                    months=body.months, payments=_pays(body.payments), register_id=body.register_id,
                                    client_uuid=body.client_uuid, beneficiary_id=body.beneficiary_id)
    return {"voucher": svc.voucher_out(ctx.db, v), **_sale_out(ctx, d, change)}


class SettingsIn(BaseModel):
    voucher_mode: Literal["multiuso", "monouso"]


@router.get("/impostazioni")
def get_settings(ctx: TenantContext = Depends(operator)):
    return svc.settings(ctx.db, ctx.tenant_id)


@router.put("/impostazioni")
def put_settings(body: SettingsIn, ctx: TenantContext = Depends(admin)):
    """Buono multiuso (scontrino all'utilizzo) o monouso (scontrino alla vendita): vale per i buoni venduti da ora."""
    return svc.save_settings(ctx.db, ctx.tenant_id, body.model_dump())


@router.get("/buoni/codice/{code}")
def voucher_by_code(code: str, ctx: TenantContext = Depends(operator)):
    return svc.voucher_out(ctx.db, svc.find_voucher(ctx.db, code), moves=True)


@router.get("/buoni/{voucher_id}")
def get_voucher(voucher_id: uuid.UUID, ctx: TenantContext = Depends(operator)):
    v = ctx.db.get(GiftVoucher, voucher_id)
    if v is None:
        raise HTTPException(404, "Buono non trovato")
    return svc.voucher_out(ctx.db, v, moves=True)


class CancelIn(BaseModel):
    note: str | None = Field(None, max_length=200)


@router.post("/buoni/{voucher_id}/annulla")
def cancel_voucher(voucher_id: uuid.UUID, body: CancelIn, ctx: TenantContext = Depends(admin)):
    v = ctx.db.get(GiftVoucher, voucher_id)
    if v is None:
        raise HTTPException(404, "Buono non trovato")
    svc.cancel_voucher(ctx.db, v, ctx.user.id, body.note)
    return svc.voucher_out(ctx.db, v, moves=True)


@router.get("/buoni/{voucher_id}/stampa")
def voucher_lines(voucher_id: uuid.UUID, ctx: TenantContext = Depends(operator)):
    """Righe del buono per la stampa dal computer (stessa grafica della termica)."""
    from app.pos import receipts
    v = ctx.db.get(GiftVoucher, voucher_id)
    if v is None:
        raise HTTPException(404, "Buono non trovato")
    return receipts.for_screen(svc.voucher_print(ctx.db, v))


class PrintIn(BaseModel):
    register_id: uuid.UUID | None = None


@router.post("/buoni/{voucher_id}/stampa")
def print_voucher(voucher_id: uuid.UUID, body: PrintIn, ctx: TenantContext = Depends(operator)):
    """Il buono sulla stampante termica della cassa."""
    from app.periferiche import service as per
    v = ctx.db.get(GiftVoucher, voucher_id)
    if v is None:
        raise HTTPException(404, "Buono non trovato")
    reg = svc._register(ctx.db, ctx.tenant_id, body.register_id)
    dev = per.register_device(ctx.db, reg, "printer")
    if dev is None:
        raise HTTPException(422, "La cassa non ha una stampante di ricevute: stampa il buono dal computer")
    j = per.enqueue(ctx.db, dev, "print.text", svc.voucher_print(ctx.db, v), user_id=ctx.user.id)
    return {"job_id": str(j.id), "device": dev.name}


# --------------------------------------------------------------------------------------------------------- pacchetti
class PackageItemIn(BaseModel):
    service_id: uuid.UUID
    sessions: int = Field(ge=1, le=100)


class PackageIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    price: Decimal = Field(gt=0, le=20000)
    items: list[PackageItemIn] = Field(min_length=1, max_length=10)
    validity_days: int | None = Field(None, ge=1, le=1100)
    min_days: int | None = Field(None, ge=1, le=120)
    description: str | None = Field(None, max_length=300)
    active: bool = True
    sort_order: int = 0


@router.get("/pacchetti")
def list_packages(ctx: TenantContext = Depends(operator)):
    return [svc.package_out(ctx.db, p) for p in ctx.db.scalars(select(ServicePackage).order_by(ServicePackage.sort_order, ServicePackage.name))]


@router.post("/pacchetti", status_code=201)
def create_package(body: PackageIn, ctx: TenantContext = Depends(admin)):
    return svc.package_out(ctx.db, svc.save_package(ctx.db, ctx.tenant_id, body.model_dump(mode="json")))


@router.put("/pacchetti/{package_id}")
def update_package(package_id: uuid.UUID, body: PackageIn, ctx: TenantContext = Depends(admin)):
    return svc.package_out(ctx.db, svc.save_package(ctx.db, ctx.tenant_id, body.model_dump(mode="json"), package_id))


class SellPackageIn(BaseModel):
    client_uuid: uuid.UUID
    party_id: uuid.UUID
    register_id: uuid.UUID | None = None
    payments: list[PaymentIn] = Field(min_length=1)


@router.post("/pacchetti/{package_id}/vendi", status_code=201)
def sell_package(package_id: uuid.UUID, body: SellPackageIn, ctx: TenantContext = Depends(writer)):
    """Vendita del pacchetto alla cliente: scontrino per l'intero prezzo; le sedute si scalano agli incassi."""
    cp, d, change = svc.sell_package(ctx.db, ctx.tenant_id, ctx.user.id, package_id=package_id, party_id=body.party_id,
                                     payments=_pays(body.payments), register_id=body.register_id, client_uuid=body.client_uuid)
    return {"package": svc.client_package_out(ctx.db, cp), **_sale_out(ctx, d, change)}


@router.get("/venduti")
def sold_packages(stato: str | None = None, party_id: uuid.UUID | None = None, ctx: TenantContext = Depends(operator)):
    stmt = select(ClientPackage).order_by(ClientPackage.created_at.desc()).limit(300)
    if party_id:
        stmt = stmt.where(ClientPackage.party_id == party_id)
    cps = list(ctx.db.scalars(stmt))
    used = svc.used_counts(ctx.db, [c.id for c in cps])
    out = [svc.client_package_out(ctx.db, c, used) for c in cps]
    return [c for c in out if not stato or c["status"] == stato]


@router.post("/venduti/{cp_id}/annulla")
def cancel_sold(cp_id: uuid.UUID, ctx: TenantContext = Depends(admin)):
    cp = ctx.db.get(ClientPackage, cp_id)
    if cp is None:
        raise HTTPException(404, "Pacchetto non trovato")
    svc.cancel_package(ctx.db, cp)
    return svc.client_package_out(ctx.db, cp)


@router.get("/clienti/{party_id}")
def client_prepaid(party_id: uuid.UUID, ctx: TenantContext = Depends(operator)):
    """Per la scheda cliente: pacchetti (con sedute rimaste) e buoni comprati da lei."""
    cps = list(ctx.db.scalars(select(ClientPackage).where(ClientPackage.party_id == party_id).order_by(ClientPackage.created_at.desc())))
    used = svc.used_counts(ctx.db, [c.id for c in cps])
    vs = ctx.db.scalars(select(GiftVoucher).where(GiftVoucher.purchaser_party_id == party_id).order_by(GiftVoucher.created_at.desc()))
    rec = ctx.db.scalars(select(GiftVoucher).where(GiftVoucher.beneficiary_party_id == party_id).order_by(GiftVoucher.created_at.desc()))
    return {"packages": [svc.client_package_out(ctx.db, c, used) for c in cps], "vouchers": [svc.voucher_out(ctx.db, v) for v in vs],
            "received": [svc.voucher_out(ctx.db, v) for v in rec]}
