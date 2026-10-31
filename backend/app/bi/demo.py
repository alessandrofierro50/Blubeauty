"""Report e dashboard di esempio per le aziende demo col pacchetto Pro."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bi.facts import CUBES
from app.bi.models import Dashboard, SavedReport
from app.bi.reports import clean_config
from app.core.db import set_tenant
from app.core.models import User

DEMO = [
    ("Fatturato mensile con confronto", "vendite", {"rows": ["mese"], "measures": ["fatturato", "margine"], "period": {"kind": "ultimi_12_mesi"},
                                                    "compare": "anno_precedente", "chart": "barre"}, "grafico", 4),
    ("Numeri del mese", "vendite", {"rows": [], "measures": ["fatturato", "margine_pct", "documenti", "clienti"], "period": {"kind": "mese_corrente"},
                                    "compare": "periodo_precedente", "chart": "kpi"}, "kpi", 2),
    ("Crediti da incassare per cliente", "scadenze", {"rows": ["soggetto"], "measures": ["residuo", "scaduto", "ritardo_medio"],
                                                      "filters": {"direzione": ["attiva"]}, "period": {"kind": "ampio"},
                                                      "chart": "tabella", "sort": "residuo"}, "tabella", 2),
    ("Vendite per categoria", "vendite", {"rows": ["categoria_principale"], "measures": ["fatturato"], "period": {"kind": "anno_corrente"}, "chart": "torta"}, "grafico", 2),
    ("Categorie per trimestre", "vendite", {"rows": ["categoria_principale"], "columns": "trimestre", "measures": ["fatturato"],
                                            "period": {"kind": "ultimi_12_mesi"}, "chart": "tabella"}, "tabella", 2),
    ("Acquisti per fornitore", "acquisti", {"rows": ["fornitore"], "measures": ["spesa", "documenti"], "period": {"kind": "anno_corrente"}, "chart": "tabella"}, None, 0),
    ("Conversione dei preventivi", "ordini", {"rows": ["mese"], "measures": ["documenti", "conversione", "inevaso"], "filters": {"tipo_documento": ["PRV"]},
                                              "period": {"kind": "ultimi_12_mesi"}, "chart": "tabella"}, None, 0),
]


def load_bi_demo(db: Session, tenant_id: uuid.UUID) -> None:
    set_tenant(db, tenant_id)
    if db.scalar(select(SavedReport.id).limit(1)):
        return
    owner = db.scalar(select(User).where(User.tenant_id == tenant_id).order_by(User.created_at))
    widgets = []
    for name, cube, cfg, view, width in DEMO:
        r = SavedReport(tenant_id=tenant_id, name=name, cube=cube, config=clean_config(CUBES[cube], cfg, True), owner_id=owner.id if owner else None,
                        shared=True, schedule={})
        db.add(r)
        db.flush()
        if view:
            widgets.append({"report_id": str(r.id), "width": width, "view": view})
    db.add(Dashboard(tenant_id=tenant_id, name="Andamento aziendale", owner_id=owner.id if owner else None, shared=True, widgets=widgets))
    db.flush()
