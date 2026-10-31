"""Statistiche avanzate (Pro): cubi di acquisti, scadenze, preventivi/ordini e magazzino, ABC, salute del magazzino,
clienti, report builder con invio programmato, dashboard."""

from datetime import date, timedelta
from decimal import Decimal

from app.core import mailer
from app.core.db import new_session
from tests.conftest import activate_and_login, make_tenant
from tests.test_vendite import confirm, new, setup, transform

BI = "/api/bi"
A = "/api/acquisti"
TODAY = date.today()
Y0 = TODAY.replace(month=1, day=1).isoformat()


def q(client, h, cube, **body):
    body.setdefault("date_from", Y0)
    body.setdefault("date_to", TODAY.isoformat())
    return client.post(f"{BI}/{cube}/query", headers=h, json=body)


def data(client, admin_headers, name):
    h, cust, sup, vite, lists = setup(client, admin_headers, name)
    dado = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "DADO", "description": "Dado M6",
                                                                   "prices": [{"price_list_id": lists["RIVEND"], "price": "2"}]}).json()
    chiodo = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "CHIODO", "description": "Chiodo",
                                                                     "prices": [{"price_list_id": lists["RIVEND"], "price": "1"}]}).json()
    f = client.post(f"{A}/documenti", headers=h, json={"doc_type": "FTF", "party_id": sup["id"], "external_number": "F-77",
                                                     "lines": [{"item_id": dado["id"], "quantity": "50", "unit_price": "0.80"},
                                                               {"item_id": chiodo["id"], "quantity": "100", "unit_price": "0.20"}]}).json()
    assert client.post(f"{A}/documenti/{f['id']}/conferma", headers=h).status_code == 200
    # vendite: viti 70 (10% sconto cliente → 63), dadi 20 → 18, chiodi 10 → 9 (Pareto A, A, B)
    fti = confirm(client, h, new(client, h, {"doc_type": "FTI", "party_id": cust["id"], "lines": [
        {"item_id": vite["id"], "quantity": "7"}, {"item_id": dado["id"], "quantity": "10"}, {"item_id": chiodo["id"], "quantity": "10"}]}))
    # preventivi: uno accettato (diventa ordine), uno no
    p1 = confirm(client, h, new(client, h, {"doc_type": "PRV", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "5"}]}))
    confirm(client, h, new(client, h, {"doc_type": "PRV", "party_id": cust["id"], "lines": [{"item_id": vite["id"], "quantity": "1"}]}))
    orc = transform(client, h, p1, "ORC")
    confirm(client, h, orc)
    return h, cust, sup, vite, dado, chiodo, fti


