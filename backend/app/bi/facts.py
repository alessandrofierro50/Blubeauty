"""Cubi del pacchetto Pro: acquisti, scadenze (crediti e debiti), preventivi e ordini, movimenti di magazzino.

Stesso motore e stesse regole delle vendite (app/bi/engine.py); il registro CUBES è l'elenco unico usato dalle API,
dal report builder e dagli invii programmati."""

from sqlalchemy import Boolean, Column, Date, Integer, MetaData, Numeric, String, Table, case, func, literal
from sqlalchemy.dialects.postgresql import UUID

from app.bi.cube import SALES
from app.bi.engine import Cube, Dimension, Measure, div, time_dimensions

meta = MetaData()
U = lambda name: Column(name, UUID(as_uuid=True))  # noqa: E731
S = lambda name: Column(name, String)  # noqa: E731
N = lambda name: Column(name, Numeric)  # noqa: E731


def product_dims(t) -> list[Dimension]:
    c = t.c
    return [
        Dimension("categoria_principale", "Categoria", "Prodotto", lambda dd: c.root_category_id, lambda dd: c.root_category_name,
                  child="categoria", empty="Senza categoria", kind="uuid"),
        Dimension("categoria", "Sottocategoria", "Prodotto", lambda dd: c.category_id, lambda dd: c.category_name, child="articolo",
                  empty="Senza categoria", kind="uuid"),
        Dimension("marca", "Marca", "Prodotto", lambda dd: c.brand_id, lambda dd: c.brand_name, child="articolo", empty="Senza marca", kind="uuid"),
        Dimension("articolo", "Articolo", "Prodotto", lambda dd: c.item_id,
                  lambda dd: func.coalesce(c.item_code + literal(" · ") + c.item_description, literal("Righe libere (servizi, spese)")),
                  empty="Righe libere (servizi, spese)", kind="uuid"),
    ]


# ====================================================================== acquisti

P = Table("bi_purchases", meta, U("line_id"), U("tenant_id"), U("document_id"), S("doc_type"), Column("doc_number", Integer), S("external_number"),
          Column("doc_year", Integer), Column("doc_date", Date), U("party_id"), S("party_name"), S("party_province"), U("item_id"), S("item_code"),
          S("item_description"), U("category_id"), S("category_name"), U("root_category_id"), S("root_category_name"), U("brand_id"),
          S("brand_name"), U("warehouse_id"), S("warehouse_name"), S("line_description"), S("unit"), N("quantity"), N("amount"))
p = P.c
PURCHASES = Cube(
    name="acquisti", label="Acquisti", description="Righe delle fatture e note di credito dei fornitori (imponibile)", table=P, date_col="doc_date",
    date_label="Data della fattura", pro=True, default_measure="spesa",
    dimensions={d.name: d for d in [
        *time_dimensions(),
        Dimension("fornitore", "Fornitore", "Fornitore", lambda dd: p.party_id, lambda dd: p.party_name, child="documento", kind="uuid"),
        Dimension("provincia", "Provincia", "Fornitore", lambda dd: p.party_province, child="fornitore"),
        *product_dims(P),
        Dimension("magazzino", "Magazzino", "Documento", lambda dd: p.warehouse_id, lambda dd: p.warehouse_name, kind="uuid"),
        Dimension("tipo_documento", "Tipo documento", "Documento", lambda dd: p.doc_type, labels={"FTF": "Fattura", "NCF": "Nota di credito"}),
        Dimension("documento", "Documento", "Documento", lambda dd: p.document_id,
                  lambda dd: func.coalesce(literal("n. ") + p.external_number, literal("")), kind="uuid"),
    ]},
    measures={m.name: m for m in [
        Measure("spesa", "Spesa", "euro", lambda: func.coalesce(func.sum(p.amount), 0), hint="Imponibile: fatture meno note di credito"),
        Measure("quantita", "Quantità", "numero", lambda: func.coalesce(func.sum(p.quantity), 0)),
        Measure("documenti", "Fatture", "intero", lambda: func.count(func.distinct(case((p.doc_type == "FTF", p.document_id))))),
        Measure("fornitori", "Fornitori", "intero", lambda: func.count(func.distinct(p.party_id))),
        Measure("articoli", "Articoli acquistati", "intero", lambda: func.count(func.distinct(p.item_id))),
        Measure("costo_medio", "Costo medio unitario", "euro", derived=lambda v: div(v["spesa"], v["quantita"]), needs=["spesa", "quantita"]),
        Measure("costo_min", "Costo unitario minimo", "euro", lambda: func.min(case((p.quantity > 0, p.amount / p.quantity)))),
        Measure("costo_max", "Costo unitario massimo", "euro", lambda: func.max(case((p.quantity > 0, p.amount / p.quantity)))),
    ]},
    hierarchies={"Tempo": ["anno", "trimestre", "mese", "giorno"], "Prodotto": ["categoria_principale", "categoria", "articolo"],
                 "Fornitore": ["fornitore", "documento"]},
    detail_cols=[("document_id", "document_id", "id"), ("doc_type", "doc_type", "str"), ("external_number", "external_number", "str"),
                 ("date", "doc_date", "date"), ("party", "party_name", "str"), ("item_code", "item_code", "str"),
                 ("description", "line_description", "str"), ("quantity", "quantity", "numero"), ("unit", "unit", "str"), ("amount", "amount", "euro")],
    detail_label=lambda r: f"{'Fattura' if r['doc_type'] == 'FTF' else 'Nota di credito'} {r['external_number'] or ''}".strip(),
)

