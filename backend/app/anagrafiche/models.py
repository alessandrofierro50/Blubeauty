"""Anagrafiche (Fase 2a): tabelle di supporto, articoli, clienti e fornitori.

Tutte le tabelle hanno tenant_id e sono protette da Row Level Security (vedi TENANT_TABLES)."""

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
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.models import JSONType


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


MONEY = Numeric(14, 4)
QTY = Numeric(14, 4)


# ------------------------------------------------------------------ impostazioni e tabelle di supporto


class AppSetting(Base):
    """Impostazioni dell'azienda cliente (es. gruppi di campi articolo visibili per settore)."""

    __tablename__ = "app_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONType, default=dict)


class VatRate(Base):
    __tablename__ = "vat_rates"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(120))
    rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    nature: Mapped[str | None] = mapped_column(String(6))  # N1..N7 per operazioni senza IVA (FatturaPA)
    legal_reference: Mapped[str | None] = mapped_column(String(200))  # riferimento normativo stampato in fattura
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PaymentTerm(Base):
    __tablename__ = "payment_terms"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(120))
    method: Mapped[str] = mapped_column(String(4), default="MP05")  # ModalitaPagamento FatturaPA (MP01 contanti, MP05 bonifico...)
    # Rate: [{"days": 30, "percent": 50}, {"days": 60, "percent": 50}]
    installments: Mapped[list] = mapped_column(JSONType, default=list)
    end_of_month: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Unit(Base):
    __tablename__ = "units"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(60))
    decimals: Mapped[int] = mapped_column(Integer, default=0)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))


class PriceList(Base):
    __tablename__ = "price_lists"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    vat_included: Mapped[bool] = mapped_column(Boolean, default=False)  # listino al pubblico: prezzi IVA inclusa
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    markup_percent: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))  # ricarico standard sul costo


class CustomFieldDef(Base):
    """Campi personalizzati aggiunti dall'utente, senza modificare il codice."""

    __tablename__ = "custom_field_defs"
    __table_args__ = (UniqueConstraint("tenant_id", "entity", "key"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    entity: Mapped[str] = mapped_column(String(20))  # item | party
    key: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(80))
    field_type: Mapped[str] = mapped_column(String(10), default="text")  # text | number | date | list | bool
    options: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


# ------------------------------------------------------------------ clienti e fornitori


class Party(Base):
    """Anagrafica unica di clienti e fornitori (un soggetto può essere entrambi)."""

    __tablename__ = "parties"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index("ix_parties_search", "tenant_id", "name"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(20))
    is_customer: Mapped[bool] = mapped_column(Boolean, default=True)
    is_supplier: Mapped[bool] = mapped_column(Boolean, default=False)
    person_type: Mapped[str] = mapped_column(String(10), default="azienda")  # azienda | privato | pa
    name: Mapped[str] = mapped_column(String(200))  # ragione sociale o "Cognome Nome"
    first_name: Mapped[str | None] = mapped_column(String(80))
    last_name: Mapped[str | None] = mapped_column(String(80))
    vat_number: Mapped[str | None] = mapped_column(String(20))
    tax_code: Mapped[str | None] = mapped_column(String(16))
    sdi_code: Mapped[str | None] = mapped_column(String(7))  # codice destinatario (7 caratteri, 6 per la PA)
    pec: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    mobile: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(200))
    address: Mapped[str | None] = mapped_column(String(200))
    street_number: Mapped[str | None] = mapped_column(String(10))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(80))
    province: Mapped[str | None] = mapped_column(String(2))
    country: Mapped[str] = mapped_column(String(2), default="IT")
    iban: Mapped[str | None] = mapped_column(String(34))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    payment_term_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payment_terms.id", ondelete="SET NULL"))
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_lists.id", ondelete="SET NULL"))
    discount1: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount2: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    credit_limit: Mapped[Decimal | None] = mapped_column(MONEY)  # fido
    # Superato il fido: "blocca" impedisce nuove vendite, "avvisa" mostra solo un messaggio.
    credit_policy: Mapped[str] = mapped_column(String(10), default="blocca", server_default="blocca")
    split_payment: Mapped[bool] = mapped_column(Boolean, default=False)
    vat_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vat_rates.id", ondelete="SET NULL"))  # esenzione
    customer_category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("customer_categories.id", ondelete="SET NULL"))
    exemption_letter: Mapped[str | None] = mapped_column(String(200))  # dichiarazione d'intento
    notes: Mapped[str | None] = mapped_column(Text)
    custom: Mapped[dict] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    addresses: Mapped[list["PartyAddress"]] = relationship(cascade="all, delete-orphan", order_by="PartyAddress.label")


