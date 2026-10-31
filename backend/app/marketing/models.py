"""Comunicazione con i clienti e marketing (WhatsApp, SMS, email).

- `messages`: ogni messaggio inviato o ricevuto, con stato del provider.
- `automations`: messaggi automatici (conferma, promemoria, disdetta, grazie + recensione, richiamo, compleanno,
  clienti persi). Conferma, promemoria e disdetta fanno parte dell'agenda (pacchetto AGENDA); gli altri e le
  campagne del modulo `marketing` (pacchetto SALONE).
- `campaigns`: invii a un segmento di clienti, SOLO a chi ha dato il consenso marketing (GDPR).
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


class MarketingSettings(Base):
    """Canale WhatsApp dell'azienda. Senza credenziali i messaggi restano in modalità simulata (registrati, non inviati)."""

    __tablename__ = "marketing_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    whatsapp_mode: Mapped[str] = mapped_column(String(20), default="simulato")  # simulato | cloud_api
    whatsapp_phone_id: Mapped[str | None] = mapped_column(String(40))  # Phone number ID di WhatsApp Business Cloud API
    whatsapp_token_enc: Mapped[str | None] = mapped_column(Text)  # token cifrato con SECRET_KEY
    review_url: Mapped[str | None] = mapped_column(String(300))  # link della recensione Google
    sender_name: Mapped[str | None] = mapped_column(String(80))


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_party", "tenant_id", "party_id", "created_at"),
        # un messaggio automatico parte una sola volta (promemoria per appuntamento, auguri per anno…)
        Index("ux_messages_dedupe", "tenant_id", "dedupe_key", unique=True, postgresql_where=text("dedupe_key IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("parties.id", ondelete="SET NULL"))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_appointments.id", ondelete="SET NULL"), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    channel: Mapped[str] = mapped_column(String(10), default="whatsapp")  # whatsapp | sms | email
    # conferma | promemoria | disdetta | grazie | richiamo | compleanno | clienti_persi | campagna
    kind: Mapped[str] = mapped_column(String(20))
    to: Mapped[str] = mapped_column(String(40))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="in_coda")  # in_coda | inviato | consegnato | letto | errore | simulato
    inbound: Mapped[bool] = mapped_column(Boolean, default=False)
    provider_id: Mapped[str | None] = mapped_column(String(120))
    error: Mapped[str | None] = mapped_column(Text)
    # chiave per non mandare due volte lo stesso automatico (es. "promemoria:<appuntamento>", "compleanno:2026:<cliente>")
    dedupe_key: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Automation(Base):
    __tablename__ = "automations"
    __table_args__ = (UniqueConstraint("tenant_id", "kind"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    kind: Mapped[str] = mapped_column(String(20))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    channel: Mapped[str] = mapped_column(String(10), default="whatsapp")
    # promemoria: ore prima; richiamo: giorni (se il servizio non ha i suoi); clienti persi: giorni senza visite
    offset: Mapped[int | None] = mapped_column(Integer)
    template: Mapped[str] = mapped_column(Text)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    channel: Mapped[str] = mapped_column(String(10), default="whatsapp")
    segment: Mapped[str] = mapped_column(String(20), default="tutti")  # tutti | inattivi_60 | compleanno_mese | nuovi_30
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(12), default="bozza")  # bozza | inviata
    recipients: Mapped[int] = mapped_column(Integer, default=0)
    filters: Mapped[dict] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(120))


# ─────────────────────────────────────────────────────────────── fidelity: raccolta punti e tessere
class LoyaltySettings(Base):
    """Regole della raccolta punti (una riga per azienda)."""

    __tablename__ = "loyalty_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    points_per_euro: Mapped[int] = mapped_column(Integer, default=1)  # punti per ogni euro speso (interi)
    welcome_points: Mapped[int] = mapped_column(Integer, default=0)  # alla consegna della tessera
    referral_points: Mapped[int] = mapped_column(Integer, default=50)  # a chi presenta un'amica, alla sua prima visita pagata
    card_prefix: Mapped[str] = mapped_column(String(6), default="BB")
    next_card_number: Mapped[int] = mapped_column(Integer, default=1)  # contatore delle tessere (riga bloccata)


class LoyaltyReward(Base):
    """Premio a soglia: si riscatta in cassa scalando i punti."""

    __tablename__ = "loyalty_rewards"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    name: Mapped[str] = mapped_column(String(120))
    points: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default="sconto_euro")  # sconto_euro | sconto_percento | servizio
    value: Mapped[int] = mapped_column(Integer, default=0)  # euro o percentuale
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_services.id", ondelete="SET NULL"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class LoyaltyCard(Base):
    __tablename__ = "loyalty_cards"
    __table_args__ = (UniqueConstraint("tenant_id", "number"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"), index=True)
    number: Mapped[str] = mapped_column(String(20))  # stampato sulla tessera con il codice a barre
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LoyaltyMove(Base):
    """Movimento di punti: il saldo è la somma (copiato in agenda_client_profiles.loyalty_points per le liste)."""

    __tablename__ = "loyalty_moves"
    __table_args__ = (
        Index("ix_loyalty_moves_party", "tenant_id", "party_id", "created_at"),
        Index("ux_loyalty_moves_dedupe", "tenant_id", "dedupe_key", unique=True, postgresql_where=text("dedupe_key IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    party_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("parties.id", ondelete="CASCADE"))
    points: Mapped[int] = mapped_column(Integer)  # positivo accumulo, negativo riscatto
    # acquisto | premio | benvenuto | presenta_amica | rettifica
    reason: Mapped[str] = mapped_column(String(20))
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agenda_appointments.id", ondelete="SET NULL"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    reward_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("loyalty_rewards.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(200))
    dedupe_key: Mapped[str | None] = mapped_column(String(120))  # niente doppi accrediti (es. "acquisto:<appuntamento>")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str | None] = mapped_column(String(120))