# ====================================================================== scadenze

I = Table("bi_installments", meta, U("installment_id"), U("tenant_id"), S("direction"), U("party_id"), S("party_name"), S("party_province"),
          U("document_id"), S("doc_type"), Column("doc_number", Integer), S("external_number"), Column("doc_year", Integer),
          Column("issue_date", Date), Column("due_date", Date), N("amount"), N("paid_amount"), N("residual"), S("status"),
          Column("unpaid", Boolean), S("method"), U("account_id"), S("account_name"), Column("reminder_level", Integer), S("description"),
          Column("last_payment_date", Date), N("overdue"), Column("delay_days", Integer))
i = I.c
STATUS = {"aperta": "Da incassare/pagare", "parziale": "Parziale", "pagata": "Saldata", "insoluta": "Insoluta"}
RECEIVABLES = Cube(
    name="scadenze", label="Scadenze, crediti e debiti", description="Rate delle fatture e scadenze manuali: incassato, residuo, scaduto, ritardi",
    table=I, date_col="due_date", date_label="Data di scadenza", pro=True, default_measure="residuo",
    dimensions={d.name: d for d in [
        *time_dimensions(),
        Dimension("direzione", "Clienti o fornitori", "Scadenza", lambda dd: i.direction, labels={"attiva": "Crediti verso clienti", "passiva": "Debiti verso fornitori"}),
        Dimension("soggetto", "Cliente / fornitore", "Scadenza", lambda dd: i.party_id, lambda dd: i.party_name, child="documento", kind="uuid"),
        Dimension("provincia", "Provincia", "Scadenza", lambda dd: i.party_province, child="soggetto"),
        Dimension("stato", "Stato", "Scadenza", lambda dd: i.status, labels=STATUS),
        Dimension("metodo", "Metodo di pagamento", "Scadenza", lambda dd: i.method),
        Dimension("conto", "Conto", "Scadenza", lambda dd: i.account_id, lambda dd: i.account_name, empty="Nessun conto", kind="uuid"),
        Dimension("sollecito", "Livello di sollecito", "Scadenza", lambda dd: i.reminder_level, kind="int",
                  labels={"0": "Nessun sollecito", "1": "1° sollecito", "2": "2° sollecito", "3": "3° sollecito"}),
        Dimension("documento", "Documento", "Scadenza", lambda dd: i.document_id,
                  lambda dd: func.coalesce(i.doc_type + literal(" ") + func.coalesce(i.external_number, func.cast(i.doc_number, String)), i.description),
                  empty="Scadenze manuali", kind="uuid"),
    ]},
    measures={m.name: m for m in [
        Measure("importo", "Importo", "euro", lambda: func.coalesce(func.sum(i.amount), 0)),
        Measure("incassato", "Incassato / pagato", "euro", lambda: func.coalesce(func.sum(i.paid_amount), 0)),
        Measure("residuo", "Residuo", "euro", lambda: func.coalesce(func.sum(i.residual), 0)),
        Measure("scaduto", "Scaduto", "euro", lambda: func.coalesce(func.sum(i.overdue), 0), hint="Residuo con scadenza passata"),
        Measure("insoluti", "Insoluti", "euro", lambda: func.coalesce(func.sum(i.residual).filter(i.unpaid), 0)),
        Measure("scadenze", "Scadenze", "intero", lambda: func.count()),
        Measure("soggetti", "Clienti / fornitori", "intero", lambda: func.count(func.distinct(i.party_id))),
        Measure("ritardo_medio", "Ritardo medio (giorni)", "giorni", lambda: func.avg(i.delay_days),
                hint="Saldate: giorni fra scadenza e ultimo incasso; aperte scadute: giorni da oggi"),
        Measure("incassato_pct", "Incassato %", "percento", derived=lambda v: div(v["incassato"] * 100, v["importo"]), needs=["incassato", "importo"]),
    ]},
    hierarchies={"Tempo": ["anno", "trimestre", "mese", "giorno"], "Soggetto": ["direzione", "soggetto", "documento"]},
    detail_cols=[("document_id", "document_id", "id"), ("doc_type", "doc_type", "str"), ("doc_number", "doc_number", "raw"),
                 ("external_number", "external_number", "str"), ("doc_year", "doc_year", "raw"), ("date", "due_date", "date"),
                 ("party", "party_name", "str"), ("description", "description", "str"), ("status", "status", "str"),
                 ("amount", "amount", "euro"), ("residual", "residual", "euro")],
    detail_label=lambda r: (f"{r['doc_type']} {r['external_number'] or r['doc_number']}" if r["doc_type"] else (r["description"] or "Scadenza")),
)