class PartyAddress(Base):
    """Destinazioni di consegna aggiuntive."""

    __tablename__ = "party_addresses"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(80))
    address: Mapped[str] = mapped_column(String(200))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(80))
    province: Mapped[str | None] = mapped_column(String(2))
    country: Mapped[str] = mapped_column(String(2), default="IT")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


# ------------------------------------------------------------------ articoli


class Item(Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index("ix_items_search", "tenant_id", "description"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    # identificazione
    code: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(String(200))
    long_description: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    item_type: Mapped[str] = mapped_column(String(10), default="articolo")  # articolo | servizio
    image_url: Mapped[str | None] = mapped_column(String(500))
    # classificazione
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    brand_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    family: Mapped[str | None] = mapped_column(String(80))
    line: Mapped[str | None] = mapped_column(String(80))
    season: Mapped[str | None] = mapped_column(String(40))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    # unità di misura e dimensioni
    unit: Mapped[str] = mapped_column(String(10), default="PZ")
    weight_net: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    weight_gross: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    volume: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    length: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    width: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    height: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    # fiscale
    vat_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vat_rates.id", ondelete="SET NULL"))
    intrastat_code: Mapped[str | None] = mapped_column(String(8))  # nomenclatura combinata
    origin_country: Mapped[str | None] = mapped_column(String(2))
    # prezzi e costi (il prezzo base è nel listino predefinito)
    last_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    avg_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    standard_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    # magazzino
    stock_managed: Mapped[bool] = mapped_column(Boolean, default=True)
    lot_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    serial_managed: Mapped[bool] = mapped_column(Boolean, default=False)
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)  # durata standard, propone la scadenza del lotto
    warranty_months: Mapped[int | None] = mapped_column(Integer)
    # banco
    plu: Mapped[str | None] = mapped_column(String(10))  # codice bilancia / tasto rapido
    pos_department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_departments.id", ondelete="SET NULL"))
    sold_by_weight: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    min_stock: Mapped[Decimal | None] = mapped_column(QTY)
    max_stock: Mapped[Decimal | None] = mapped_column(QTY)
    reorder_point: Mapped[Decimal | None] = mapped_column(QTY)
    reorder_qty: Mapped[Decimal | None] = mapped_column(QTY)
    location: Mapped[str | None] = mapped_column(String(60))  # scaffale / ripiano
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)
    has_variants: Mapped[bool] = mapped_column(Boolean, default=False)
    is_kit: Mapped[bool] = mapped_column(Boolean, default=False)  # distinta base: scarica i componenti
    custom: Mapped[dict] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    variants: Mapped[list["ItemVariant"]] = relationship(cascade="all, delete-orphan", order_by="ItemVariant.code")
    barcodes: Mapped[list["ItemBarcode"]] = relationship(cascade="all, delete-orphan")
    units: Mapped[list["ItemUnit"]] = relationship(cascade="all, delete-orphan")
    suppliers: Mapped[list["ItemSupplier"]] = relationship(cascade="all, delete-orphan")
    prices: Mapped[list["ItemPrice"]] = relationship(cascade="all, delete-orphan")
    components: Mapped[list["ItemComponent"]] = relationship(
        cascade="all, delete-orphan", foreign_keys="ItemComponent.item_id"
    )


class ItemVariant(Base):
    __tablename__ = "item_variants"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(50))
    size: Mapped[str | None] = mapped_column(String(20))
    color: Mapped[str | None] = mapped_column(String(40))
    format: Mapped[str | None] = mapped_column(String(40))
    price_delta: Mapped[Decimal | None] = mapped_column(MONEY)  # maggiorazione sul prezzo base
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ItemBarcode(Base):
    __tablename__ = "item_barcodes"
    __table_args__ = (UniqueConstraint("tenant_id", "barcode"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="CASCADE"))
    barcode: Mapped[str] = mapped_column(String(60))
    barcode_type: Mapped[str] = mapped_column(String(10), default="EAN13")  # EAN13 | EAN8 | UPC | CODE128 | QR
    unit: Mapped[str | None] = mapped_column(String(10))  # es. il codice del cartone
    quantity: Mapped[Decimal] = mapped_column(QTY, default=1)


