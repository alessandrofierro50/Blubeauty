from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from tests.conftest import activate_and_login, make_tenant
from tests.test_magazzino import stock

V = "/api/vendite"
A = "/api/acquisti"


def setup(client, admin_headers, name="Vendite Srl"):
    t = make_tenant(client, admin_headers, name, plan="PRO", sector="Ferramenta", vat_number="02345670984")
    h = activate_and_login(client, t)
    lists = {p["code"]: p["id"] for p in client.get("/api/anagrafiche/tabelle/listini", headers=h).json()}
    cust = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Cliente Rossi", "is_customer": True, "vat_number": "07123450012", "price_list_id": lists["RIVEND"],
        "discount1": "10"}).json()
    sup = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Grossista", "is_customer": False, "is_supplier": True, "vat_number": "01114601006"}).json()
    vite = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "VITE", "description": "Vite", "prices": [{"price_list_id": lists["RIVEND"], "price": "10"}]}).json()
    r = client.post(f"{A}/documenti", headers=h, json={"doc_type": "DDTF", "party_id": sup["id"], "external_number": "1",
                                                     "lines": [{"item_id": vite["id"], "quantity": "100", "unit_price": "4"}]})
    assert client.post(f"{A}/documenti/{r.json()['id']}/conferma", headers=h).status_code == 200
    return h, cust, sup, vite, lists


