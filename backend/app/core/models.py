"""Modelli della Fase 1: area SaaS (gestione abbonamenti) e base dell'area cliente."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


# --------------------------------------------------------------------------
# Area SaaS (nessuna RLS: accessibile solo dalle API del super amministratore)
# --------------------------------------------------------------------------


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(20), unique=True)  # BASE | PLUS | PRO
    name: Mapped[str] = mapped_column(String(80))
    price_month: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    price_year: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    modules: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    max_users: Mapped[int] = mapped_column(Integer, default=3)
    max_companies: Mapped[int] = mapped_column(Integer, default=1)
    max_warehouses: Mapped[int] = mapped_column(Integer, default=1)
    max_pos: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(200))
    vat_number: Mapped[str | None] = mapped_column(String(20))
    tax_code: Mapped[str | None] = mapped_column(String(20))
    sector: Mapped[str | None] = mapped_column(String(80))
    contact_name: Mapped[str | None] = mapped_column(String(120))
    contact_email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    billing_data: Mapped[dict] = mapped_column(JSONType, default=dict)
    notes: Mapped[str | None] = mapped_column(Text)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    # Limiti personalizzati (null = usa quelli del pacchetto)
    max_users: Mapped[int | None] = mapped_column(Integer)
    max_companies: Mapped[int | None] = mapped_column(Integer)
    max_warehouses: Mapped[int | None] = mapped_column(Integer)
    max_pos: Mapped[int | None] = mapped_column(Integer)
    # Accettazione dei termini di utilizzo (iscrizione alla prova dal sito): versione, quando e da quale IP
    terms_version: Mapped[str | None] = mapped_column(String(20))
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_accepted_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="tenant", order_by="Subscription.start_date"
    )
    extra_modules: Mapped[list["TenantModule"]] = relationship(cascade="all, delete-orphan")


class Subscription(Base):
    """Un periodo di abbonamento. Ogni rinnovo o cambio pacchetto crea una nuova riga (storico)."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("plans.id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=0)
    period: Mapped[str] = mapped_column(String(20), default="annuale")  # mensile | annuale | personalizzata
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False)
    grace_days: Mapped[int] = mapped_column(Integer, default=15)
    readonly_days: Mapped[int] = mapped_column(Integer, default=30)  # dopo la tolleranza, poi sospensione
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="subscriptions")
    plan: Mapped[Plan] = relationship()


class TenantModule(Base):
    """Modulo extra attivato su un singolo cliente, oltre a quelli del pacchetto."""

    __tablename__ = "tenant_modules"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    module: Mapped[str] = mapped_column(String(40), primary_key=True)


class SuperAdmin(Base):
    __tablename__ = "super_admins"

    id: Mapped[uuid.UUID] = uuid_pk()
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    # recupero password: solo l'impronta SHA-256 del link, valido un'ora
    reset_token_hash: Mapped[str | None] = mapped_column(String(64))
    reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Versione dei token: cresce quando le credenziali cambiano dalla Console, così le sessioni aperte decadono.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    credentials_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    code: Mapped[str] = mapped_column(String(40), primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)


class ReminderRule(Base):
    """Giorni prima della scadenza in cui inviare l'avviso (0 = giorno della scadenza)."""

    __tablename__ = "reminder_rules"

    days_before: Mapped[int] = mapped_column(Integer, primary_key=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SaasSetting(Base):
    """Impostazioni del ciclo di vita modificabili dal pannello (tabella di sistema, senza RLS):
    giorni di tolleranza e di sola lettura predefiniti, giorni di avviso della prova. Vedi logic.LIFECYCLE_DEFAULTS."""

    __tablename__ = "saas_settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict | list | int | None] = mapped_column(JSONType)


class EmailLog(Base):
    __tablename__ = "email_log"
    # NULLS NOT DISTINCT: vale anche per il riepilogo settimanale, che non ha abbonamento.
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "rule", name="uq_email_once_per_rule", postgresql_nulls_not_distinct=True
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE")
    )
    rule: Mapped[str] = mapped_column(String(40))  # es. "giorni_7", "fine_tolleranza", "riepilogo_2026-43"
    recipients: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(300))
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    admin_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # super admin o impersonificazione
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[dict | None] = mapped_column(JSONType)
    after: Mapped[dict | None] = mapped_column(JSONType)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# --------------------------------------------------------------------------
# Area cliente (tenant_id + Row Level Security)
# --------------------------------------------------------------------------


