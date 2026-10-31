import uuid
from datetime import date
from decimal import Decimal

from app.pos.service import parse_scale_barcode, DEFAULT_SETTINGS
from tests.conftest import activate_and_login, make_tenant
from tests.test_magazzino import stock

P = "/api/pos"
A = "/api/acquisti"
SC = "/api/scadenzario"


def setup(client, admin_headers, name, plan="PLUS"):
    t = make_tenant(client, admin_headers, name, plan=plan, sector="Alimentari", vat_number="02345670984")
    h = activate_and_login(client, t)
    lists = {p["code"]: p["id"] for p in client.get("/api/anagrafiche/tabelle/listini", headers=h).json()}
    vats = {v["code"]: v["id"] for v in client.get("/api/anagrafiche/tabelle/aliquote-iva", headers=h).json()}
    sup = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Grossista", "is_customer": False, "is_supplier": True, "vat_number": "01114601006"}).json()
    pane = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "PANE", "description": "Pane casereccio", "unit": "KG", "vat_rate_id": vats["4"], "plu": "123", "sold_by_weight": True,
        "prices": [{"price_list_id": lists["PUBBLICO"], "price": "3.50"}]})
    assert pane.status_code == 201, pane.text
    pane = pane.json()
    acqua = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "ACQUA", "description": "Acqua naturale 1,5 l", "barcodes": [{"barcode": "8001234567897"}],
        "prices": [{"price_list_id": lists["PUBBLICO"], "price": "0.40"}]})
    assert acqua.status_code == 201, acqua.text
    acqua = acqua.json()
    r = client.post(f"{A}/documenti", headers=h, json={"doc_type": "DDTF", "party_id": sup["id"], "external_number": "1", "lines": [
        {"item_id": pane["id"], "quantity": "50", "unit_price": "1.20"}, {"item_id": acqua["id"], "quantity": "100", "unit_price": "0.15"}]})
    assert client.post(f"{A}/documenti/{r.json()['id']}/conferma", headers=h).status_code == 200
    whs = client.get("/api/magazzino/magazzini", headers=h).json()["rows"]
    cassa = client.post(f"{SC}/conti", headers=h, json={"name": "Cassa negozio", "kind": "cassa", "opening_balance": "0"}).json()
    banca = client.post(f"{SC}/conti", headers=h, json={"name": "Banca", "kind": "banca", "opening_balance": "0"}).json()
    dep = client.post(f"{P}/reparti", headers=h, json={"code": "ORTO", "name": "Ortofrutta", "vat_rate_id": vats["4"]})
    assert dep.status_code == 201, dep.text
    reg = client.post(f"{P}/casse", headers=h, json={"code": "C1", "name": "Cassa 1", "warehouse_id": whs[0]["id"], "mode": "supermercato",
                                                     "cash_account_id": cassa["id"], "card_account_id": banca["id"],
                                                     "quick_keys": [{"type": "department", "id": dep.json()["id"], "label": "Frutta"}]})
    assert reg.status_code == 201, reg.text
    return h, reg.json(), pane, acqua, dep.json(), cassa, banca


def qty(client, h, item):
    return Decimal(stock(client, h, item["id"])["warehouses"][0]["on_hand"])


def sale(client, h, reg, lines, payments, **kw):
    return client.post(f"{P}/casse/{reg['id']}/vendite", headers=h, json={"client_uuid": str(uuid.uuid4()), "lines": lines, "payments": payments, **kw})


def test_codici_bilancia():
    cfg = {"scale_barcode": DEFAULT_SETTINGS["scale_barcode"]}
    sc = parse_scale_barcode("2100123012504", cfg)  # PLU 00123, 1,250 kg
    assert sc.plu == "123" and sc.quantity == Decimal("1.25")
    assert parse_scale_barcode("8001234567897", cfg) is None
    cfg2 = {"scale_barcode": {**DEFAULT_SETTINGS["scale_barcode"], "value": "prezzo"}}
    assert parse_scale_barcode("2100123004378", cfg2).amount == Decimal("4.37")


def test_modulo_solo_plus(client, admin_headers):
    t = make_tenant(client, admin_headers, "Base Pos", plan="BASE")
    h = activate_and_login(client, t)
    assert client.get(f"{P}/casse", headers=h).status_code == 403


