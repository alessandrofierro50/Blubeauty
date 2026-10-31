"""Documenti commerciali: un modello unico per ciclo passivo (acquisti) e attivo (vendite).

Tipi documento (doc_type):
  acquisti: ORF ordine a fornitore · DDTF DDT fornitore · FTF fattura fornitore · NCF nota di credito fornitore
  vendite: PRV preventivo · ORC ordine cliente · DDT · FTI fattura immediata · FTD fattura differita · NC nota di credito
  banco: SCO documento commerciale (scontrino) · RSO reso / annullo
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.models import JSONType

MONEY = Numeric(14, 4)
QTY = Numeric(14, 4)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class Numbering(Base):
    """Progressivo per ragione sociale, tipo, anno e sezionale. Letto con SELECT ... FOR UPDATE: nessun buco."""

    __tablename__ = "numbering"
    __table_args__ = (UniqueConstraint("tenant_id", "company_id", "doc_type", "year", "series"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    doc_type: Mapped[str] = mapped_column(String(6))
    year: Mapped[int] = mapped_column(Integer)
    series: Mapped[str] = mapped_column(String(10), default="")
    last_number: Mapped[int] = mapped_column(Integer, default=0)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_type_date", "tenant_id", "doc_type", "doc_date"),
        Index("ix_documents_party", "tenant_id", "party_id"),
        UniqueConstraint("tenant_id", "client_uuid", name="uq_documents_client_uuid"),
        Index("ix_documents_sales_date", "tenant_id", "doc_date", postgresql_where=text("direction = 'vendita'")),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="RESTRICT"))
    doc_type: Mapped[str] = mapped_column(String(6))
    direction: Mapped[str] = mapped_column(String(8))  # acquisto | vendita
    year: Mapped[int] = mapped_column(Integer)
    series: Mapped[str] = mapped_column(String(10), default="")
    number: Mapped[int | None] = mapped_column(Integer)  # progressivo interno (assegnato alla conferma)
    doc_date: Mapped[date] = mapped_column(Date)
    external_number: Mapped[str | None] = mapped_column(String(40))  # numero del documento del fornitore
    external_date: Mapped[date | None] = mapped_column(Date)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"))
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    store_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(12), default="bozza")  # bozza | confermato | evaso | annullato
    payment_term_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_terms.id", ondelete="SET NULL"))
    moves_stock: Mapped[bool] = mapped_column(Boolean, default=True)  # carica/scarica il magazzino alla conferma
    taxable_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    vat_total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    total: Mapped[Decimal] = mapped_column(MONEY, default=0)
    withholding_total: Mapped[Decimal] = mapped_column(MONEY, default=0)  # ritenuta d'acconto
    stamp_duty: Mapped[Decimal] = mapped_column(MONEY, default=0)  # bollo
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    reference: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(10), default="manuale")  # manuale | xml
    xml_file: Mapped[str | None] = mapped_column(String(80))  # file originale (media) per le fatture importate
    payment_schedule: Mapped[list] = mapped_column(JSONType, default=list)  # scadenze lette dalla fattura
    stock_operation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # --- vendite
    destination_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("party_addresses.id", ondelete="SET NULL"))
    # DDT: causale, porto, vettore, colli, peso, aspetto dei beni, inizio trasporto
    transport: Mapped[dict] = mapped_column(JSONType, default=dict)
    valid_until: Mapped[date | None] = mapped_column(Date)  # validità del preventivo
    # Pagata/incassata. Provvisorio: dalla fase 2e lo aggiorna lo scadenzario.
    settled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    contract_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contracts.id", ondelete="SET NULL"))
    attachment_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)  # schede tecniche allegate
    print_options: Mapped[dict] = mapped_column(JSONType, default=dict)  # descrizioni estese, immagini, prezzi nascosti...
    # --- vendita al banco
    prices_vat_included: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    register_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_registers.id", ondelete="SET NULL"))
    pos_session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_sessions.id", ondelete="SET NULL"), index=True)
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # id generato dalla cassa: niente doppioni offline
    fiscal: Mapped[dict] = mapped_column(JSONType, default=dict)  # registratore: matricola, n. documento commerciale, Z, lotteria
    # --- tentata vendita: giro dell'agente, consegna firmata (firma, chi ritira, ora, posizione) e invii al cliente
    van_trip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("van_trips.id", ondelete="SET NULL"), index=True)
    delivery: Mapped[dict] = mapped_column(JSONType, default=dict, server_default="{}")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    lines: Mapped[list["DocumentLine"]] = relationship(cascade="all, delete-orphan", order_by="DocumentLine.line_no")


class DocumentLine(Base):
    __tablename__ = "document_lines"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id", ondelete="RESTRICT"), index=True)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(10))
    quantity: Mapped[Decimal] = mapped_column(QTY, default=0)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, default=0)  # IVA esclusa
    discount1: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    discount2: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    discount3: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    vat_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vat_rates.id", ondelete="SET NULL"))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    vat_nature: Mapped[str | None] = mapped_column(String(6))
    line_total: Mapped[Decimal] = mapped_column(MONEY, default=0)  # imponibile della riga
    lot_number: Mapped[str | None] = mapped_column(String(60))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    serials: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    qty_processed: Mapped[Decimal] = mapped_column(QTY, default=0)  # quantità già evasa da documenti successivi
    origin_line_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_lines.id", ondelete="SET NULL"))
    supplier_code: Mapped[str | None] = mapped_column(String(60))  # codice articolo letto dalla fattura XML
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)  # vendite: costo al momento della vendita (per il margine)
    unit_price_gross: Mapped[Decimal | None] = mapped_column(MONEY)  # banco: prezzo IVA inclusa
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_departments.id", ondelete="SET NULL"))
    price_source: Mapped[str | None] = mapped_column(String(60))  # vendite: da dove arriva il prezzo proposto
    notes: Mapped[str | None] = mapped_column(Text)


class DocumentLink(Base):
    """Tracciabilità: da quale documento nasce quale (ordine → DDT → fattura)."""

    __tablename__ = "document_links"
    __table_args__ = (UniqueConstraint("from_id", "to_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    from_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    to_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)


class PurchaseLineMemory(Base):
    """Memoria degli abbinamenti fatti all'import XML quando la riga del fornitore non ha un codice articolo."""

    __tablename__ = "purchase_line_memory"
    __table_args__ = (UniqueConstraint("tenant_id", "supplier_id", "description_key"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"))
    description_key: Mapped[str] = mapped_column(String(200))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="SET NULL"))