class Company(Base):
    """Ragione sociale. Un cliente può averne più d'una, entro i limiti del pacchetto."""

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    vat_number: Mapped[str | None] = mapped_column(String(20))
    tax_code: Mapped[str | None] = mapped_column(String(20))
    tax_regime: Mapped[str] = mapped_column(String(10), default="RF01")
    # Iscrizione REA (obbligatoria in fattura elettronica per le società iscritte al registro imprese)
    rea_office: Mapped[str | None] = mapped_column(String(2))  # sigla provincia dell'ufficio
    rea_number: Mapped[str | None] = mapped_column(String(20))
    share_capital: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sole_shareholder: Mapped[str | None] = mapped_column(String(2))  # SU socio unico | SM più soci
    in_liquidation: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    address: Mapped[str | None] = mapped_column(String(200))
    zip_code: Mapped[str | None] = mapped_column(String(10))
    city: Mapped[str | None] = mapped_column(String(80))
    province: Mapped[str | None] = mapped_column(String(2))
    pec: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(40))
    website: Mapped[str | None] = mapped_column(String(200))
    iban: Mapped[str | None] = mapped_column(String(34))
    bank_name: Mapped[str | None] = mapped_column(String(120))
    logo_file: Mapped[str | None] = mapped_column(String(80))  # nome base del file nella cartella media
    # Layout di stampa: colore, piè di pagina, note... usato da tutti i documenti stampati
    print_settings: Mapped[dict] = mapped_column(JSONType, default=dict, server_default="{}")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(120))


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(200), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(200))
    full_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(30), default="amministratore")
    # amministratore | amministrazione | vendite | magazzino | cassa
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    activation_token: Mapped[str | None] = mapped_column(String(100))
    # password provvisoria (scelta dal super amministratore o mandata con la prova): va cambiata al primo accesso
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    reset_token_hash: Mapped[str | None] = mapped_column(String(64))
    reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Tabelle che ricevono la policy RLS (usato dalla migrazione e dai test di isolamento).
TENANT_TABLES = ["companies", "warehouses", "users"]

# Le tabelle delle anagrafiche (Fase 2a) sono definite nel loro modulo.
TENANT_TABLES += [
    "app_settings", "vat_rates", "payment_terms", "units", "categories", "brands", "price_lists",
    "custom_field_defs", "parties", "party_addresses", "items", "item_variants", "item_barcodes",
    "item_units", "item_suppliers", "item_prices", "item_components",
    "customer_categories", "customer_prices", "promotions", "item_images", "catalogs",
    "stores", "lots", "serials", "stock_movements", "stock_balances", "inventory_sessions", "inventory_counts",
    "item_attachments",
    "numbering", "documents", "document_lines", "document_links", "purchase_line_memory",
    "contracts", "contract_lines",
    "financial_accounts", "installments", "installment_payments", "payment_reminders", "liquidity_snapshots",
    "einvoices", "einvoice_inbox",
    "pos_departments", "pos_registers", "pos_sessions", "pos_cash_moves", "pos_payments",
    "agents", "devices", "device_jobs", "label_templates",
    "saved_reports", "dashboards",
    "vans", "van_route_stops", "van_trips", "van_counts", "van_collections",
    "payments",
    # BluBeauty: agenda e marketing
    "agenda_settings", "agenda_staff", "agenda_resources", "agenda_service_categories", "agenda_services",
    "agenda_service_staff", "agenda_service_resources", "agenda_client_profiles", "agenda_technical_cards",
    "agenda_appointments", "agenda_appointment_items",
    "marketing_settings", "messages", "automations", "campaigns",
    "loyalty_settings", "loyalty_rewards", "loyalty_cards", "loyalty_moves",
]

from app.anagrafiche import models as _anagrafiche_models  # noqa: E402,F401  (registra i modelli)
from app.magazzino import models as _magazzino_models  # noqa: E402,F401
from app.documenti import models as _documenti_models  # noqa: E402,F401
from app.scadenzario import models as _scadenzario_models  # noqa: E402,F401
from app.fatturapa import models as _fatturapa_models  # noqa: E402,F401
from app.pos import models as _pos_models  # noqa: E402,F401
from app.periferiche import models as _periferiche_models  # noqa: E402,F401
from app.bi import models as _bi_models  # noqa: E402,F401
from app.tentata import models as _tentata_models  # noqa: E402,F401
from app.pagamenti import models as _pagamenti_models  # noqa: E402,F401
from app.agenda import models as _agenda_models  # noqa: E402,F401
from app.marketing import models as _marketing_models  # noqa: E402,F401
