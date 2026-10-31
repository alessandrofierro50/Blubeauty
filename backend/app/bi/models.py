"""Report salvati (report builder del pacchetto Pro) e dashboard personalizzabili."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.models import JSONType


class SavedReport(Base):
    """Analisi salvata: cubo, righe/colonne, misure, filtri, periodo (anche relativo), grafico; invio programmato via email."""

    __tablename__ = "saved_reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    cube: Mapped[str] = mapped_column(String(20))
    config: Mapped[dict] = mapped_column(JSONType, default=dict)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    shared: Mapped[bool] = mapped_column(Boolean, default=True)
    schedule: Mapped[dict] = mapped_column(JSONType, default=dict)  # {frequency: settimanale|mensile|giornaliero, weekday, day, emails}
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Dashboard(Base):
    """Dashboard con widget (report salvati) disposti dall'utente."""

    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    owner_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    widgets: Mapped[list] = mapped_column(JSONType, default=list)  # [{report_id, width: 1-4, view?: kpi|grafico|tabella}]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