# ====================================================================== preventivi e ordini

Q = Table("bi_pipeline", meta, U("document_id"), U("tenant_id"), S("doc_type"), Column("doc_number", Integer), Column("doc_year", Integer),
          Column("doc_date", Date), S("status"), U("party_id"), S("party_name"), S("party_province"), U("created_by"), S("seller_name"),
          N("amount"), Column("converted", Boolean), N("open_amount"), Column("lead_days", Integer))
q = Q.c
PIPELINE = Cube(
    name="ordini", label="Preventivi e ordini", description="Preventivi e ordini dei clienti: conversione, ordini inevasi, tempi di evasione",
    table=Q, date_col="doc_date", date_label="Data del documento", pro=True, default_measure="valore",
    dimensions={d.name: d for d in [
        *time_dimensions(),
        Dimension("tipo_documento", "Tipo", "Documento", lambda dd: q.doc_type, labels={"PRV": "Preventivi", "ORC": "Ordini"}),
        Dimension("stato", "Stato", "Documento", lambda dd: q.doc_type + literal(":") + q.status,
                  labels={"PRV:confermato": "Preventivo inviato", "PRV:evaso": "Preventivo accettato", "PRV:annullato": "Preventivo rifiutato",
                          "ORC:confermato": "Ordine aperto", "ORC:evaso": "Ordine evaso", "ORC:annullato": "Ordine annullato"}),
        Dimension("cliente", "Cliente", "Cliente", lambda dd: q.party_id, lambda dd: q.party_name, child="documento", kind="uuid"),
        Dimension("provincia", "Provincia", "Cliente", lambda dd: q.party_province, child="cliente"),
        Dimension("venditore", "Inserito da", "Documento", lambda dd: q.created_by, lambda dd: q.seller_name, kind="uuid"),
        Dimension("documento", "Documento", "Documento", lambda dd: q.document_id,
                  lambda dd: q.doc_type + literal(" ") + func.cast(q.doc_number, String) + literal("/") + func.cast(q.doc_year, String), kind="uuid"),
    ]},
    measures={m.name: m for m in [
        Measure("valore", "Valore", "euro", lambda: func.coalesce(func.sum(q.amount), 0), hint="Imponibile dei documenti"),
        Measure("documenti", "Documenti", "intero", lambda: func.count()),
        Measure("convertiti", "Accettati / evasi", "intero", lambda: func.count().filter(q.converted)),
        Measure("valore_convertito", "Valore accettato / evaso", "euro", lambda: func.coalesce(func.sum(q.amount).filter(q.converted), 0)),
        Measure("conversione", "Tasso di conversione", "percento", derived=lambda v: div(v["convertiti"] * 100, v["documenti"]), needs=["convertiti", "documenti"]),
        Measure("inevaso", "Ordinato da evadere", "euro", lambda: func.coalesce(func.sum(q.open_amount), 0)),
        Measure("giorni_medi", "Giorni medi di evasione", "giorni", lambda: func.avg(q.lead_days),
                hint="Dal preventivo all'ordine o dall'ordine al DDT/fattura"),
        Measure("clienti", "Clienti", "intero", lambda: func.count(func.distinct(q.party_id))),
    ]},
    hierarchies={"Tempo": ["anno", "trimestre", "mese", "giorno"], "Cliente": ["provincia", "cliente", "documento"]},
    detail_cols=[("document_id", "document_id", "id"), ("doc_type", "doc_type", "str"), ("doc_number", "doc_number", "raw"),
                 ("doc_year", "doc_year", "raw"), ("date", "doc_date", "date"), ("party", "party_name", "str"), ("status", "status", "str"),
                 ("amount", "amount", "euro"), ("open_amount", "open_amount", "euro"), ("lead_days", "lead_days", "raw")],
    detail_label=lambda r: f"{'Preventivo' if r['doc_type'] == 'PRV' else 'Ordine'} {r['doc_number']}/{r['doc_year']}",
)

