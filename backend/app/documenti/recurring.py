"""Job giornaliero: emette le fatture dei contratti ricorrenti per tutte le aziende abilitate."""

import logging
from datetime import date

from sqlalchemy import select

from app.core.db import set_tenant
from app.core.models import Company, Tenant
from app.documenti import vendite_service as sales
from app.saas.service import tenant_state

log = logging.getLogger(__name__)


def run_recurring_invoices(session_factory, on: date) -> dict:
    db = session_factory()
    try:
        tenants = [t.id for t in db.scalars(select(Tenant))
                   if (st := tenant_state(t, on)).access == "full" and "vendite" in st.modules]
    finally:
        db.close()
    result = {}
    for tid in tenants:
        db = session_factory()
        try:
            set_tenant(db, tid)
            if not sales.contracts_due(db, on):
                db.rollback()
                continue
            company = db.scalar(select(Company).order_by(Company.name))
            created = sales.generate_contract_invoices(db, tid, company.id, on)
            db.commit()
            result[str(tid)] = len(created)
        except Exception:  # noqa: BLE001 - si registra e si passa all'azienda successiva
            db.rollback()
            log.exception("Canoni ricorrenti: errore per l'azienda %s", tid)
            result[str(tid)] = "errore"
        finally:
            db.close()
    return result