def test_cubi_pro(client, admin_headers):
    tb = make_tenant(client, admin_headers, "Solo Base BI", plan="BASE")
    hb = activate_and_login(client, tb)
    cubes = {c["name"]: c["available"] for c in client.get(f"{BI}/cubi", headers=hb).json()}
    assert cubes == {"vendite": True, "acquisti": False, "scadenze": False, "ordini": False, "magazzino": False}
    assert q(client, hb, "acquisti", measures=["spesa"]).status_code == 422
    assert client.get(f"{BI}/report", headers=hb).status_code == 403

    h, cust, sup, vite, dado, chiodo, fti = data(client, admin_headers, "Pro BI Srl")
    # acquisti: fattura del fornitore (il DDT iniziale non conta: si contano fatture e note di credito)
    r = q(client, h, "acquisti", measures=["spesa", "quantita", "costo_medio", "documenti"], dimensions=["articolo"], sort="spesa").json()
    by = {x["dims"]["articolo"]["label"]: x["values"] for x in r["rows"]}
    assert by["DADO · Dado M6"] == {"spesa": "40.00", "quantita": "50.000", "costo_medio": "0.80", "documenti": 1}
    assert r["totals"]["spesa"] == "60.00"
    det = client.post(f"{BI}/acquisti/dettaglio", headers=h, json={"measures": ["spesa"], "date_from": Y0, "date_to": TODAY.isoformat(),
                                                                 "filters": {"articolo": [dado["id"]]}}).json()
    assert det[0]["label"] == "Fattura F-77" and det[0]["amount"] == "40.00"
    # scadenze: la fattura al cliente (90 € + IVA) è tutta da incassare, quella del fornitore da pagare
    r = q(client, h, "scadenze", measures=["importo", "residuo", "scadenze"], dimensions=["direzione"],
          date_from=TODAY.isoformat(), date_to=(TODAY + timedelta(days=400)).isoformat()).json()
    by = {x["dims"]["direzione"]["label"]: x["values"] for x in r["rows"]}
    assert by["Crediti verso clienti"]["residuo"] == "109.80" and by["Debiti verso fornitori"]["importo"] == "73.20"
    # preventivi e ordini: 1 preventivo accettato su 2, ordine aperto da evadere
    r = q(client, h, "ordini", measures=["documenti", "convertiti", "conversione", "inevaso"], dimensions=["tipo_documento"]).json()
    by = {x["dims"]["tipo_documento"]["label"]: x["values"] for x in r["rows"]}
    assert by["Preventivi"]["conversione"] == "50.00" and by["Preventivi"]["convertiti"] == 1
    assert Decimal(by["Ordini"]["inevaso"]) == Decimal("45.00")  # 5 viti a 9 €
    r = q(client, h, "ordini", measures=["giorni_medi"], filters={"tipo_documento": ["PRV"]}).json()
    assert r["totals"]["giorni_medi"] == "0.0"
    # movimenti di magazzino: carichi e scarichi per causale
    r = q(client, h, "magazzino", measures=["carichi", "scarichi", "valore_carichi"], dimensions=["causale"]).json()
    by = {x["dims"]["causale"]["label"]: x["values"] for x in r["rows"]}
    assert Decimal(by["Vendita"]["scarichi"]) == 27 and Decimal(by["Acquisto"]["carichi"]) == 250
    # valori per i filtri
    vals = client.get(f"{BI}/vendite/valori/articolo?q=dado", headers=h).json()
    assert vals == [{"key": dado["id"], "label": "DADO · Dado M6"}]
    # Pro: fino a 4 dimensioni e margini
    assert q(client, h, "vendite", measures=["margine"], dimensions=["mese", "cliente", "articolo"]).status_code == 200


def test_abc_magazzino_clienti(client, admin_headers):
    h, cust, sup, vite, dado, chiodo, fti = data(client, admin_headers, "Analisi Srl")
    r = client.get(f"{BI}/analisi/abc?oggetto=articolo&misura=fatturato&periodo=anno_corrente", headers=h).json()
    assert [(x["label"], x["value"], x["class"]) for x in r["rows"]] == [("VITE · Vite", "63.00", "A"), ("DADO · Dado M6", "18.00", "A"),
                                                                       ("CHIODO · Chiodo", "9.00", "B")]
    assert r["total"] == "90.00" and r["rows"][1]["cumulative"] == "90.00"
    assert {s["class"]: s["count"] for s in r["summary"]} == {"A": 2, "B": 1, "C": 0}
    r = client.get(f"{BI}/analisi/abc?oggetto=fornitore&misura=spesa&periodo=anno_corrente", headers=h).json()
    assert r["rows"][0]["label"] == "Grossista" and r["measure"] == "spesa"
    # magazzino: viti 100 caricate a 4 €, 7 vendute; un articolo fermo
    fermo = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "FERMO", "description": "Articolo fermo"}).json()
    r = client.post(f"{A}/documenti", headers=h, json={"doc_type": "DDTF", "party_id": sup["id"], "external_number": "D-9",
                                                     "lines": [{"item_id": fermo["id"], "quantity": "5", "unit_price": "3"}]}).json()
    client.post(f"{A}/documenti/{r['id']}/conferma", headers=h)
    st = client.get(f"{BI}/analisi/magazzino?giorni=90", headers=h).json()
    by = {x["code"]: x for x in st["rows"]}
    assert by["VITE"]["on_hand"] == "93" and by["VITE"]["value_avg"] == "372.00" and by["VITE"]["out_period"] == "7"
    assert by["VITE"]["coverage_days"] == 1196 and by["VITE"]["idle"] is False
    assert by["FERMO"]["idle"] is True and by["FERMO"]["value_fifo"] == "15.00"
    assert st["summary"]["idle_count"] == 1 and st["summary"]["idle_value"] == "15.00"
    # clienti
    cl = client.get(f"{BI}/analisi/clienti?giorni_inattivo=90", headers=h).json()
    assert cl["rows"][0]["name"] == "Cliente Rossi" and cl["rows"][0]["status"] == "attivo" and cl["rows"][0]["revenue_12m"] == "90.00"
    assert client.get(f"{BI}/analisi/garanzie", headers=h).json()["active"] == 0


