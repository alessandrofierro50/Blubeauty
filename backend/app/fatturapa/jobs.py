"""Job periodico: aggiorna gli stati SDI e scarica le fatture ricevute, un'azienda per transazione."""

import logging
import time
from datetime import date

from sqlalchemy import select

from app.core.db import set_tenant
from app.core.models import Tenant
from app.fatturapa import service as sdi
from app.fatturapa.aruba import ArubaError
from app.saas.service import tenant_state

log = logging.getLogger(__name__)


def poll_all_tenants(session_factory, on: date, pause: float = 5.0) -> dict:
    db = session_factory()
    try:
        tenants = [t.id for t in db.scalars(select(Tenant))
                   if (st := tenant_state(t, on)).access in ("full", "readonly") and "fatturapa" in st.modules]
    finally:
        db.close()
    out = {}
    for n, tid in enumerate(tenants):
        if n and pause:
            time.sleep(pause)  # Aruba: massimo 12 ricerche al minuto per IP
        db = session_factory()
        try:
            set_tenant(db, tid)
            out[str(tid)] = sdi.poll_tenant(db, tid)
            db.commit()
        except ArubaError as exc:
            db.rollback()
            out[str(tid)] = str(exc)
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("Aggiornamento SDI: errore per l'azienda %s", tid)
            out[str(tid)] = "errore"
        finally:
            db.close()
    return out
