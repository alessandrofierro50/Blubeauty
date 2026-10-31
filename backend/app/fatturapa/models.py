"""Fatturazione elettronica (modulo extra "fatturapa"): trasmissioni a SDI tramite Aruba e fatture ricevute."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def tenant_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


# Stati Aruba/SDI (codice Aruba → chiave interna). "da_inviare" e "verificata" sono solo nostri.
STATUSES = {
    1: "presa_in_carico", 2: "errore_elaborazione", 3: "inviata", 4: "scartata", 5: "non_consegnata",
    6: "recapito_impossibile", 7: "consegnata", 8: "accettata", 9: "rifiutata", 10: "decorrenza_termini",
}
STATUS_LABELS = {
    "da_inviare": "Da inviare", "presa_in_carico": "Presa in carico da Aruba", "errore_elaborazione": "Errore di elaborazione",
    "inviata": "Inviata a SDI", "scartata": "Scartata da SDI", "non_consegnata": "Non consegnata (nel cassetto fiscale)",
    "recapito_impossibile": "Recapito impossibile", "consegnata": "Consegnata", "accettata": "Accettata dalla PA",
    "rifiutata": "Rifiutata dalla PA", "decorrenza_termini": "Decorrenza termini",
}
# stati dopo i quali non serve più chiedere aggiornamenti
FINAL = {"errore_elaborazione", "scartata", "recapito_impossibile", "consegnata", "accettata", "rifiutata", "decorrenza_termini",
         "non_consegnata"}
# per la PA si attende l'esito del committente dopo la consegna
FINAL_PA = FINAL - {"consegnata", "non_consegnata"}
# stati che permettono un nuovo invio (stesso numero e data, dopo aver corretto i dati)
RESENDABLE = {"da_inviare", "errore_elaborazione", "scartata", "rifiutata"}


class EInvoice(Base):
    """Trasmissione di una fattura di vendita a SDI (una riga per ogni tentativo di invio)."""

    __tablename__ = "einvoices"

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    progressive: Mapped[str] = mapped_column(String(10))  # ProgressivoInvio
    format: Mapped[str] = mapped_column(String(5), default="FPR12")  # FPR12 privati, FPA12 PA
    xml_file: Mapped[str | None] = mapped_column(String(80))  # copia dell'XML inviato (media)
    filename: Mapped[str | None] = mapped_column(String(80), index=True)  # nome assegnato da Aruba
    aruba_id: Mapped[str | None] = mapped_column(String(40))
    sdi_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="da_inviare")
    errors: Mapped[list] = mapped_column(JSONType, default=list)  # [{"code": "...", "description": "..."}]
    notifications: Mapped[list] = mapped_column(JSONType, default=list)  # [{"type": "RC", "date": ..., "filename": ...}]
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class EInvoiceInbox(Base):
    """Fattura ricevuta da SDI (tramite Aruba), in attesa di essere registrata negli acquisti."""

    __tablename__ = "einvoice_inbox"
    __table_args__ = (UniqueConstraint("tenant_id", "filename"),)

    id: Mapped[uuid.UUID] = pk()
    tenant_id: Mapped[uuid.UUID] = tenant_fk()
    filename: Mapped[str] = mapped_column(String(120))
    aruba_id: Mapped[str | None] = mapped_column(String(40))
    sdi_id: Mapped[str | None] = mapped_column(String(40))
    supplier_name: Mapped[str | None] = mapped_column(String(200))
    supplier_vat: Mapped[str | None] = mapped_column(String(30))
    number: Mapped[str | None] = mapped_column(String(40))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    doc_type: Mapped[str | None] = mapped_column(String(6))
    total: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    xml_file: Mapped[str | None] = mapped_column(String(80))  # XML (già estratto dal p7m) salvato nei media
    status: Mapped[str] = mapped_column(String(16), default="da_registrare")  # da_registrare | registrata | ignorata
    document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EInvoiceRoute(Base):
    """Instradamento delle callback di Aruba: partita IVA del cedente → azienda cliente.

    Tabella di sistema senza RLS: la callback arriva senza utente e serve sapere a quale azienda appartiene."""

    __tablename__ = "einvoice_routes"

    vat_key: Mapped[str] = mapped_column(String(32), primary_key=True)  # es. IT01234560033
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)


FATTURAPA_TABLES = ["einvoices", "einvoice_inbox"]