def test_report_builder_e_invio(client, admin_headers):
    h, cust, sup, vite, dado, chiodo, fti = data(client, admin_headers, "Report Srl")
    bad = client.post(f"{BI}/report", headers=h, json={"name": "Errato", "cube": "vendite", "config": {"measures": ["boh"]}})
    assert bad.status_code == 422
    body = {"name": "Vendite per articolo e mese", "cube": "vendite", "config": {
        "rows": ["articolo"], "columns": "mese", "measures": ["fatturato", "quantita"], "period": {"kind": "anno_corrente"}, "chart": "barre"},
        "schedule": {"frequency": "settimanale", "weekday": TODAY.weekday(), "emails": ["Titolare@Esempio.it"]}}
    r = client.post(f"{BI}/report", headers=h, json=body)
    assert r.status_code == 201, r.text
    rep = r.json()
    assert rep["schedule"]["emails"] == ["titolare@esempio.it"] and rep["period_label"] == "Quest'anno" and rep["schedule_label"].startswith("ogni ")
    assert client.post(f"{BI}/report", headers=h, json={**body, "schedule": {"frequency": "settimanale", "emails": ["non-una-email"]}}).status_code == 422
    run = client.get(f"{BI}/report/{rep['id']}/esegui", headers=h).json()
    assert run["result"]["totals"]["fatturato"] == "90.00" and len(run["result"]["rows"]) == 3
    x = client.get(f"{BI}/report/{rep['id']}/excel", headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    import io
    from openpyxl import load_workbook
    ws = load_workbook(io.BytesIO(x.content)).active
    assert ws.cell(2, 1).value == "Articolo" and "Totale" in ws.cell(2, ws.max_column).value
    # invio di prova e invio programmato
    mailer.OUTBOX.clear()
    assert client.post(f"{BI}/report/{rep['id']}/invia", headers=h).json()["sent_to"] == ["titolare@esempio.it"]
    assert mailer.OUTBOX[-1]["subject"] == "Report: Vendite per articolo e mese" and mailer.OUTBOX[-1]["attachments"][0][0].endswith(".xlsx")
    from app.bi.reports import run_scheduled
    mailer.OUTBOX.clear()
    out = run_scheduled(new_session, TODAY)
    assert list(out.values()) == [1] and len(mailer.OUTBOX) == 1
    assert run_scheduled(new_session, TODAY) == {}  # una volta sola al giorno
    # dashboard con il report come widget
    d = client.post(f"{BI}/dashboard", headers=h, json={"name": "La mia", "widgets": [{"report_id": rep["id"], "width": 9, "view": "kpi"},
                                                                                     {"report_id": "non-esiste"}]}).json()
    assert d["widgets"] == [{"report_id": rep["id"], "width": 4, "view": "kpi"}]
    assert client.delete(f"{BI}/report/{rep['id']}", headers=h).status_code == 204
    assert client.get(f"{BI}/dashboard", headers=h).json()[0]["widgets"] == []
