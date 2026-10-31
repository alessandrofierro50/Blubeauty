"""Periferiche (pacchetto Plus): computer del negozio con l'agent, dispositivi collegati, coda dei lavori, modelli di etichette."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class Agent(Base):
    """Un computer del negozio su cui gira BluBeauty Agent."""

    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(60))
    hostname: Mapped[str | None] = mapped_column(String(120))
    version: Mapped[str | None] = mapped_column(String(20))
    platform: Mapped[str | None] = mapped_column(String(60))
    local_key: Mapped[str | None] = mapped_column(String(64))  # chiave per il servizio locale (cassa senza rete)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Device(Base):
    """Periferica raggiunta da un agent: registratore telematico, stampante di ricevute o etichette, bilancia."""

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(12))  # rt | stampante | etichette | bilancia
    driver: Mapped[str] = mapped_column(String(30))
    address: Mapped[str | None] = mapped_column(String(200))  # IP[:porta], COM3, nome stampante Windows, cartella
    options: Mapped[dict] = mapped_column(JSONType, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeviceJob(Base):
    """Lavoro da eseguire su una periferica: lo prende l'agent, lo esegue e restituisce l'esito."""

    __tablename__ = "device_jobs"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="in_coda", index=True)  # in_coda | inviato | eseguito | errore | annullato
    result: Mapped[dict] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_sessions.id", ondelete="SET NULL"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class LabelTemplate(Base):
    """Modello di etichetta: dimensioni in mm ed elementi posizionati (testi, prezzo, codice a barre, QR, riquadri)."""

    __tablename__ = "label_templates"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(60))
    width_mm: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    height_mm: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    dpi: Mapped[int] = mapped_column(Integer, default=203)
    gap_mm: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=3)
    elements: Mapped[list] = mapped_column(JSONType, default=list)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentKey(Base):
    """Codici di abbinamento e token degli agent (solo l'impronta SHA-256).

    Tabella di sistema senza RLS: l'agent si presenta col solo token e da qui si ricava l'azienda."""

    __tablename__ = "agent_keys"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(8))  # abbina | token
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


PERIFERICHE_TABLES = ["agents", "devices", "device_jobs", "label_templates"]
