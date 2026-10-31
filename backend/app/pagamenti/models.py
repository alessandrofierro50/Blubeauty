"""Pagamenti degli abbonamenti e fatture di BluCode ai clienti.

- `payments` è una tabella del cliente (tenant_id + RLS): il cliente vede solo i suoi pagamenti.
- `payment_routes`, `payment_events` e `invoice_counters` sono tabelle di sistema senza RLS (come `einvoice_routes`):
  i webhook dei gestori arrivano senza utente e devono ricondurre il pagamento all'azienda giusta; il contatore delle
  fatture è unico per sezionale e anno, non per azienda.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType

METHODS = {"carta": "Carta di credito", "paypal": "PayPal", "bonifico": "Bonifico bancario"}
# ModalitaPagamento nell'XML FatturaPA (confermati dal titolare il 2026-10-29)
XML_METHOD = {"carta": "MP08", "paypal": "MP08", "bonifico": "MP05"}
STATUSES = {"in_attesa": "In attesa", "pagato": "Pagato", "fallito": "Fallito", "annullato": "Annullato"}


class Payment(Base):
    """Un pagamento dell'abbonamento. Il numero di fattura, l'XML e il PDF esistono solo quando è «pagato»."""

    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("invoice_sezionale", "invoice_year", "invoice_number", name="uq_payment_invoice_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    plan_code: Mapped[str] = mapped_column(String(20))
    plan_name: Mapped[str] = mapped_column(String(80))
    period: Mapped[str] = mapped_column(String(20))  # mensile | annuale
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # canone (imponibile, senza IVA: forfettario)
    stamp: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)  # rimborso del bollo addebitato al cliente
    stamp_duty: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)  # bollo virtuale in fattura (anche se a carico BluCode)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # importo pagato dal cliente
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    method: Mapped[str] = mapped_column(String(12))  # carta | paypal | bonifico
    status: Mapped[str] = mapped_column(String(12), default="in_attesa")
    causale: Mapped[str] = mapped_column(String(60), unique=True)  # BLUCODE BG 1A2B3C4D (anche per i bonifici)
    provider_ref: Mapped[str | None] = mapped_column(String(120))  # sessione Stripe / ordine PayPal
    provider_payment_ref: Mapped[str | None] = mapped_column(String(120))  # payment_intent Stripe / cattura PayPal
    billing: Mapped[dict] = mapped_column(JSONType, default=dict)  # copia dei dati di fatturazione al momento del pagamento
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # utente dell'azienda
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(80))  # "webhook stripe", "paypal", "super admin <email>"
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    # periodo creato dalla conferma
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    # fattura (numero dal sezionale, solo a pagamento confermato)
    invoice_sezionale: Mapped[str | None] = mapped_column(String(10))
    invoice_year: Mapped[int | None] = mapped_column(Integer)
    invoice_number: Mapped[int | None] = mapped_column(Integer)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    invoice_format: Mapped[str | None] = mapped_column(String(5))  # FPR12 | FPA12
    invoice_xml: Mapped[bytes | None] = mapped_column(LargeBinary)
    invoice_pdf: Mapped[bytes | None] = mapped_column(LargeBinary)  # proforma per il cliente
    invoice_errors: Mapped[list] = mapped_column(JSONType, default=list)  # errori XSD (non dovrebbero esserci)
    sdi_status: Mapped[str | None] = mapped_column(String(24))  # None (invio manuale) | da_inviare | presa_in_carico | ...
    sdi_filename: Mapped[str | None] = mapped_column(String(80))
    sdi_error: Mapped[str | None] = mapped_column(Text)
    # email partite dopo la conferma (proforma al cliente, XML a BluCode)
    customer_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    admin_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    email_error: Mapped[str | None] = mapped_column(Text)

    @property
    def invoice_label(self) -> str | None:
        return f"{self.invoice_number}/{self.invoice_sezionale}" if self.invoice_number else None


class PaymentRoute(Base):
    """Indice di sistema dei pagamenti, senza RLS: id → azienda, riferimento del gestore → pagamento, più un riassunto
    (stato, importi, date) per l'elenco del super amministratore e per la console. Lo aggiorna solo service._sync_route,
    ogni volta che cambia il pagamento; i dati completi (fattura, dati di fatturazione) restano in `payments`."""

    __tablename__ = "payment_routes"

    payment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(12))  # = metodo: carta | paypal | bonifico
    provider_ref: Mapped[str | None] = mapped_column(String(120), unique=True)
    status: Mapped[str] = mapped_column(String(12), index=True)
    plan_code: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(20))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    causale: Mapped[str] = mapped_column(String(60))
    invoice: Mapped[str | None] = mapped_column(String(30))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class PaymentEvent(Base):
    """Eventi dei webhook già elaborati: lo stesso evento rimandato (o ripetuto da un malintenzionato) non fa nulla."""

    __tablename__ = "payment_events"

    provider: Mapped[str] = mapped_column(String(12), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    event_type: Mapped[str | None] = mapped_column(String(80))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InvoiceCounter(Base):
    """Ultimo numero di fattura per sezionale e anno solare. Si incrementa nella stessa transazione della conferma
    (INSERT ... ON CONFLICT DO UPDATE ... RETURNING): se la conferma fallisce il numero torna indietro, quindi niente buchi."""

    __tablename__ = "invoice_counters"

    sezionale: Mapped[str] = mapped_column(String(10), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_number: Mapped[int] = mapped_column(Integer, default=0)