def new(client, h, body):
    r = client.post(f"{V}/documenti", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def confirm(client, h, d, **kw):
    r = client.post(f"{V}/documenti/{d['id']}/conferma", headers=h, json=kw)
    assert r.status_code == 200, r.text
    return r.json()


def transform(client, h, d, to, quantities=None, **kw):
    r = client.post(f"{V}/documenti/{d['id']}/trasforma", headers=h, json={"to": to, "quantities": quantities, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def wh(client, h, item):
    w = stock(client, h, item["id"])["warehouses"][0]
    return Decimal(w["on_hand"]), Decimal(w["reserved"])


def test_ciclo_completo(client, admin_headers):
    h, cust, _, vite, _ = setup(client, admin_headers)
    # preventivo: prezzo dal motore prezzi (listino rivenditori 10 € meno sconto cliente 10%)
    prv = new(client, h, {"doc_type": "PRV", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "30"}]})
    assert Decimal(prv["lines"][0]["unit_price"]) == 9 and prv["lines"][0]["price_source"] == "Listino RIVEND"
    assert Decimal(prv["taxable_total"]) == 270 and Decimal(prv["total"]) == Decimal("329.40")
    assert Decimal(prv["margin"]["margin"]) == 150  # costo 4 × 30
    prv = confirm(client, h, prv)
    assert prv["number"] == 1
    # ordine: impegna la merce
    orc = confirm(client, h, transform(client, h, prv, "ORC"))
    assert wh(client, h, vite) == (100, 30)
    assert client.get(f"{V}/documenti/{prv['id']}", headers=h).json()["status"] == "evaso"
    # DDT parziale: scarica e libera l'impegno
    line = orc["lines"][0]["id"]
    ddt = confirm(client, h, transform(client, h, orc, "DDT", {line: "20"}))
    assert wh(client, h, vite) == (80, 10)
    assert client.get(f"{V}/documenti/{orc['id']}", headers=h).json()["status"] == "confermato"
    # il resto con fattura immediata
    fti = confirm(client, h, transform(client, h, orc, "FTI"))
    assert fti["number"] == 1 and Decimal(fti["lines"][0]["quantity"]) == 10
    assert wh(client, h, vite) == (70, 0)
    assert client.get(f"{V}/documenti/{orc['id']}", headers=h).json()["status"] == "evaso"
    # fatturazione differita del DDT: stessa numerazione delle fatture, magazzino fermo
    r = client.post(f"{V}/fatturazione-differita", headers=h, json={"ddt_ids": [ddt["id"]], "confirm": True})
    assert r.status_code == 201, r.text
    ftd = r.json()["documents"][0]
    assert ftd["doc_type"] == "FTD" and ftd["number"] == 2 and Decimal(ftd["taxable_total"]) == 180
    # in stampa ogni documento cita quelli da cui nasce, risalendo la catena
    rif = lambda d: [(o["doc_type"], o["number"]) for o in client.get(f"{V}/documenti/{d['id']}/stampa", headers=h).json()["origins"]]
    assert rif(prv) == [] and rif(orc) == [("PRV", 1)] and rif(fti) == [("PRV", 1), ("ORC", 1)]
    assert rif(ftd) == [("PRV", 1), ("ORC", 1), ("DDT", 1)]
    assert wh(client, h, vite) == (70, 0)
    assert client.get(f"{V}/documenti/{ddt['id']}", headers=h).json()["status"] == "evaso"
    assert client.get(f"{V}/documenti?da_fatturare=true", headers=h).json()["total"] == 0
    # una fattura con data precedente all'ultima non si può emettere
    old = new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "doc_date": (date.today() - timedelta(days=1)).isoformat(),
                          "lines": [{"description": "Servizio", "quantity": "1", "unit_price": "10"}]})
    r = client.post(f"{V}/documenti/{old['id']}/conferma", headers=h, json={})
    assert r.status_code == 422 and "ultima fattura" in r.json()["detail"]
    # nota di credito con rientro merce
    nc = new(client, h, {"doc_type": "NC", "party_id": cust["id"], "moves_stock": True,
                         "lines": [{"item_id": vite["id"], "quantity": "5", "unit_price": "9"}]})
    nc = confirm(client, h, nc)
    assert nc["number"] == 3 and wh(client, h, vite) == (75, 0)
    # acquistato dal cliente: 20 (DDT) + 10 (fattura) − 5 (nota di credito); la differita non si conta due volte
    acq = client.get(f"{V}/acquistato-cliente?party_id={cust['id']}", headers=h).json()
    assert Decimal(acq["rows"][0]["quantity"]) == 25 and Decimal(acq["total"]) == 225
    # storico articolo: acquisti e vendite
    st = client.get(f"{V}/storico-articolo?item_id={vite['id']}", headers=h).json()
    assert Decimal(st["summary"]["bought_qty"]) == 100 and Decimal(st["summary"]["sold_qty"]) == 25
    assert Decimal(st["summary"]["avg_sale"]) == 9
    # riquadro prezzi: ultimi prezzi al cliente, costi, listini, disponibilità
    info = client.get(f"{V}/info-riga?item_id={vite['id']}&party_id={cust['id']}&qty=1", headers=h).json()
    assert Decimal(info["price"]["unit_price"]) == 9 and Decimal(info["costs"]["cost"]) == 4
    assert info["last_sales"] and Decimal(info["last_sales"][0]["net_price"]) == 9
    assert Decimal(info["stock"]["available"]) == 75 and Decimal(info["last_purchase"]["net_price"]) == 4
    # annullamenti a catena: prima la differita, poi il DDT (rientra la merce, l'ordine si riapre e reimpegna)
    assert client.post(f"{V}/documenti/{ddt['id']}/annulla", headers=h).status_code == 409
    assert client.post(f"{V}/documenti/{ftd['id']}/annulla", headers=h).json()["status"] == "annullato"
    assert client.get(f"{V}/documenti/{ddt['id']}", headers=h).json()["status"] == "confermato"
    assert client.post(f"{V}/documenti/{ddt['id']}/annulla", headers=h).json()["status"] == "annullato"
    assert wh(client, h, vite) == (95, 20)
    orc = client.get(f"{V}/documenti/{orc['id']}", headers=h).json()
    assert orc["status"] == "confermato"
    # chiusura manuale dell'ordine: libera l'impegno residuo
    assert client.post(f"{V}/documenti/{orc['id']}/chiudi", headers=h).json()["status"] == "evaso"
    assert wh(client, h, vite) == (95, 0)


