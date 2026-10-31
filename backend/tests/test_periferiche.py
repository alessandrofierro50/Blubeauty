"""Periferiche: abbinamento dell'agent, coda dei lavori, documento commerciale in cassa, chiusura Z, etichette."""

import uuid
from decimal import Decimal

from tests.conftest import activate_and_login, make_tenant
from tests.test_pos import P, sale, setup

PER = "/api/periferiche"


def pair_agent(client, h, name="PC cassa"):
    a = client.post(f"{PER}/computer", headers=h, json={"name": name})
    assert a.status_code == 201, a.text
    code = a.json()["pairing_code"]
    r = client.post("/api/agent/abbina", json={"code": code.lower(), "hostname": "NEGOZIO-PC", "version": "1.0.0"})
    assert r.status_code == 200, r.text
    assert client.post("/api/agent/abbina", json={"code": code}).status_code == 404  # vale una volta sola
    return a.json(), {"Authorization": f"Agent {r.json()['token']}"}, r.json()


def device(client, h, agent_id, driver, name, **kw):
    r = client.post(f"{PER}/dispositivi", headers=h, json={"agent_id": agent_id, "name": name, "driver": driver, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def jobs(client, ah):
    r = client.get("/api/agent/lavori?attesa=0", headers=ah)
    assert r.status_code == 200, r.text
    return r.json()


def done(client, ah, job, **result):
    r = client.post(f"/api/agent/lavori/{job['id']}/esito", headers=ah, json={"ok": True, "result": result})
    assert r.status_code == 200, r.text


def with_devices(client, admin_headers, name):
    h, reg, pane, acqua, dep, cassa, banca = setup(client, admin_headers, name)
    agent, ah, paired = pair_agent(client, h)
    rt = device(client, h, agent["id"], "simulatore_rt", "Registratore")
    pr = device(client, h, agent["id"], "simulatore_stampante", "Termica")
    body = {k: reg[k] for k in ("code", "name", "store_id", "warehouse_id", "price_list_id", "mode", "cash_account_id", "card_account_id",
                                "quick_keys", "settings", "active")}
    r = client.put(f"{P}/casse/{reg['id']}", headers=h, json={**body, "devices": {"rt": rt["id"], "printer": pr["id"]}})
    assert r.status_code == 200, r.text
    assert client.put(f"{P}/casse/{reg['id']}", headers=h, json={**body, "devices": {"rt": pr["id"]}}).status_code == 422
    return h, r.json(), pane, acqua, ah, rt, pr, paired


def test_abbinamento_e_moduli(client, admin_headers):
    t = make_tenant(client, admin_headers, "Solo Base", plan="BASE")
    hb = activate_and_login(client, t)
    assert client.get(f"{PER}/computer", headers=hb).status_code == 403
    h, reg, *_ = setup(client, admin_headers, "Periferiche Srl")
    agent, ah, paired = pair_agent(client, h)
    assert paired["local_key"] and paired["allowed_origins"]
    rt = device(client, h, agent["id"], "epson_rt", "Epson", address="192.168.1.50", options={"serial": "99MEY012345"})
    assert rt["options"]["departments"]["22"] == 1  # impostazioni predefinite del driver
    assert client.post(f"{PER}/dispositivi", headers=h, json={"agent_id": agent["id"], "name": "x", "driver": "epson_rt"}).status_code == 422
    cfg = client.get("/api/agent/configurazione", headers=ah).json()
    assert [d["name"] for d in cfg["devices"]] == ["Epson"] and cfg["devices"][0]["address"] == "192.168.1.50"
    lst = client.get(f"{PER}/computer", headers=h).json()
    assert lst[0]["paired"] and lst[0]["online"] and lst[0]["devices"] == 1
    assert client.get("/api/agent/lavori?attesa=0", headers={"Authorization": "Agent sbagliato"}).status_code == 401
    # eliminato il computer, il token non vale più
    assert client.delete(f"{PER}/computer/{agent['id']}", headers=h).status_code == 204
    assert client.get("/api/agent/configurazione", headers=ah).status_code == 401


def test_documento_commerciale_reso_e_chiusura(client, admin_headers):
    h, reg, pane, acqua, ah, rt, pr, _ = with_devices(client, admin_headers, "Fiscale Srl")
    ses = client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={"opening_float": "50"}).json()
    r = sale(client, h, reg, [{"item_id": acqua["id"], "quantity": "6", "unit_price_gross": "0.40", "discount": "10"},
                              {"item_id": pane["id"], "quantity": "1.25", "unit_price_gross": "3.50"}],
             [{"method": "contanti", "amount": "10"}], lottery_code="ABCD1234")
    assert r.status_code == 200, r.text
    sco = r.json()
    assert sco["fiscal"]["rt"]["status"] == "in_coda"
    js = jobs(client, ah)
    assert len(js) == 1 and js[0]["kind"] == "rt.receipt" and js[0]["device"]["driver"] == "simulatore_rt"
    p = js[0]["payload"]
    assert p["lottery"] == "ABCD1234" and p["payments"] == [{"method": "contanti", "amount": "10.00"}]  # il contante dato: il resto lo calcola il registratore
    acq = next(x for x in p["lines"] if "Acqua" in x["description"])
    assert acq["full_amount"] == "2.40" and acq["amount"] == "2.16"  # lo sconto diventa una rettifica sull'articolo
    assert next(x for x in p["lines"] if "Pane" in x["description"])["amount"] == "4.38"
    assert jobs(client, ah) == []  # un lavoro inviato non si rimanda da solo
    assert client.get(f"{P}/scontrini/{sco['id']}", headers=h).json()["fiscal"]["rt"]["status"] == "inviato"
    done(client, ah, js[0], number="0007", z="0012", date="2026-10-28", serial="99SIM000001")
    rt_data = client.get(f"{P}/scontrini/{sco['id']}", headers=h).json()["fiscal"]["rt"]
    assert rt_data["status"] == "emesso" and rt_data["number"] == "0007" and rt_data["z"] == "0012"
    # reso parziale: riferimento al documento commerciale d'origine
    acq_line = next(x for x in sco["lines"] if x["item_id"] == acqua["id"])
    rso = client.post(f"{P}/casse/{reg['id']}/resi", headers=h, json={"client_uuid": str(uuid.uuid4()), "original_id": sco["id"], "lines": [
        {"item_id": acqua["id"], "origin_line_id": acq_line["id"], "quantity": "2", "unit_price_gross": "0.40", "discount": "10"}]}).json()
    rj = jobs(client, ah)[0]
    assert rj["kind"] == "rt.refund" and rj["payload"]["reference"] == {"z": "0012", "number": "0007", "date": "2026-10-28", "serial": "99SIM000001"}
    assert rj["payload"]["void"] is False and rj["payload"]["lines"][0]["amount"] == "0.72"
    # errore del registratore e nuova prova
    r = client.post(f"/api/agent/lavori/{rj['id']}/esito", headers=ah, json={"ok": False, "error": "Carta finita"})
    assert r.json()["status"] == "errore"
    doc = client.get(f"{P}/scontrini/{rso['id']}", headers=h).json()
    assert doc["fiscal"]["rt"]["status"] == "errore" and doc["fiscal"]["rt"]["error"] == "Carta finita"
    assert client.post(f"{P}/scontrini/{rso['id']}/fiscale", headers=h, json={}).json()["fiscal"]["rt"]["status"] == "in_coda"
    rj2 = jobs(client, ah)[0]
    assert rj2["id"] != rj["id"] and rj2["payload"] == rj["payload"]
    assert client.post(f"{P}/scontrini/{rso['id']}/fiscale", headers=h, json={}).status_code == 409  # inviato senza risposta
    done(client, ah, rj2, number="0008", z="0012", date="2026-10-28")
    assert client.post(f"{P}/scontrini/{rso['id']}/fiscale", headers=h, json={}).status_code == 409  # già emesso
    # ricevuta di cortesia sulla stampante termica
    assert client.post(f"{P}/scontrini/{sco['id']}/stampa", headers=h).status_code == 200
    pj = jobs(client, ah)[0]
    assert pj["kind"] == "print.text" and any("0012-0007" in (x.get("text") or "") for x in pj["payload"]["lines"])
    assert not any(x.get("rt_only") for x in pj["payload"]["lines"])
    done(client, ah, pj)
    # copia di cortesia NON fiscale sul registratore (come BluOrderScan): rt.nonfiscal, senza intestazione, con la dicitura
    r = client.post(f"{P}/scontrini/{sco['id']}/stampa", headers=h, json={"where": "registratore"})
    assert r.status_code == 200 and r.json()["where"] == "registratore"
    cj = jobs(client, ah)[0]
    assert cj["kind"] == "rt.nonfiscal"
    texts = [x.get("rt_text") or x.get("text") for x in cj["payload"]["lines"] if not x.get("rt_skip") and x.get("text")]
    assert "COPIA DI CORTESIA" in texts and texts[-1] == "NON VALIDO COME DOC. COMMERCIALE"
    done(client, ah, cj)
    # senza rete: la cassa ha stampato tramite l'agent locale, il server registra l'esito senza nuovo lavoro
    off = sale(client, h, reg, [{"item_id": acqua["id"], "unit_price_gross": "0.40"}], [{"method": "contanti", "amount": "0.40"}],
               rt_result={"number": "0009", "z": "0012", "date": "2026-10-28"}).json()
    assert off["fiscal"]["rt"] == {"status": "emesso", "offline": True, "number": "0009", "z": "0012", "date": "2026-10-28"}
    assert jobs(client, ah) == []
    # chiusura di cassa: chiusura giornaliera Z sul registratore, numero registrato nell'apertura
    client.post(f"{P}/aperture/{ses['id']}/chiudi", headers=h, json={"counted_cash": "50"})
    zj = jobs(client, ah)[0]
    assert zj["kind"] == "rt.z"
    done(client, ah, zj, z="0012", date="2026-10-28")
    assert client.get(f"{P}/aperture/{ses['id']}", headers=h).json()["z_number"] == "0012"
    hist = client.get(f"{PER}/lavori", headers=h).json()
    assert {j["status"] for j in hist} >= {"eseguito", "annullato"}


def test_etichette(client, admin_headers):
    h, reg, pane, acqua, ah, rt, pr, paired = with_devices(client, admin_headers, "Etichette Srl")
    tpls = client.get(f"{PER}/etichette/modelli", headers=h).json()
    assert tpls[0]["is_default"] and tpls[0]["name"].startswith("Scaffale")
    data = client.post(f"{PER}/etichette/dati", headers=h, json={"rows": [{"item_id": acqua["id"], "quantity": 3}]}).json()
    assert data[0]["fields"]["price"] == "€ 0,40" and data[0]["fields"]["barcode"] == "8001234567897" and data[0]["quantity"] == 3
    zebra = device(client, h, paired["agent_id"], "simulatore_etichette", "Zebra")
    r = client.post(f"{PER}/etichette/stampa", headers=h, json={"rows": [{"item_id": acqua["id"], "quantity": 3}, {"item_id": pane["id"], "quantity": 1}],
                                                                "template_id": tpls[0]["id"], "device_id": zebra["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["labels"] == 4
    z = jobs(client, ah)[0]["payload"]["zpl"]
    assert z.count("^XA") == 2 and "^BEN," in z and "^FD800123456789^FS" in z and "^PQ3" in z and "€ 0,40" in z
    assert "^BCN," in z  # il pane non ha un EAN: Code 128 col codice articolo
    # modello personalizzato
    t = client.post(f"{PER}/etichette/modelli", headers=h, json={"name": "Piccola", "width_mm": 30, "height_mm": 20, "elements": [
        {"type": "text", "field": "custom", "text": "OFFERTA", "x": 1, "y": 1, "size": 4, "bold": True},
        {"type": "qr", "field": "code", "x": 1, "y": 6, "size": 3}, {"type": "box", "x": 0, "y": 0, "w": 30, "h": 20}]})
    assert t.status_code == 201, t.text
    assert client.post(f"{PER}/etichette/modelli", headers=h, json={"name": "Errata", "width_mm": 30, "height_mm": 20,
                                                                    "elements": [{"type": "text", "field": "boh"}]}).status_code == 422
    # etichette dal carico: quantità dalle righe del documento
    sup = client.post("/api/anagrafiche/soggetti", headers=h, json={"name": "Altro", "is_supplier": True, "is_customer": False, "vat_number": "01114601006"}).json()
    d = client.post("/api/acquisti/documenti", headers=h, json={"doc_type": "DDTF", "party_id": sup["id"], "external_number": "9",
                                                               "lines": [{"item_id": acqua["id"], "quantity": "24", "unit_price": "0.15"}]}).json()
    assert client.get(f"{PER}/etichette/da-documento/{d['id']}", headers=h).json() == [{"item_id": acqua["id"], "variant_id": None, "quantity": 24}]


def test_scarica_agent(client, admin_headers):
    import io
    import zipfile
    h, *_ = setup(client, admin_headers, "Scarica Srl")
    r = client.get(f"{PER}/agent/scarica", headers=h)
    assert r.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "BluBeautyAgent/blubeauty_agent.py" in names and "BluBeautyAgent/LEGGIMI.txt" in names
