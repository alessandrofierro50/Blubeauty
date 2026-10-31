from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from tests.conftest import activate_and_login, make_tenant
from tests.test_vendite import new, setup

BI = "/api/bi/vendite"


def confirm(client, h, d):
    r = client.post(f"/api/vendite/documenti/{d['id']}/conferma", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def q(client, h, **body):
    today = date.today()
    body.setdefault("date_from", today.replace(month=1, day=1).isoformat())
    body.setdefault("date_to", today.isoformat())
    return client.post(f"{BI}/query", headers=h, json=body)


def data(client, admin_headers, name):
    h, cust, _, vite, _ = setup(client, admin_headers, name)
    today = date.today()
    cat = client.post("/api/anagrafiche/tabelle/categorie", headers=h, json={"name": "Viteria"}).json()
    it = client.get(f"/api/anagrafiche/articoli/{vite['id']}", headers=h).json()
    it["category_id"] = cat["id"]
    assert client.put(f"/api/anagrafiche/articoli/{vite['id']}", headers=h, json=it).status_code == 200
    confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "doc_date": (today - relativedelta(years=1)).isoformat(),
                                       "lines": [{"description": "Servizio", "quantity": "1", "unit_price": "50"}]}))
    confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "lines": [
        {"item_id": vite["id"], "quantity": "10"}, {"description": "Trasporto", "quantity": "1", "unit_price": "10"}]}))
    confirm(client, h, new(client, h, {"doc_type": "NC", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "1", "unit_price": "9"}]}))
    return h, cust, vite, cat


def test_modello_misure_dimensioni_confronto(client, admin_headers):
    h, cust, vite, cat = data(client, admin_headers, "BI Srl")
    m = client.get(f"{BI}/modello", headers=h).json()
    assert {"fatturato", "margine"} <= {x["name"] for x in m["measures"]} and m["hierarchies"]["Tempo"][0] == "anno"
    r = q(client, h, measures=["fatturato", "documenti", "note_credito", "clienti", "fattura_media"], compare="anno_precedente").json()
    assert r["totals"] == {"fatturato": "91.00", "documenti": 1, "note_credito": 1, "clienti": 1, "fattura_media": "91.00"}
    assert r["totals_compare"]["fatturato"] == "50.00" and r["totals_delta"]["fatturato"] == "82.0"
    # per mese: il mese dell'anno scorso si allinea a quello di quest'anno
    r = q(client, h, measures=["fatturato"], dimensions=["mese"], compare="anno_precedente").json()
    cur_month = next(x for x in r["rows"] if x["dims"]["mese"]["key"] == date.today().strftime("%Y-%m"))
    assert cur_month["values"]["fatturato"] == "91.00" and cur_month["compare"]["fatturato"] == "50.00"
    # gerarchia prodotto: categoria → articolo, con le righe libere a parte
    r = q(client, h, measures=["fatturato", "quantita"], dimensions=["categoria_principale"]).json()
    by = {x["dims"]["categoria_principale"]["label"]: x["values"] for x in r["rows"]}
    assert by["Viteria"]["fatturato"] == "81.00" and by["Senza categoria"]["fatturato"] == "10.00"
    r = q(client, h, measures=["fatturato", "quantita", "prezzo_medio"], dimensions=["articolo"],
          filters={"categoria_principale": [cat["id"]]}).json()
    assert len(r["rows"]) == 1 and r["rows"][0]["values"] == {"fatturato": "81.00", "quantita": "9.000", "prezzo_medio": "9.00"}
    # filtro su «non indicato» (righe senza articolo)
    r = q(client, h, measures=["fatturato"], filters={"articolo": [None]}).json()
    assert r["totals"]["fatturato"] == "10.00"
    # drill-through: le righe che compongono il numero
    rows = client.post(f"{BI}/dettaglio", headers=h, json={"measures": ["fatturato"], "date_from": date.today().replace(month=1, day=1).isoformat(),
                                                           "date_to": date.today().isoformat(), "filters": {"articolo": [vite["id"]]}}).json()
    assert sorted(Decimal(x["revenue"]) for x in rows) == [Decimal(-9), Decimal(90)]
    # margine (pacchetto Pro): costo 4 € → 9 viti nette a 81 € = 45 € di margine
    r = q(client, h, measures=["margine", "margine_pct"], filters={"articolo": [vite["id"]]}).json()
    assert r["totals"]["margine"] == "45.00" and r["totals"]["margine_pct"] == "55.56"
    x = client.post(f"{BI}/excel", headers=h, json={"measures": ["fatturato"], "dimensions": ["cliente"], "date_from": "2026-01-01", "date_to": date.today().isoformat()})
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_limiti_base_e_validazione(client, admin_headers):
    t = make_tenant(client, admin_headers, "BI Base Srl", plan="BASE")
    h = activate_and_login(client, t)
    r = q(client, h, measures=["margine"])
    assert r.status_code == 422 and "Pro" in r.json()["detail"]
    assert q(client, h, measures=["fatturato"], dimensions=["mese", "cliente", "articolo"]).status_code == 422
    assert q(client, h, measures=["fatturato"], dimensions=["x; drop table documents"]).status_code == 422
    assert q(client, h, measures=["fatturato"], filters={"cliente": ["non-un-uuid"]}).status_code == 422
    assert q(client, h, measures=["fatturato"]).json()["totals"]["fatturato"] == "0.00"


def test_isolamento_tra_aziende(client, admin_headers):
    data(client, admin_headers, "BI Uno Srl")
    t = make_tenant(client, admin_headers, "BI Due Srl", plan="PRO")
    h2 = activate_and_login(client, t)
    r = q(client, h2, measures=["fatturato", "righe"]).json()
    assert r["totals"] == {"fatturato": "0.00", "righe": 0}