def test_fido(client, admin_headers):
    h, cust, _, vite, _ = setup(client, admin_headers, "Fido Srl")
    p = client.get(f"/api/anagrafiche/soggetti/{cust['id']}", headers=h).json()
    p.update({"credit_limit": "300", "credit_policy": "blocca"})
    assert client.put(f"/api/anagrafiche/soggetti/{cust['id']}", headers=h, json=p).status_code == 200
    f1 = confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"],
                                            "lines": [{"item_id": vite["id"], "quantity": "20"}]}))  # 219,60 €
    f2 = new(client, h, {"doc_type": "DDT", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "10"}]})
    r = client.post(f"{V}/documenti/{f2['id']}/conferma", headers=h, json={})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "fido_superato"
    st = client.get(f"{V}/clienti/{cust['id']}/fido", headers=h).json()
    assert Decimal(st["exposure"]["invoices"]) == Decimal("219.60") and Decimal(st["available"]) == Decimal("80.40")
    # incassata la prima fattura, il DDT passa
    client.post(f"{V}/documenti/{f1['id']}/incassata", headers=h, json={"settled": True})
    assert confirm(client, h, f2)["warnings"] == []
    # fatturare il DDT non aumenta l'esposizione
    ftd = client.post(f"{V}/fatturazione-differita", headers=h, json={"ddt_ids": [f2["id"]], "confirm": True}).json()
    assert ftd["warnings"] == []
    assert Decimal(client.get(f"{V}/clienti/{cust['id']}/fido", headers=h).json()["exposure"]["total"]) == Decimal("109.80")
    # superamento forzato dall'amministratore: passa con avviso
    big = new(client, h, {"doc_type": "ORC", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "50"}]})
    out = confirm(client, h, big, force=True)
    assert out["status"] == "confermato" and "Fido superato" in out["warnings"][0]
    # criterio "avvisa": nessun blocco
    p["credit_policy"] = "avvisa"
    client.put(f"/api/anagrafiche/soggetti/{cust['id']}", headers=h, json=p)
    ok = confirm(client, h, new(client, h, {"doc_type": "ORC", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "5"}]}))
    assert ok["warnings"]


def test_contratti_ricorrenti(client, admin_headers):
    h, cust, _, _, _ = setup(client, admin_headers, "Canoni Srl")
    start = date.today().replace(day=1) - relativedelta(months=2)
    r = client.post(f"{V}/contratti", headers=h, json={
        "party_id": cust["id"], "description": "Assistenza software", "start_date": start.isoformat(),
        "frequency_months": 1, "lines": [{"description": "Canone assistenza", "unit_price": "50"}]})
    assert r.status_code == 201, r.text
    ct = r.json()
    assert ct["code"] == "CT00001" and ct["next_invoice_date"] == start.isoformat() and ct["yearly"] == "600.00"
    assert client.get(f"{V}/contratti", headers=h).json()["due"] == 1
    gen = client.post(f"{V}/contratti/genera", headers=h, json={}).json()["documents"]
    assert len(gen) == 3  # i due mesi arretrati e quello corrente
    assert [d["number"] for d in gen] == [1, 2, 3] and all(d["status"] == "confermato" for d in gen)
    full = client.get(f"{V}/documenti/{gen[0]['id']}", headers=h).json()
    assert "periodo" in full["lines"][0]["description"] and full["moves_stock"] is False
    ct = client.get(f"{V}/contratti/{ct['id']}", headers=h).json()
    assert ct["next_invoice_date"] == (start + relativedelta(months=3)).isoformat() and len(ct["invoices"]) == 3
    assert client.post(f"{V}/contratti/genera", headers=h, json={}).json()["documents"] == []
    # con fatture emesse il contratto non si cancella: si disattiva
    assert client.delete(f"{V}/contratti/{ct['id']}", headers=h).json()["deactivated"] is True


