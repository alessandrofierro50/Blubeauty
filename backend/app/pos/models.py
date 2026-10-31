"""Vendita al banco (pacchetto Plus): reparti, casse, aperture/chiusure, movimenti di cassa e incassi.

Gli scontrini sono documenti di vendita (doc_type "SCO", reso "RSO") con prezzi IVA inclusa."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType

MONEY = Numeric(14, 2)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class PosDepartment(Base):
    """Reparto: vendite a importo libero (ortofrutta, panetteria…) e raggruppamento dei corrispettivi sul registratore."""

    __tablename__ = "pos_departments"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(60))
    vat_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vat_rates.id", ondelete="SET NULL"))
    rt_department: Mapped[int | None] = mapped_column(Integer)  # numero reparto sul registratore telematico
    color: Mapped[str | None] = mapped_column(String(20))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PosRegister(Base):
    """Cassa / postazione: punto vendita, magazzino da scaricare, listino, modalità e periferiche."""

    __tablename__ = "pos_registers"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(60))
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_lists.id", ondelete="SET NULL"))
    mode: Mapped[str] = mapped_column(String(12), default="negozio")  # negozio (touch) | supermercato (tastiera)
    cash_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id", ondelete="SET NULL"))
    card_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id", ondelete="SET NULL"))
    quick_keys: Mapped[list] = mapped_column(JSONType, default=list)  # [{"type": "item"|"department", "id": ..., "label": ...}]
    devices: Mapped[dict] = mapped_column(JSONType, default=dict)  # registratore, stampante, display (fase 3c)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)  # es. chiedi codice lotteria, stampa automatica
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PosSession(Base):
    """Apertura di cassa: dal fondo iniziale alla chiusura con conteggio del contante."""

    __tablename__ = "pos_sessions"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    register_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_registers.id", ondelete="RESTRICT"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(8), default="aperta")  # aperta | chiusa
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    opening_float: Mapped[Decimal] = mapped_column(MONEY, default=0)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    expected_cash: Mapped[Decimal | None] = mapped_column(MONEY)
    counted_cash: Mapped[Decimal | None] = mapped_column(MONEY)
    difference: Mapped[Decimal | None] = mapped_column(MONEY)
    z_number: Mapped[str | None] = mapped_column(String(20))  # chiusura giornaliera del registratore
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)  # totali congelati alla chiusura
    notes: Mapped[str | None] = mapped_column(Text)


class PosCashMove(Base):
    """Prelievi e versamenti di contante durante l'apertura."""

    __tablename__ = "pos_cash_moves"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_sessions.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(10))  # prelievo | versamento
    amount: Mapped[Decimal] = mapped_column(MONEY)
    reason: Mapped[str | None] = mapped_column(String(120))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PosPayment(Base):
    """Incasso di uno scontrino (anche misto): contanti, carta, buoni… Il reso ha importi negativi."""

    __tablename__ = "pos_payments"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pos_sessions.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(String(12))  # contanti | carta | bancomat | buono | buono_pasto | satispay | altro
    amount: Mapped[Decimal] = mapped_column(MONEY)  # quanto resta incassato (al netto del resto)
    tendered: Mapped[Decimal | None] = mapped_column(MONEY)  # contante consegnato dal cliente
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


POS_TABLES = ["pos_departments", "pos_registers", "pos_sessions", "pos_cash_moves", "pos_payments"]