def test_scontrino_resto_resi_e_chiusura(client, admin_headers):
    h, reg, pane, acqua, dep, cassa, banca = setup(client, admin_headers, "Market Srl")
    # catalogo con prezzi al pubblico IVA inclusa e codici
    cat = client.get(f"{P}/casse/{reg['id']}/catalogo", headers=h).json()
    by = {i["code"]: i for i in cat["items"]}
    assert by["PANE"]["price"] == "3.50" and by["ACQUA"]["barcodes"][0]["code"] == "8001234567897"
    assert client.get(f"{P}/casse/{reg['id']}/codice?code=8001234567897", headers=h).json()["item_id"] == acqua["id"]
    w = client.get(f"{P}/casse/{reg['id']}/codice?code=2100123012504", headers=h).json()
    assert w["item_id"] == pane["id"] and Decimal(w["quantity"]) == Decimal("1.25")
    # senza apertura non si vende
    assert sale(client, h, reg, [{"item_id": acqua["id"], "unit_price_gross": "0.40"}], [{"method": "contanti", "amount": "1"}]).status_code == 409
    ses = client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={"opening_float": "100"}).json()
    assert client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={}).status_code == 409
    lines = [{"item_id": pane["id"], "quantity": "1.25", "unit_price_gross": "3.50"},  # 4,375 → 4,38
             {"item_id": acqua["id"], "quantity": "6", "unit_price_gross": "0.40"},
             {"department_id": dep["id"], "unit_price_gross": "2.15"}]
    cid = str(uuid.uuid4())
    body = {"client_uuid": cid, "lines": lines, "payments": [{"method": "contanti", "amount": "10"}]}
    r = client.post(f"{P}/casse/{reg['id']}/vendite", headers=h, json=body)
    assert r.status_code == 200, r.text
    sco = r.json()
    assert sco["doc_type"] == "SCO" and sco["number"] == 1 and sco["party_name"] == "Cliente al banco"
    assert Decimal(sco["total"]) == Decimal("8.93") and Decimal(sco["change"]) == Decimal("1.07")
    assert sum(Decimal(v["taxable"]) + Decimal(v["vat"]) for v in sco["vat_summary"]) == Decimal("8.93")
    assert sco["payments"][0]["amount"] == "8.93" and sco["payments"][0]["tendered"] == "10.00"
    # rimandata (rete caduta): nessun doppione
    again = client.post(f"{P}/casse/{reg['id']}/vendite", headers=h, json=body).json()
    assert again["id"] == sco["id"] and again["replayed"] is True
    assert qty(client, h, pane) == Decimal("48.75") and qty(client, h, acqua) == 94
    # pagamento misto: il resto solo sul contante
    bad = sale(client, h, reg, [{"item_id": acqua["id"], "unit_price_gross": "0.40"}], [{"method": "carta", "amount": "5"}])
    assert bad.status_code == 422
    short = sale(client, h, reg, [{"item_id": acqua["id"], "quantity": "10", "unit_price_gross": "0.40"}], [{"method": "contanti", "amount": "3"}])
    assert short.status_code == 422
    mix = sale(client, h, reg, [{"item_id": acqua["id"], "quantity": "10", "unit_price_gross": "0.40", "discount": "10"}],
               [{"method": "carta", "amount": "3"}, {"method": "contanti", "amount": "1"}])
    assert mix.status_code == 200, mix.text
    assert Decimal(mix.json()["total"]) == Decimal("3.60") and Decimal(mix.json()["change"]) == Decimal("0.40")
    # reso parziale dallo scontrino: rientra in magazzino, rimborso in contanti
    pl = next(x for x in sco["lines"] if x["item_id"] == acqua["id"])
    too = client.post(f"{P}/casse/{reg['id']}/resi", headers=h, json={"client_uuid": str(uuid.uuid4()), "original_id": sco["id"],
                                                                      "lines": [{"item_id": acqua["id"], "quantity": "7", "unit_price_gross": "0.40", "origin_line_id": pl["id"]}]})
    assert too.status_code == 422
    rso = client.post(f"{P}/casse/{reg['id']}/resi", headers=h, json={"client_uuid": str(uuid.uuid4()), "original_id": sco["id"], "reason": "Bottiglia rotta",
                                                                      "lines": [{"item_id": acqua["id"], "quantity": "2", "unit_price_gross": "0.40", "origin_line_id": pl["id"]}]})
    assert rso.status_code == 200, rso.text
    assert rso.json()["doc_type"] == "RSO" and Decimal(rso.json()["total"]) == Decimal("0.80")
    assert qty(client, h, acqua) == 86
    # gli scontrini non si toccano dalle vendite
    assert client.post(f"/api/vendite/documenti/{sco['id']}/annulla", headers=h).status_code == 409
    # prelievo, riepilogo (X) e chiusura
    client.post(f"{P}/aperture/{ses['id']}/movimenti", headers=h, json={"kind": "prelievo", "amount": "50", "reason": "Versamento in banca"})
    x = client.get(f"{P}/aperture/{ses['id']}", headers=h).json()["summary"]
    # 100 + 8,93 + 0,60 − 0,80 − 50
    assert Decimal(x["expected_cash"]) == Decimal("58.73") and x["receipts"] == 2
    assert Decimal(x["net_total"]) == Decimal("11.73") and Decimal(x["by_method"]["carta"]["amount"]) == 3
    closed = client.post(f"{P}/aperture/{ses['id']}/chiudi", headers=h, json={"counted_cash": "58.50", "z_number": "0042"}).json()
    assert closed["status"] == "chiusa" and Decimal(closed["difference"]) == Decimal("-0.23")
    assert sale(client, h, reg, [{"item_id": acqua["id"], "unit_price_gross": "0.40"}], [{"method": "contanti", "amount": "1"}]).status_code == 409
    # liquidità: gli incassi al banco finiscono sui conti della cassa
    accs = {a["name"]: Decimal(a["balance"]) for a in client.get(f"{SC}/conti", headers=h).json()}
    assert accs["Cassa negozio"] == Decimal("8.73") and accs["Banca"] == 3
    # statistiche BI: canale banco, resi in negativo
    q = client.post("/api/bi/vendite/query", headers=h, json={"dimensions": ["canale"], "measures": ["fatturato", "documenti", "note_credito"],
                                                             "date_from": date.today().isoformat(), "date_to": date.today().isoformat()}).json()
    banco = next(r for r in q["rows"] if r["dims"]["canale"]["key"] == "banco")
    assert banco["dims"]["canale"]["label"] == "Vendita al banco"
    assert banco["values"] == {"fatturato": "10.54", "documenti": 2, "note_credito": 1}  # imponibile (11,73 IVA inclusa)


