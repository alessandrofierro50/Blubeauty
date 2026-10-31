"""Tentata vendita (modulo extra): agenti con furgone.

- Furgone = magazzino dedicato con agente, targa e sezionale dei documenti (es. "A3": DDT 125/A3).
- Giro clienti abituale per giorno della settimana; il giro del giorno parte da lì (più gli ordini da consegnare).
- Giro del giorno: carico dal magazzino centrale (trasferimento), documenti e incassi emessi dall'agente anche senza rete
  (`client_uuid`), rientro con conta del magazziniere (anche alla cieca), differenze motivate e firme, quadratura di cassa.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType

MONEY = Numeric(14, 2)
QTY = Numeric(14, 4)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class Van(Base):
    __tablename__ = "vans"
    __table_args__ = (UniqueConstraint("tenant_id", "code"), UniqueConstraint("tenant_id", "series"))

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(10))
    name: Mapped[str] = mapped_column(String(60))
    vehicle: Mapped[str | None] = mapped_column(String(60))  # tipo di mezzo
    plate: Mapped[str | None] = mapped_column(String(12))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"), unique=True)
    home_warehouse_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("warehouses.id", ondelete="RESTRICT"))  # da cui si carica
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    series: Mapped[str] = mapped_column(String(10))  # sezionale dei documenti dell'agente
    max_discount: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)  # sconto massimo che l'agente può fare
    allowed_docs: Mapped[list[str]] = mapped_column(ARRAY(String), default=lambda: ["DDT", "FTI", "ORC", "NC"])
    cash_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_accounts.id", ondelete="SET NULL"))
    blind_count: Mapped[bool] = mapped_column(Boolean, default=True)  # al rientro il magazziniere conta senza vedere le quantità
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VanRouteStop(Base):
    """Giro clienti abituale: in quali giorni della settimana (0 = lunedì) e in che ordine si visita il cliente."""

    __tablename__ = "van_route_stops"
    __table_args__ = (UniqueConstraint("van_id", "party_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    van_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vans.id", ondelete="CASCADE"), index=True)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"))
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger), default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class VanTrip(Base):
    """Giro del giorno. Stati: preparazione → in_corso → rientro (attende il magazziniere) → chiuso."""

    __tablename__ = "van_trips"
    __table_args__ = (UniqueConstraint("van_id", "trip_date"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    van_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vans.id", ondelete="RESTRICT"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    trip_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="preparazione")
    stops: Mapped[list] = mapped_column(JSONType, default=list)  # [{"party_id", "notes", "visited": bool}]
    load_operations: Mapped[list] = mapped_column(JSONType, default=list)  # [{"operation_id", "at", "user_id"}]
    km_start: Mapped[int | None] = mapped_column(Integer)
    km_end: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # quadratura di cassa dichiarata dall'agente al rientro: {"contanti": "120.00", "assegno": "50.00"}
    cash_declared: Mapped[dict] = mapped_column(JSONType, default=dict)
    return_notes: Mapped[str | None] = mapped_column(Text)
    # verifica del magazziniere
    checked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remaining: Mapped[str | None] = mapped_column(String(10))  # rientra (in centrale) | resta (sul furgone)
    signatures: Mapped[dict] = mapped_column(JSONType, default=dict)  # {"agente": {...}, "magazziniere": {...}}
    return_operation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    adjust_operation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VanCount(Base):
    """Riga della conta al rientro: quanto doveva esserci sul furgone, quanto è stato contato e perché è diverso."""

    __tablename__ = "van_counts"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("van_trips.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("items.id", ondelete="RESTRICT"))
    variant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("item_variants.id", ondelete="RESTRICT"))
    lot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lots.id", ondelete="RESTRICT"))
    expected: Mapped[Decimal] = mapped_column(QTY, default=0)
    agent_count: Mapped[Decimal | None] = mapped_column(QTY)  # conta facoltativa dell'agente
    counted: Mapped[Decimal] = mapped_column(QTY, default=0)  # conta del magazziniere
    reason: Mapped[str | None] = mapped_column(String(20))  # rotto | ammanco | errore_carico | scaduto | altro
    notes: Mapped[str | None] = mapped_column(Text)


class VanCollection(Base):
    """Incasso sul posto: chiude le scadenze del cliente nello scadenzario e va nella quadratura del giro."""

    __tablename__ = "van_collections"
    __table_args__ = (UniqueConstraint("tenant_id", "client_uuid"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    trip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("van_trips.id", ondelete="CASCADE"), index=True)
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="RESTRICT"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    method: Mapped[str] = mapped_column(String(10))  # contanti | assegno | pos
    amount: Mapped[Decimal] = mapped_column(MONEY)
    check_info: Mapped[str | None] = mapped_column(String(120))  # banca e numero dell'assegno
    payment_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    unallocated: Mapped[Decimal] = mapped_column(MONEY, default=0)  # acconto senza scadenze aperte
    signature: Mapped[dict] = mapped_column(JSONType, default=dict)
    client_uuid: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


TENTATA_TABLES = ["vans", "van_route_stops", "van_trips", "van_counts", "van_collections"]
