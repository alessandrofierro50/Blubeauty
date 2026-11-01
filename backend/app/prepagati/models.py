"""Buoni regalo e pacchetti di sedute (prepagati) di BluBeauty.

Buono regalo «multiuso» (predefinito, art. 6-quater DPR 633/72): alla VENDITA si registra l'incasso con una ricevuta non
fiscale; lo scontrino si fa all'UTILIZZO per l'importo usato, pagato «con buono regalo» (il registratore non lo conta di nuovo
come incasso). «Monouso» (art. 6-ter): scontrino alla vendita, all'utilizzo nessun nuovo scontrino. In entrambi i casi il
saldo si scala a ogni uso (`gift_voucher_moves`) e il residuo resta sul buono.
Pacchetto di sedute: listino (`service_packages`), venduto alla cliente (`client_packages`, scontrino alla vendita),
ogni seduta usata all'incasso dell'appuntamento è una riga di `client_package_uses`.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class GiftVoucher(Base):
    __tablename__ = "gift_vouchers"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="ux_gift_vouchers_code"),
                      UniqueConstraint("public_token", name="ux_gift_vouchers_token"))

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    code: Mapped[str] = mapped_column(String(20))                    # BR-XXXX-XXXX
    public_token: Mapped[str] = mapped_column(String(48))           # link per la persona che lo riceve
    kind: Mapped[str] = mapped_column(String(10), default="importo")  # importo | servizio
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_services.id", ondelete="SET NULL"))
    initial_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    balance: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    purchaser_party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    beneficiary_name: Mapped[str | None] = mapped_column(String(120))
    # cliente che lo riceve, se è già in anagrafica: il buono compare nella sua scheda e all'incasso
    beneficiary_party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"), index=True)
    # multiuso: scontrino all'UTILIZZO (alla vendita solo ricevuta non fiscale); monouso: scontrino alla VENDITA
    fiscal_mode: Mapped[str] = mapped_column(String(10), default="multiuso", server_default="multiuso")
    message: Mapped[str | None] = mapped_column(String(300))
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="attivo")  # attivo | esaurito | annullato (scaduto: calcolato)
    sale_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GiftVoucherMove(Base):
    __tablename__ = "gift_voucher_moves"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    voucher_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gift_vouchers.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(12))  # emissione | utilizzo | annullo
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))  # + emissione, − utilizzo
    balance_after: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_appointments.id", ondelete="SET NULL"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(200))
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ServicePackage(Base):
    """Pacchetto a listino, es. «10 pressoterapie»: servizi con il numero di sedute, prezzo, durata."""

    __tablename__ = "service_packages"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    items: Mapped[list] = mapped_column(JSONType, default=list)  # [{"service_id", "sessions"}]
    validity_days: Mapped[int | None] = mapped_column(Integer)  # vuoto = senza scadenza
    min_days: Mapped[int | None] = mapped_column(Integer)  # giorni consigliati tra una seduta e l'altra
    description: Mapped[str | None] = mapped_column(String(300))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientPackage(Base):
    """Pacchetto venduto a una cliente (copia del listino al momento della vendita)."""

    __tablename__ = "client_packages"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("service_packages.id", ondelete="SET NULL"))
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    items: Mapped[list] = mapped_column(JSONType, default=list)  # [{"service_id", "name", "sessions"}]
    min_days: Mapped[int | None] = mapped_column(Integer)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(12), default="attivo")  # attivo | esaurito | annullato (scaduto: calcolato)
    sale_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientPackageUse(Base):
    __tablename__ = "client_package_uses"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    client_package_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("client_packages.id", ondelete="CASCADE"), index=True)
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_services.id", ondelete="SET NULL"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_appointments.id", ondelete="SET NULL"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)  # prezzo di listino della seduta (solo informativo)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