class Contract(Base):
    """Contratto / canone ricorrente: genera da solo le fatture alla scadenza di ogni periodo."""

    __tablename__ = "contracts"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(20))
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"), index=True)
    description: Mapped[str] = mapped_column(String(200))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    frequency_months: Mapped[int] = mapped_column(Integer, default=1)  # 1 mensile, 3 trimestrale, 12 annuale...
    billing: Mapped[str] = mapped_column(String(12), default="anticipata")  # anticipata | posticipata
    next_invoice_date: Mapped[date] = mapped_column(Date)
    auto_confirm: Mapped[bool] = mapped_column(Boolean, default=True)  # False: la fattura resta in bozza da controllare
    payment_term_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_terms.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lines: Mapped[list["ContractLine"]] = relationship(cascade="all, delete-orphan", order_by="ContractLine.line_no")


class ContractLine(Base):
    __tablename__ = "contract_lines"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    contract_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("contracts.id", ondelete="CASCADE"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("items.id", ondelete="RESTRICT"))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(QTY, default=1)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, default=0)
    discount1: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    vat_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vat_rates.id", ondelete="SET NULL"))


DOCUMENTI_TABLES = ["numbering", "documents", "document_lines", "document_links", "purchase_line_memory",
                    "contracts", "contract_lines"]