def test_matricole_in_vendita(client, admin_headers):
    h, cust, sup, _, _ = setup(client, admin_headers, "Matricole Srl")
    tr = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "TR", "description": "Trapano", "serial_managed": True,
                                                                  "warranty_months": 24}).json()
    r = client.post(f"{A}/documenti", headers=h, json={"doc_type": "DDTF", "party_id": sup["id"], "external_number": "2",
                                                     "lines": [{"item_id": tr["id"], "quantity": "2", "unit_price": "50", "serials": ["A1", "A2"]}]})
    client.post(f"{A}/documenti/{r.json()['id']}/conferma", headers=h)
    d = new(client, h, {"doc_type": "DDT", "party_id": cust["id"], "lines": [{"item_id": tr["id"], "quantity": "1", "unit_price": "90", "serials": ["A1"]}]})
    confirm(client, h, d)
    sers = {x["serial_number"]: x for x in client.get("/api/magazzino/matricole?q=A1", headers=h).json()}
    assert sers["A1"]["status"] == "venduto" and sers["A1"]["warranty_until"]
    client.post(f"{V}/documenti/{d['id']}/annulla", headers=h)
    sers = {x["serial_number"]: x for x in client.get("/api/magazzino/matricole?q=A1", headers=h).json()}
    assert sers["A1"]["status"] == "disponibile"


def test_job_notturno_canoni(client, admin_headers):
    from app.core.db import new_session
    from app.documenti.recurring import run_recurring_invoices

    h, cust, _, _, _ = setup(client, admin_headers, "Notturno Srl")
    client.post(f"{V}/contratti", headers=h, json={
        "party_id": cust["id"], "description": "Noleggio", "start_date": date.today().isoformat(), "frequency_months": 12,
        "auto_confirm": False, "lines": [{"description": "Noleggio annuale", "unit_price": "1200"}]})
    result = run_recurring_invoices(new_session, date.today())
    assert 1 in result.values()
    docs = client.get(f"{V}/documenti?tipo=FTI", headers=h).json()["rows"]
    assert len(docs) == 1 and docs[0]["status"] == "bozza"  # da controllare prima di emetterla
    assert run_recurring_invoices(new_session, date.today()) == {}


def test_listino_cliente_senza_articolo_usa_il_predefinito(client, admin_headers):
    h, cust, _, _, lists = setup(client, admin_headers, "Listini Srl")
    solo_pubblico = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "TUBO", "description": "Tubo", "prices": [{"price_list_id": lists["PUBBLICO"], "price": "12.20"}]}).json()
    d = new(client, h, {"doc_type": "PRV", "party_id": cust["id"], "lines": [{"item_id": solo_pubblico["id"], "quantity": "1"}]})
    assert Decimal(d["lines"][0]["unit_price"]) == 9 and d["lines"][0]["price_source"] == "Listino PUBBLICO"  # 10 netto IVA − 10%


def test_bollo_sezionali_e_numerazioni(client, admin_headers):
    h, cust, _, vite, _ = setup(client, admin_headers, "Numeri Srl")
    vats = {v["code"]: v["id"] for v in client.get("/api/anagrafiche/tabelle/aliquote-iva", headers=h).json()}
    line = lambda price, vat: {"description": "Servizio", "quantity": "1", "unit_price": price, "vat_rate_id": vats[vat]}  # noqa: E731
    # bollo automatico a carico del cliente: oltre 77,47 € senza IVA
    f1 = new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "lines": [line("400", "N2.2")]})
    assert Decimal(f1["stamp_duty"]) == 2 and Decimal(f1["total"]) == 402
    assert Decimal(new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "lines": [line("70", "N2.2")]})["stamp_duty"]) == 0
    assert Decimal(new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "lines": [line("500", "N3.1")]})["stamp_duty"]) == 0
    assert Decimal(new(client, h, {"doc_type": "PRV", "party_id": cust["id"], "lines": [line("400", "N2.2")]})["stamp_duty"]) == 0
    f1 = confirm(client, h, f1)
    assert f1["number"] == 1
    # a carico dell'azienda: indicato ma fuori dal totale
    cfg = client.get(f"{V}/impostazioni", headers=h).json()
    assert cfg["bollo_mode"] == "cliente" and cfg["series"]["FT"] == []
    r = client.put(f"{V}/impostazioni", headers=h, json={"bollo_mode": "azienda", "series": {"FT": [{"code": "b", "description": "Negozio"}]},
                                                         "default_series": {}})
    assert r.status_code == 200 and r.json()["series"]["FT"] == [{"code": "B", "description": "Negozio"}]
    f2 = new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "lines": [line("400", "N2.2")]})
    assert Decimal(f2["stamp_duty"]) == 2 and Decimal(f2["total"]) == 400 and f2["series"] == ""
    # sezionale B: numerazione separata
    fb = confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "series": "B", "lines": [line("50", "22")]}))
    assert fb["series"] == "B" and fb["number"] == 1
    assert client.post(f"{V}/documenti", headers=h, json={"doc_type": "FTI", "party_id": cust["id"], "series": "Z", "lines": []}).status_code == 422
    # prossimo numero: non si scende sotto un numero valido, si riparte dopo aver annullato le prove
    year = date.today().year
    r = client.put(f"{V}/numerazioni", headers=h, json={"key": "FT", "year": year, "series": "", "next_number": 1})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "numeri_usati"
    assert client.post(f"{V}/documenti/{f1['id']}/annulla", headers=h).status_code == 200
    r = client.put(f"{V}/numerazioni", headers=h, json={"key": "FT", "year": year, "series": "", "next_number": 1})
    assert r.status_code == 200 and r.json()["notes"]
    assert client.get(f"{V}/documenti/{f1['id']}", headers=h).json()["number"] is None
    assert confirm(client, h, f2)["number"] == 1
    # numero scelto a mano: libero, poi la numerazione continua da lì
    f3 = new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "lines": [line("10", "22")]})
    assert client.post(f"{V}/documenti/{f3['id']}/conferma", headers=h, json={"number": 1}).status_code == 422
    assert confirm(client, h, f3, number=6)["number"] == 6
    c = next(x for x in client.get(f"{V}/impostazioni", headers=h).json()["counters"] if x["key"] == "FT" and x["series"] == "")
    assert c["next_number"] == 7 and c["documents"] == 2
    r = client.put(f"{V}/numerazioni", headers=h, json={"key": "FT", "year": year, "series": "", "next_number": 20})
    assert r.status_code == 200
    f4 = confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "lines": [line("10", "22")]}))
    assert f4["number"] == 20


