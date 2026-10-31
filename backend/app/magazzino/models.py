"""Magazzino (Fase 2b): punti vendita, lotti, matricole, movimenti, giacenze, inventari.

Regola d'oro: le giacenze (stock_balances) si modificano SOLO tramite app.magazzino.service.move(),
dentro la stessa transazione del movimento."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

QTY = Numeric(14, 4)
MONEY = Numeric(14, 4)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class Store(Base):
    """Punto vendita: scarica dal magazzino indicato (proprio o condiviso con altri punti vendita)."""

    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(200))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(80))
    province: Mapped[str | None] = mapped_column(String(2))
    phone: Mapped[str | None] = mapped_column(String(40))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Lot(Base):
    __tablename__ = "lots"
    __table_args__ = (UniqueConstraint("tenant_id", "item_id", "lot_number"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    lot_number: Mapped[str] = mapped_column(String(60))
    production_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Serial(Base):
    """Un pezzo con matricola: da dove arriva, dove si trova, a chi è stato venduto, fino a quando è in garanzia."""

    __tablename__ = "serials"
    __table_args__ = (UniqueConstraint("tenant_id", "item_id", "serial_number"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="SET NULL"))
    serial_number: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(12), default="disponibile")  # disponibile | venduto | reso | riparazione | dismesso
    warehouse_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("warehouses.id", ondelete="SET NULL"))
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    purchase_date: Mapped[date | None] = mapped_column(Date)
    purchase_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    sale_date: Mapped[date | None] = mapped_column(Date)
    warranty_until: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_movements_item", "tenant_id", "item_id", "moved_at"),
        Index("ix_movements_warehouse", "tenant_id", "warehouse_id", "moved_at"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    moved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="RESTRICT"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="RESTRICT"))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lots.id", ondelete="RESTRICT"))
    serial_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("serials.id", ondelete="RESTRICT"))
    quantity: Mapped[Decimal] = mapped_column(QTY)  # positiva = entrata, negativa = uscita (UM principale)
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    reason: Mapped[str] = mapped_column(String(20))  # vedi service.REASONS
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    document_type: Mapped[str | None] = mapped_column(String(10))  # collegamento ai documenti (fasi successive)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    document_line_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    operation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)  # raggruppa le righe di un'operazione
    reference: Mapped[str | None] = mapped_column(String(200))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class StockBalance(Base):
    """Giacenza per magazzino / articolo / variante / lotto. Aggiornata solo da service.move()."""

    __tablename__ = "stock_balances"
    __table_args__ = (
        UniqueConstraint("tenant_id", "warehouse_id", "item_id", "variant_id", "lot_id",
                         name="uq_stock_balance", postgresql_nulls_not_distinct=True),
        Index("ix_balances_item", "tenant_id", "item_id"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="CASCADE"))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lots.id", ondelete="CASCADE"))
    on_hand: Mapped[Decimal] = mapped_column(QTY, default=0)  # fisica
    reserved: Mapped[Decimal] = mapped_column(QTY, default=0)  # impegnata da ordini clienti
    ordered: Mapped[Decimal] = mapped_column(QTY, default=0)  # in arrivo da ordini fornitori


class InventorySession(Base):
    __tablename__ = "inventory_sessions"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(10), default="aperto")  # aperto | chiuso | annullato
    category_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)  # vuoto = tutti
    location_prefix: Mapped[str | None] = mapped_column(String(40))
    zero_uncounted: Mapped[bool] = mapped_column(Boolean, default=False)  # alla chiusura azzera i non contati
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # rettifiche generate


class InventoryCount(Base):
    __tablename__ = "inventory_counts"
    __table_args__ = (UniqueConstraint("tenant_id", "client_uuid"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("inventory_sessions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="CASCADE"))
    lot_number: Mapped[str | None] = mapped_column(String(60))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    serial_number: Mapped[str | None] = mapped_column(String(80))
    quantity: Mapped[Decimal] = mapped_column(QTY)
    client_uuid: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))  # evita doppioni quando il telefono reinvia
    source: Mapped[str] = mapped_column(String(12), default="smartphone")  # smartphone | manuale | import
    accepted: Mapped[bool] = mapped_column(Boolean, default=True)  # i conteggi scartati non entrano nella rettifica
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


MAGAZZINO_TABLES = ["stores", "lots", "serials", "stock_movements", "stock_balances", "inventory_sessions", "inventory_counts"]
