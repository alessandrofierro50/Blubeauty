"""Modello semantico delle vendite (Business Intelligence).

Fatto: bi_sales (una riga per riga fatturata). Dimensioni con chiave + etichetta, raggruppate in gerarchie per il
drill-down; misure additive (somme, conteggi distinti) e derivate (rapporti calcolati sui totali, mai sommati).
Le interrogazioni si costruiscono solo da nomi presenti in questo modello: nessun testo libero arriva all'SQL."""

from sqlalchemy import Boolean, Column, Date, Integer, MetaData, Numeric, String, Table, case, cast, func, literal
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Session

from app.bi import engine
from app.bi.engine import Cube, Dimension, Measure, Query, QueryError, div, time_dimensions

meta = MetaData()
F = Table(
    "bi_sales", meta,
    Column("line_id", UUID(as_uuid=True)), Column("tenant_id", UUID(as_uuid=True)), Column("document_id", UUID(as_uuid=True)),
    Column("doc_type", String), Column("doc_number", Integer), Column("doc_year", Integer), Column("doc_date", Date),
    Column("channel", String), Column("party_id", UUID(as_uuid=True)), Column("party_name", String), Column("party_city", String),
    Column("party_province", String), Column("customer_category_id", UUID(as_uuid=True)), Column("customer_category", String),
    Column("item_id", UUID(as_uuid=True)), Column("item_code", String), Column("item_description", String),
    Column("category_id", UUID(as_uuid=True)), Column("category_name", String), Column("root_category_id", UUID(as_uuid=True)),
    Column("root_category_name", String), Column("brand_id", UUID(as_uuid=True)), Column("brand_name", String),
    Column("warehouse_id", UUID(as_uuid=True)), Column("warehouse_name", String), Column("line_description", String),
    Column("unit", String), Column("quantity", Numeric), Column("revenue", Numeric), Column("cost", Numeric),
    Column("missing_cost", Boolean), Column("department_id", UUID(as_uuid=True)), Column("department_name", String),
    Column("register_id", UUID(as_uuid=True)), Column("register_name", String), Column("cashier_id", UUID(as_uuid=True)),
    Column("cashier_name", String), Column("sale_hour", Integer), Column("is_promo", Boolean),
    Column("van_id", UUID(as_uuid=True)), Column("van_name", String), Column("agent_id", UUID(as_uuid=True)), Column("agent_name", String),
)
c = F.c


DOC_TYPE_LABEL = {"FTI": "Fattura", "FTD": "Fattura differita", "NC": "Nota di credito", "SCO": "Scontrino", "RSO": "Reso al banco"}

DIMENSIONS: dict[str, Dimension] = {d.name: d for d in [
    *time_dimensions(),
    Dimension("provincia", "Provincia", "Cliente", lambda dd: c.party_province, child="cliente"),
    Dimension("citta", "Città", "Cliente", lambda dd: c.party_city, child="cliente"),
    Dimension("categoria_cliente", "Categoria cliente", "Cliente", lambda dd: c.customer_category_id,
              lambda dd: c.customer_category, child="cliente", kind="uuid"),
    Dimension("cliente", "Cliente", "Cliente", lambda dd: c.party_id, lambda dd: c.party_name, child="documento", kind="uuid"),
    Dimension("categoria_principale", "Categoria", "Prodotto", lambda dd: c.root_category_id, lambda dd: c.root_category_name,
              child="categoria", empty="Senza categoria", kind="uuid"),
    Dimension("categoria", "Sottocategoria", "Prodotto", lambda dd: c.category_id, lambda dd: c.category_name, child="articolo",
              empty="Senza categoria", kind="uuid"),
    Dimension("marca", "Marca", "Prodotto", lambda dd: c.brand_id, lambda dd: c.brand_name, child="articolo", empty="Senza marca", kind="uuid"),
    Dimension("articolo", "Articolo", "Prodotto", lambda dd: c.item_id,
              lambda dd: func.coalesce(c.item_code + literal(" · ") + c.item_description, literal("Righe libere (servizi, spese)"), kind="uuid"),
              empty="Righe libere (servizi, spese)"),
    Dimension("magazzino", "Magazzino", "Documento", lambda dd: c.warehouse_id, lambda dd: c.warehouse_name, kind="uuid"),
    Dimension("tipo_documento", "Tipo documento", "Documento", lambda dd: c.doc_type, labels=DOC_TYPE_LABEL),
    Dimension("canale", "Canale", "Documento", lambda dd: c.channel, labels={"fattura": "Fatture", "banco": "Vendita al banco", "online": "Negozio online",
                                                                                         "furgone": "Tentata vendita (furgoni)"}),
    Dimension("agente", "Agente", "Agenti", lambda dd: c.agent_id, lambda dd: c.agent_name, child="cliente", empty="Senza agente", kind="uuid"),
    Dimension("furgone", "Furgone", "Agenti", lambda dd: c.van_id, lambda dd: c.van_name, child="cliente", empty="Senza furgone", kind="uuid"),
    Dimension("reparto", "Reparto", "Banco", lambda dd: c.department_id, lambda dd: c.department_name, child="articolo", empty="Senza reparto", kind="uuid"),
    Dimension("cassa", "Cassa", "Banco", lambda dd: c.register_id, lambda dd: c.register_name, child="cassiere", empty="Fuori dalla cassa", kind="uuid"),
    Dimension("cassiere", "Cassiere", "Banco", lambda dd: c.cashier_id, lambda dd: c.cashier_name, child="documento", empty="Non indicato", kind="uuid"),
    Dimension("fascia_oraria", "Fascia oraria", "Banco", lambda dd: c.sale_hour, kind="int"),
    Dimension("documento", "Documento", "Documento", lambda dd: c.document_id,
              lambda dd: c.doc_type + literal(" ") + cast(c.doc_number, String) + literal("/") + cast(c.doc_year, String), kind="uuid"),
]}