def test_fatturazione_ddt_di_fine_mese(client, admin_headers):
    h, cust, _, vite, _ = setup(client, admin_headers, "Fine Mese Srl")
    other = client.post("/api/anagrafiche/soggetti", headers=h, json={"name": "Bar Aurora", "is_customer": True,
                                                                     "vat_number": "01234560033"}).json()
    end = date.today()
    mk = lambda c, q: confirm(client, h, new(client, h, {"doc_type": "DDT", "party_id": c["id"], "lines": [  # noqa: E731
        {"item_id": vite["id"], "quantity": q, "unit_price": "10"}]}))
    d1, d2, d3 = mk(cust, "2"), mk(cust, "3"), mk(other, "1")
    r = client.get(f"{V}/fatturazione-ddt?fino_al={end.isoformat()}", headers=h).json()
    assert [c["name"] for c in r["customers"]] == ["Bar Aurora", "Cliente Rossi"] and r["ddt_count"] == 3
    rossi = r["customers"][1]
    assert rossi["count"] == 2 and Decimal(rossi["taxable"]) == 50
    assert rossi["ddts"][0]["lines"][0]["code"] == "VITE" and Decimal(rossi["ddts"][0]["lines"][0]["quantity"]) == 2
    assert client.get(f"{V}/fatturazione-ddt?fino_al={(end - timedelta(days=1)).isoformat()}", headers=h).json()["customers"] == []
    # solo un DDT del primo cliente: l'altro resta da fatturare
    out = client.post(f"{V}/fatturazione-differita", headers=h, json={"ddt_ids": [d1["id"]], "confirm": True}).json()
    assert len(out["documents"]) == 1
    r = client.get(f"{V}/fatturazione-ddt", headers=h).json()
    assert {c["name"]: c["count"] for c in r["customers"]} == {"Bar Aurora": 1, "Cliente Rossi": 1}
    # tutti i clienti insieme: una fattura per cliente
    out = client.post(f"{V}/fatturazione-differita", headers=h, json={"ddt_ids": [d2["id"], d3["id"]], "confirm": True}).json()
    assert sorted(x["party_name"] for x in out["documents"]) == ["Bar Aurora", "Cliente Rossi"]
    assert client.get(f"{V}/fatturazione-ddt", headers=h).json()["customers"] == []
