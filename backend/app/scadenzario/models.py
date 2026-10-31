"""Scadenzario attivo e passivo: conti di cassa/banca, scadenze, incassi e pagamenti, solleciti, fotografie della liquidità."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.models import JSONType

MONEY = Numeric(14, 2)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class FinancialAccount(Base):
    """Cassa, conti bancari, carte: il saldo iniziale serve alla fotografia della liquidità."""

    __tablename__ = "financial_accounts"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(10), default="banca")  # cassa | banca | carta | altro
    iban: Mapped[str | None] = mapped_column(String(34))
    opening_balance: Mapped[Decimal] = mapped_column(MONEY, default=0)
    opening_date: Mapped[date | None] = mapped_column(Date)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Installment(Base):
    """Una scadenza: rata di una fattura (attiva o passiva) o voce inserita a mano (affitto, F24, rata...).

    Gli importi delle note di credito sono negativi: riducono quanto il cliente deve (o quanto dobbiamo)."""

    __tablename__ = "installments"
    __table_args__ = (Index("ix_installments_open", "tenant_id", "direction", "status", "due_date"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    direction: Mapped[str] = mapped_column(String(8))  # attiva (da incassare) | passiva (da pagare)
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"), index=True)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)  # rata n. seq di total_seq
    total_seq: Mapped[int] = mapped_column(Integer, default=1)
    description: Mapped[str] = mapped_column(String(200))
    issue_date: Mapped[date] = mapped_column(Date)  # data del documento: da quando la scadenza "esiste"
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    paid_amount: Mapped[Decimal] = mapped_column(MONEY, default=0)
    method: Mapped[str | None] = mapped_column(String(4))  # ModalitaPagamento FatturaPA (MP01 contanti, MP05 bonifico, MP12 RiBa...)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="aperta")  # aperta | parziale | pagata
    unpaid: Mapped[bool] = mapped_column(Boolean, default=False)  # insoluta (es. Ri.Ba. tornata indietro)
    reminder_level: Mapped[int] = mapped_column(Integer, default=0)  # ultimo livello di sollecito inviato
    last_reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    payments: Mapped[list["InstallmentPayment"]] = relationship(cascade="all, delete-orphan", order_by="InstallmentPayment.pay_date")


class InstallmentPayment(Base):
    """Incasso o pagamento (anche parziale) di una scadenza."""

    __tablename__ = "installment_payments"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    installment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("installments.id", ondelete="CASCADE"), index=True)
    pay_date: Mapped[date] = mapped_column(Date, index=True)
    amount: Mapped[Decimal] = mapped_column(MONEY)
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id", ondelete="SET NULL"))
    method: Mapped[str | None] = mapped_column(String(4))
    notes: Mapped[str | None] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentReminder(Base):
    """Registro dei solleciti inviati (email o WhatsApp)."""

    __tablename__ = "payment_reminders"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    level: Mapped[int] = mapped_column(Integer)
    channel: Mapped[str] = mapped_column(String(10), default="email")  # email | whatsapp
    recipients: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    subject: Mapped[str | None] = mapped_column(String(200))
    total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    installment_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    status: Mapped[str] = mapped_column(String(10), default="inviato")  # inviato | errore
    error: Mapped[str | None] = mapped_column(Text)
    automatic: Mapped[bool] = mapped_column(Boolean, default=False)
    sent_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LiquiditySnapshot(Base):
    """Fotografia della liquidità salvata: i dati restano congelati per i confronti nel tempo."""

    __tablename__ = "liquidity_snapshots"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    as_of: Mapped[date] = mapped_column(Date)
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


SCADENZARIO_TABLES = ["financial_accounts", "installments", "installment_payments", "payment_reminders", "liquidity_snapshots"]