# ====================================================================== movimenti di magazzino

REASONS = {"carico": "Carico", "scarico": "Scarico", "rettifica": "Rettifica", "inventario": "Inventario", "trasferimento": "Trasferimento",
           "acquisto": "Acquisto", "reso_fornitore": "Reso a fornitore", "vendita": "Vendita", "reso_cliente": "Reso da cliente",
           "omaggio": "Omaggio", "scarto": "Scarto / deperimento"}
M = Table("bi_stock_moves", meta, U("move_id"), U("tenant_id"), Column("move_date", Date), U("warehouse_id"), S("warehouse_name"), U("item_id"),
          S("item_code"), S("item_description"), U("category_id"), S("category_name"), U("root_category_id"), S("root_category_name"),
          U("brand_id"), S("brand_name"), S("unit"), S("reason"), U("party_id"), S("party_name"), S("document_type"), U("document_id"),
          N("quantity"), N("value"))
m = M.c
STOCK = Cube(
    name="magazzino", label="Movimenti di magazzino", description="Carichi e scarichi per causale, valorizzati al costo", table=M,
    date_col="move_date", date_label="Data del movimento", pro=True, default_measure="scarichi",
    dimensions={d.name: d for d in [
        *time_dimensions(),
        Dimension("magazzino", "Magazzino", "Magazzino", lambda dd: m.warehouse_id, lambda dd: m.warehouse_name, kind="uuid"),
        Dimension("causale", "Causale", "Magazzino", lambda dd: m.reason, labels=REASONS),
        *[d for d in product_dims(M) if d.name != "articolo"],
        Dimension("articolo", "Articolo", "Prodotto", lambda dd: m.item_id, lambda dd: m.item_code + literal(" · ") + m.item_description, kind="uuid"),
        Dimension("soggetto", "Cliente / fornitore", "Magazzino", lambda dd: m.party_id, lambda dd: m.party_name, empty="Nessuno", kind="uuid"),
    ]},
    measures={x.name: x for x in [
        Measure("carichi", "Quantità caricata", "numero", lambda: func.coalesce(func.sum(m.quantity).filter(m.quantity > 0), 0)),
        Measure("scarichi", "Quantità scaricata", "numero", lambda: func.coalesce(-func.sum(m.quantity).filter(m.quantity < 0), 0)),
        Measure("saldo", "Variazione di giacenza", "numero", lambda: func.coalesce(func.sum(m.quantity), 0)),
        Measure("valore_carichi", "Valore caricato", "euro", lambda: func.coalesce(func.sum(m.value).filter(m.quantity > 0), 0)),
        Measure("valore_scarichi", "Valore scaricato", "euro", lambda: func.coalesce(-func.sum(m.value).filter(m.quantity < 0), 0)),
        Measure("movimenti", "Movimenti", "intero", lambda: func.count()),
        Measure("articoli", "Articoli movimentati", "intero", lambda: func.count(func.distinct(m.item_id))),
    ]},
    hierarchies={"Tempo": ["anno", "trimestre", "mese", "giorno"], "Prodotto": ["categoria_principale", "categoria", "articolo"]},
    detail_cols=[("document_id", "document_id", "id"), ("doc_type", "document_type", "str"), ("date", "move_date", "date"),
                 ("reason", "reason", "str"), ("party", "party_name", "str"), ("item_code", "item_code", "str"),
                 ("description", "item_description", "str"), ("quantity", "quantity", "numero"), ("unit", "unit", "str"), ("amount", "value", "euro")],
    detail_label=lambda r: REASONS.get(r["reason"], r["reason"]),
)

CUBES: dict[str, Cube] = {c.name: c for c in (SALES, PURCHASES, RECEIVABLES, PIPELINE, STOCK)}