HIERARCHIES = {
    "Tempo": ["anno", "trimestre", "mese", "giorno"],
    "Prodotto": ["categoria_principale", "categoria", "articolo"],
    "Cliente": ["provincia", "cliente", "documento"],
    "Banco": ["cassa", "cassiere", "documento"],
    "Agenti": ["agente", "cliente", "documento"],
}
MEASURES: dict[str, Measure] = {m.name: m for m in [
    Measure("fatturato", "Fatturato", "euro", lambda: func.coalesce(func.sum(c.revenue), 0), hint="Imponibile: fatture meno note di credito"),
    Measure("quantita", "Quantità", "numero", lambda: func.coalesce(func.sum(c.quantity).filter(~c.is_promo), 0)),
    Measure("documenti", "Vendite", "intero", lambda: func.count(func.distinct(case((c.doc_type.not_in(("NC", "RSO")), c.document_id))))),
    Measure("note_credito", "Note di credito e resi", "intero", lambda: func.count(func.distinct(case((c.doc_type.in_(("NC", "RSO")), c.document_id))))),
    Measure("clienti", "Clienti", "intero", lambda: func.count(func.distinct(c.party_id))),
    Measure("articoli", "Articoli venduti", "intero", lambda: func.count(func.distinct(c.item_id))),
    Measure("righe", "Righe", "intero", lambda: func.count()),
    Measure("sconti_promo", "Sconti delle promozioni di cassa", "euro", lambda: -func.coalesce(func.sum(c.revenue).filter(c.is_promo), 0),
            hint="Imponibile scontato da 3x2, N-esimo pezzo e soglie di spesa"),
    Measure("fattura_media", "Vendita media", "euro", derived=lambda v: div(v["fatturato"], v["documenti"]), needs=["fatturato", "documenti"]),
    Measure("prezzo_medio", "Prezzo medio", "euro", derived=lambda v: div(v["fatturato"], v["quantita"]), needs=["fatturato", "quantita"]),
    Measure("costo", "Costo del venduto", "euro", lambda: func.coalesce(func.sum(c.cost), 0), pro=True),
    Measure("margine", "Margine", "euro", lambda: func.coalesce(func.sum(c.revenue - c.cost), 0), pro=True),
    Measure("margine_pct", "Margine %", "percento", derived=lambda v: div(v["margine"] * 100, v["fatturato"]), needs=["margine", "fatturato"], pro=True),
    Measure("righe_senza_costo", "Righe senza costo", "intero", lambda: func.count().filter(c.missing_cost), pro=True),
]}



SALES = Cube(
    name="vendite", label="Vendite", description="Righe di fatture, note di credito, scontrini e resi al banco (imponibile)",
    table=F, date_col="doc_date", dimensions=DIMENSIONS, measures=MEASURES, hierarchies=HIERARCHIES, default_measure="fatturato",
    date_label="Data del documento",
    detail_cols=[("document_id", "document_id", "id"), ("doc_type", "doc_type", "str"), ("doc_number", "doc_number", "raw"),
                 ("doc_year", "doc_year", "raw"), ("date", "doc_date", "date"), ("party", "party_name", "str"), ("item_code", "item_code", "str"),
                 ("description", "line_description", "str"), ("quantity", "quantity", "numero"), ("unit", "unit", "str"),
                 ("revenue", "revenue", "euro")],
    detail_label=lambda r: f"{DOC_TYPE_LABEL.get(r['doc_type'], r['doc_type'])} {r['doc_number']}/{r['doc_year']}",
)


# compatibilità: interfaccia del modulo usata finora (vendite)
def model(pro: bool) -> dict:
    return engine.model(SALES, pro)


def execute(db: Session, q: Query, pro: bool) -> dict:
    return engine.execute(SALES, db, q, pro)


def detail(db: Session, q: Query, limit: int = 300) -> list[dict]:
    return engine.detail(SALES, db, q, True, limit)


__all__ = ["DIMENSIONS", "MEASURES", "HIERARCHIES", "Query", "QueryError", "execute", "detail", "model", "SALES"]
