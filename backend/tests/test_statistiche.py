from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from tests.test_vendite import new, setup

ST = "/api/statistiche"


def confirm(client, h, d):
    r = client.post(f"/api/vendite/documenti/{d['id']}/conferma", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def test_fatturato_clienti_articoli_e_magazzino(client, admin_headers):
    h, cust, _, vite, _ = setup(client, admin_headers, "Statistiche Srl")
    today = date.today()
    last_year = today - relativedelta(years=1)
    # anno scorso: 50 € (stesso periodo)
    confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "doc_date": last_year.isoformat(),
                                       "lines": [{"description": "Servizio", "quantity": "1", "unit_price": "50"}]}))
    # quest'anno: fattura 10 viti a 9 € + servizio 10 €, nota di credito 1 vite
    confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "lines": [
        {"item_id": vite["id"], "quantity": "10"}, {"description": "Trasporto", "quantity": "1", "unit_price": "10"}]}))
    confirm(client, h, new(client, h, {"doc_type": "NC", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "1", "unit_price": "9"}]}))
    confirm(client, h, new(client, h, {"doc_type": "DDT", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "2"}]}))
    a = (today - relativedelta(days=today.timetuple().tm_yday - 1)).isoformat()
    r = client.get(f"{ST}/vendite?date_from={a}&date_to={today.isoformat()}", headers=h).json()
    assert Decimal(r["totals"]["revenue"]) == 91 and r["totals"]["invoices"] == 1 and r["totals"]["credit_notes"] == 1
    if last_year >= date.fromisoformat(a) - relativedelta(years=1):
        assert Decimal(r["previous"]["revenue"]) == 50
    assert Decimal(r["customers"][0]["revenue"]) == 91 and r["customers"][0]["name"] == "Cliente Rossi"
    vite_row = next(x for x in r["items"] if x["code"] == "VITE")
    assert Decimal(vite_row["quantity"]) == 9 and Decimal(vite_row["revenue"]) == 81
    assert any(x["description"].startswith("Righe libere") for x in r["items"])
    assert Decimal(r["ddt_to_invoice"]["amount"]) == 18 and r["ddt_to_invoice"]["count"] == 1
    assert sum(Decimal(m["revenue"]) for m in r["months"]) == 91
    # magazzino: 100 caricate − 10 vendute + 1 reso? (la NC senza rientro merce non carica) − 2 DDT = 88 a 4 €
    m = client.get(f"{ST}/magazzino", headers=h).json()
    assert Decimal(m["value"]) == Decimal("352.00")
    x = client.get(f"{ST}/excel?date_from={a}", headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"


def test_lotti_in_scadenza(client, admin_headers):
    h, _, sup, _, _ = setup(client, admin_headers, "Lotti Stat Srl")
    latte = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "LATTE", "description": "Latte", "lot_managed": True,
                                                                     "min_stock": "50"}).json()
    d = client.post("/api/acquisti/documenti", headers=h, json={"doc_type": "DDTF", "party_id": sup["id"], "external_number": "9", "lines": [
        {"item_id": latte["id"], "quantity": "20", "unit_price": "1", "lot_number": "L1", "expiry_date": (date.today() + timedelta(days=5)).isoformat()},
        {"item_id": latte["id"], "quantity": "10", "unit_price": "1", "lot_number": "L2", "expiry_date": (date.today() + timedelta(days=200)).isoformat()}]}).json()
    client.post(f"/api/acquisti/documenti/{d['id']}/conferma", headers=h)
    m = client.get(f"{ST}/magazzino?days=30", headers=h).json()
    assert [x["lot_number"] for x in m["expiring_lots"]] == ["L1"] and m["expiring_lots"][0]["days"] == 5
    assert any(x["code"] == "LATTE" for x in m["under_min"])
