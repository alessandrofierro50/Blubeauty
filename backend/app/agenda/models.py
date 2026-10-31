"""Modulo Agenda di BluBeauty: operatori, cabine/postazioni, servizi con tempi di posa, appuntamenti,
prenotazione online da smartphone con link personale per la disdetta, schede clienti.

Il cliente dell'appuntamento è un'anagrafica `parties` (cliente) del motore comune: così cassa, scontrino sul
registratore telematico, fattura elettronica e storico vendite funzionano come nel resto del gestionale.
I dati propri del salone (consensi, compleanno, punti fedeltà, schede tecniche) stanno in tabelle dedicate.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.core.models import JSONType

MONEY = Numeric(12, 2)


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class BookingPage(Base):
    """Indirizzo pubblico della prenotazione online (/prenota/<slug>).

    Tabella di SISTEMA senza RLS (come `einvoice_routes`): la pagina pubblica non ha un utente collegato, quindi
    dallo slug ricava l'azienda e solo dopo imposta il tenant per leggere i dati con la RLS attiva.
    """

    __tablename__ = "booking_pages"

    slug: Mapped[str] = mapped_column(String(60), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgendaSettings(Base):
    """Impostazioni dell'agenda e della prenotazione online (una riga per azienda)."""

    __tablename__ = "agenda_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    salon_name: Mapped[str] = mapped_column(String(120), default="")  # nome mostrato ai clienti (vuoto = dati azienda)
    # Orari di apertura: {"mon": [["09:00","13:00"],["15:00","19:30"]], ...}; giorno assente = chiuso
    opening_hours: Mapped[dict] = mapped_column(JSONType, default=dict)
    slot_minutes: Mapped[int] = mapped_column(Integer, default=15)
    online_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    online_lead_minutes: Mapped[int] = mapped_column(Integer, default=60)  # anticipo minimo per prenotare online
    online_max_days: Mapped[int] = mapped_column(Integer, default=60)  # fino a quanti giorni avanti
    cancel_hours: Mapped[int] = mapped_column(Integer, default=24)  # disdetta online fino a N ore prima
    welcome_text: Mapped[str | None] = mapped_column(Text)
    register_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_registers.id", ondelete="SET NULL"))  # cassa predefinita
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_departments.id", ondelete="SET NULL"))  # reparto servizi


class AgendaStaff(Base):
    """Operatore (parrucchiera, estetista, barbiere): una colonna in agenda."""

    __tablename__ = "agenda_staff"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    first_name: Mapped[str] = mapped_column(String(60))
    last_name: Mapped[str] = mapped_column(String(60), default="")
    color: Mapped[str] = mapped_column(String(9), default="#2340a8")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    bookable_online: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Orari personali (stesso formato di opening_hours); vuoto = orari del salone
    working_hours: Mapped[dict] = mapped_column(JSONType, default=dict)


class AgendaResource(Base):
    """Cabina, postazione, lavatesta o macchinario: un servizio può richiederne uno libero."""

    __tablename__ = "agenda_resources"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(20), default="cabina")  # cabina | postazione | lavatesta | macchinario
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class AgendaServiceCategory(Base):
    __tablename__ = "agenda_service_categories"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(60))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class AgendaService(Base):
    """Servizio del listino. Il prezzo è IVA inclusa (prezzo al pubblico, come in cassa).

    Tempo di posa: dal minuto `processing_start_min` per `processing_min` minuti l'operatore è libero
    (es. colore: 20' applicazione, 35' posa, 25' lavaggio e piega) e può servire un altro cliente.
    """

    __tablename__ = "agenda_services"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    category_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_service_categories.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(MONEY, default=0)
    vat_rate_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vat_rates.id", ondelete="SET NULL"))
    department_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pos_departments.id", ondelete="SET NULL"))
    duration_min: Mapped[int] = mapped_column(Integer, default=30)
    processing_start_min: Mapped[int | None] = mapped_column(Integer)
    processing_min: Mapped[int | None] = mapped_column(Integer)
    bookable_online: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # Richiamo automatico (es. ritocco colore): giorni dopo il servizio, vuoto = nessun richiamo
    recall_days: Mapped[int | None] = mapped_column(Integer)

    staff_links: Mapped[list["AgendaServiceStaff"]] = relationship(cascade="all, delete-orphan", lazy="selectin")
    resource_links: Mapped[list["AgendaServiceResource"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class AgendaServiceStaff(Base):
    """Chi esegue il servizio."""

    __tablename__ = "agenda_service_staff"

    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_services.id", ondelete="CASCADE"), primary_key=True)
    staff_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_staff.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()


class AgendaServiceResource(Base):
    """Risorse richieste dal servizio: ne serve UNA libera tra quelle elencate."""

    __tablename__ = "agenda_service_resources"

    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_services.id", ondelete="CASCADE"), primary_key=True)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_resources.id", ondelete="CASCADE"), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = tenant_fk()


class ClientProfile(Base):
    """Dati del salone sull'anagrafica cliente: consensi GDPR, compleanno, punti fedeltà."""

    __tablename__ = "agenda_client_profiles"
    __table_args__ = (UniqueConstraint("tenant_id", "party_id"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    privacy_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marketing_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    birth_date: Mapped[date | None] = mapped_column(Date)
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text)


class TechnicalCard(Base):
    """Scheda tecnica: formula colore, trattamento, anamnesi, consenso informato firmato."""

    __tablename__ = "agenda_technical_cards"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # colore | trattamento | anamnesi | consenso
    title: Mapped[str] = mapped_column(String(120))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(120))


class Appointment(Base):
    __tablename__ = "agenda_appointments"
    __table_args__ = (Index("ix_agenda_appointments_day", "tenant_id", "starts_at"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # prenotato | confermato | arrivato | concluso | pagato | disdetto | non_presentato
    status: Mapped[str] = mapped_column(String(20), default="prenotato")
    channel: Mapped[str] = mapped_column(String(20), default="salone")  # salone | online | telefono | whatsapp
    notes: Mapped[str | None] = mapped_column(Text)
    # Link personale del cliente per vedere e disdire l'appuntamento (lungo e casuale, unico tra tutte le aziende)
    public_token: Mapped[str] = mapped_column(String(64), unique=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[str | None] = mapped_column(String(20))  # cliente | salone
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))  # scontrino o fattura
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(120))

    items: Mapped[list["AppointmentItem"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="AppointmentItem.starts_at"
    )


class AppointmentItem(Base):
    """Un servizio dell'appuntamento, con operatore e risorsa (un appuntamento può averne più d'uno)."""

    __tablename__ = "agenda_appointment_items"
    __table_args__ = (
        Index("ix_agenda_items_staff", "staff_id", "starts_at"),
        Index("ix_agenda_items_resource", "resource_id", "starts_at"),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    appointment_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_appointments.id", ondelete="CASCADE"), index=True)
    service_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agenda_services.id", ondelete="RESTRICT"))
    staff_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_staff.id", ondelete="SET NULL"))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_resources.id", ondelete="SET NULL"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    price: Mapped[Decimal] = mapped_column(MONEY, default=0)  # IVA inclusa
    # copia dei tempi del servizio al momento della prenotazione (il listino può cambiare dopo)
    processing_start_min: Mapped[int | None] = mapped_column(Integer)
    processing_min: Mapped[int | None] = mapped_column(Integer)