class ItemUnit(Base):
    """Unità di misura secondarie: 1 <unit> = factor x UM principale."""

    __tablename__ = "item_units"
    __table_args__ = (UniqueConstraint("item_id", "unit"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    unit: Mapped[str] = mapped_column(String(10))
    factor: Mapped[Decimal] = mapped_column(QTY)


class ItemSupplier(Base):
    """Codici e costi per fornitore. Serve anche a riconoscere le righe delle fatture XML importate."""

    __tablename__ = "item_suppliers"
    __table_args__ = (UniqueConstraint("item_id", "supplier_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    supplier_code: Mapped[str | None] = mapped_column(String(60))
    last_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    discount: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    min_order_qty: Mapped[Decimal | None] = mapped_column(QTY)


class ItemPrice(Base):
    """Prezzo per listino, con scaglioni di quantità e sconti a cascata."""

    __tablename__ = "item_prices"
    __table_args__ = (UniqueConstraint("item_id", "price_list_id", "min_qty"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    price_list_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("price_lists.id", ondelete="CASCADE"))
    min_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    price: Mapped[Decimal] = mapped_column(MONEY)
    discount1: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount2: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    discount3: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))


class ItemComponent(Base):
    """Distinta base / kit."""

    __tablename__ = "item_components"
    __table_args__ = (UniqueConstraint("item_id", "component_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    component_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(QTY)

    component: Mapped[Item] = relationship(foreign_keys=[component_id])


ANAGRAFICHE_TABLES = [
    "app_settings", "vat_rates", "payment_terms", "units", "categories", "brands", "price_lists",
    "custom_field_defs", "parties", "party_addresses", "items", "item_variants", "item_barcodes",
    "item_units", "item_suppliers", "item_prices", "item_components",
]


# ------------------------------------------------------------------ prezzi personalizzati e promozioni


class CustomerCategory(Base):
    __tablename__ = "customer_categories"
    __table_args__ = (UniqueConstraint("tenant_id", "name"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(80))


class CustomerPrice(Base):
    """Prezzo netto concordato con un cliente per un articolo (o variante)."""

    __tablename__ = "customer_prices"
    __table_args__ = (Index("ix_customer_prices_lookup", "tenant_id", "party_id", "item_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="CASCADE"))
    min_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    net_price: Mapped[Decimal] = mapped_column(MONEY)  # IVA esclusa
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(String(200))


class Promotion(Base):
    __tablename__ = "promotions"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    date_from: Mapped[date] = mapped_column(Date)
    date_to: Mapped[date] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Cosa: tutti gli articoli, categorie o articoli scelti
    item_scope: Mapped[str] = mapped_column(String(12), default="articoli")  # tutti | categorie | articoli
    category_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    item_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    # Per chi: tutti i clienti, categorie di clienti o clienti scelti
    customer_scope: Mapped[str] = mapped_column(String(12), default="tutti")  # tutti | categorie | clienti
    customer_category_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    party_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    # Come: prezzo fisso (stessa base IVA del listino al pubblico se vat_included), sconto % o sconto in euro
    price_type: Mapped[str] = mapped_column(String(10), default="sconto")  # prezzo | sconto | importo
    value: Mapped[Decimal] = mapped_column(MONEY)
    vat_included: Mapped[bool] = mapped_column(Boolean, default=True)  # vale per price_type prezzo/importo
    min_qty: Mapped[Decimal] = mapped_column(QTY, default=0)
    # Meccanica: "prezzo" (prezzo o sconto sul singolo articolo, vale ovunque) oppure promozioni di cassa:
    # "nxm" (prendi buy_qty paghi pay_qty), "nesimo" (ogni buy_qty pezzi il meno caro scontato di value %),
    # "soglia" (spesa di almeno threshold: sconto value % o value € sullo scontrino)
    mechanic: Mapped[str] = mapped_column(String(10), default="prezzo", server_default="prezzo")
    buy_qty: Mapped[int | None] = mapped_column(Integer)
    pay_qty: Mapped[int | None] = mapped_column(Integer)
    threshold: Mapped[Decimal | None] = mapped_column(MONEY)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ItemImage(Base):
    """Immagini dell'articolo. I file stanno nella cartella media con nomi casuali non indovinabili."""

    __tablename__ = "item_images"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)  # 0 = immagine principale
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Catalog(Base):
    """Catalogo o listino stampabile: selezione di categorie/articoli e prezzi da mostrare."""

    __tablename__ = "catalogs"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str | None] = mapped_column(String(200))
    layout: Mapped[str] = mapped_column(String(10), default="griglia")  # griglia (con immagini) | elenco
    price_list_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("price_lists.id", ondelete="SET NULL"))
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))  # prezzi del cliente
    show_prices: Mapped[bool] = mapped_column(Boolean, default=True)
    vat_included: Mapped[bool] = mapped_column(Boolean, default=True)
    show_codes: Mapped[bool] = mapped_column(Boolean, default=True)
    group_by_category: Mapped[bool] = mapped_column(Boolean, default=True)
    category_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    include_item_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    exclude_item_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    valid_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ItemAttachment(Base):
    """Schede tecniche, certificati, manuali... da allegare a preventivi e documenti."""

    __tablename__ = "item_attachments"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    file_name: Mapped[str] = mapped_column(String(80))
    original_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="scheda_tecnica")  # scheda_tecnica | certificato | manuale | sicurezza | altro
    size: Mapped[int] = mapped_column(Integer, default=0)
    attach_to_quotes: Mapped[bool] = mapped_column(Boolean, default=True)  # proposto in automatico nei preventivi
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