def test_fattura_al_banco(client, admin_headers):
    h, reg, pane, acqua, dep, cassa, banca = setup(client, admin_headers, "Fattura Banco Srl")
    client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={"opening_float": "0"})
    cust = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Bar Centrale", "is_customer": True, "vat_number": "07123450012", "address": "Via Roma 1", "zip_code": "70100", "city": "Bari",
        "province": "BA"}).json()
    found = client.get(f"{P}/clienti?q=centrale", headers=h).json()
    assert found[0]["id"] == cust["id"] and found[0]["can_invoice"]
    r = sale(client, h, reg, [{"item_id": acqua["id"], "quantity": "10", "unit_price_gross": "0.40"}], [{"method": "carta", "amount": "4"}],
             invoice_party_id=cust["id"])
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["doc_type"] == "FTI" and Decimal(f["total"]) == Decimal("4.00")
    doc = client.get(f"/api/vendite/documenti/{f['id']}", headers=h).json()
    assert doc["settled"] is True
    accs = {a["name"]: Decimal(a["balance"]) for a in client.get(f"{SC}/conti", headers=h).json()}
    assert accs["Banca"] == 4  # una sola volta: dalla rata, non dall'incasso di cassa


def test_catalogo_varianti(client, admin_headers):
    h, reg, pane, acqua, dep, cassa, banca = setup(client, admin_headers, "Varianti Srl")
    lists = {p["code"]: p["id"] for p in client.get("/api/anagrafiche/tabelle/listini", headers=h).json()}
    r = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "TSHIRT", "description": "T-shirt", "has_variants": True,
        "variants": [{"code": "TSHIRT-S", "size": "S"}, {"code": "TSHIRT-XL", "size": "XL", "price_delta": "2"}],
        "prices": [{"price_list_id": lists["PUBBLICO"], "price": "19.90"}]})
    assert r.status_code == 201, r.text
    it = next(i for i in client.get(f"{P}/casse/{reg['id']}/catalogo", headers=h).json()["items"] if i["code"] == "TSHIRT")
    assert it["vat_rate"] == "22.00" and it["price"] == "19.90"
    assert {v["label"]: v["price"] for v in it["variants"]} == {"S": "19.90", "XL": "21.90"}
    # senza taglia non si vende
    client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={})
    r = sale(client, h, reg, [{"item_id": it["id"], "unit_price_gross": "19.90"}], [{"method": "contanti", "amount": "20"}])
    assert r.status_code == 422 and "taglia" in r.json()["detail"]
