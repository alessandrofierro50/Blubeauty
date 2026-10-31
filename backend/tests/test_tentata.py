"""Tentata vendita: carico del furgone, documenti dell'agente con firma, incassi, rientro con conta alla cieca."""

import base64
import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

from PIL import Image

from tests.conftest import activate_and_login, make_tenant
from tests.test_magazzino import stock

T = "/api/tentata"
A = "/api/acquisti"
V = "/api/vendite"
SC = "/api/scadenzario"


def png() -> str:
    im = Image.new("RGBA", (120, 40), (255, 255, 255, 0))
    for x in range(10, 110):
        im.putpixel((x, 20 + (x % 7) - 3), (0, 0, 0, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def user(client, h, name, email, role):
    r = client.post("/api/app/users", headers=h, json={"full_name": name, "email": email, "role": role})
    assert r.status_code == 201, r.text
    uid, token = r.json()["id"], r.json()["activation_link"].split("token=")[1]
    r = client.post("/api/auth/activate", json={"token": token, "password": "password-123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}, uid


def setup(client, admin_headers, name="Distribuzione Srl"):
    t = make_tenant(client, admin_headers, name, plan="PRO", sector="Alimentari", vat_number="02345670984")
    client.patch(f"/api/admin/tenants/{t['id']}", headers=admin_headers, json={"extra_modules": ["tentata_vendita"]})
    h = activate_and_login(client, t)
    lists = {p["code"]: p["id"] for p in client.get("/api/anagrafiche/tabelle/listini", headers=h).json()}
    terms = {p["code"]: p["id"] for p in client.get("/api/anagrafiche/tabelle/pagamenti", headers=h).json()}
    sup = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Produttore", "is_customer": False, "is_supplier": True, "vat_number": "01114601006"}).json()
    acqua = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "ACQUA", "description": "Acqua 6x1,5 l", "unit": "CF", "prices": [{"price_list_id": lists["PUBBLICO"], "price": "3.00"}]}).json()
    yog = client.post("/api/anagrafiche/articoli", headers=h, json={
        "code": "YOG", "description": "Yogurt bianco", "lot_managed": True, "prices": [{"price_list_id": lists["PUBBLICO"], "price": "1.00"}]}).json()
    r = client.post(f"{A}/documenti", headers=h, json={"doc_type": "DDTF", "party_id": sup["id"], "external_number": "1", "lines": [
        {"item_id": acqua["id"], "quantity": "100", "unit_price": "1.50"},
        {"item_id": yog["id"], "quantity": "30", "unit_price": "0.40", "lot_number": "L1", "expiry_date": (date.today() + timedelta(days=20)).isoformat()},
        {"item_id": yog["id"], "quantity": "30", "unit_price": "0.40", "lot_number": "L2", "expiry_date": (date.today() + timedelta(days=40)).isoformat()}]})
    assert client.post(f"{A}/documenti/{r.json()['id']}/conferma", headers=h).status_code == 200
    bar = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Bar Centrale", "is_customer": True, "vat_number": "07123450012", "email": "bar@cliente.test",
        "mobile": "333 1234567", "payment_term_id": terms["CONT"]}).json()
    alim = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Alimentari Rossi", "is_customer": True, "vat_number": "02633880121", "payment_term_id": terms["BB30"]}).json()
    cassa = client.post(f"{SC}/conti", headers=h, json={"name": "Cassa agenti", "kind": "cassa", "opening_balance": "0"}).json()
    client.post(f"{SC}/conti", headers=h, json={"name": "Banca", "kind": "banca", "opening_balance": "0", "is_default": True})
    ha, agent_id = user(client, h, "Luca Agente", "luca@test.it", "agente")
    hw, _ = user(client, h, "Gino Magazzino", "gino@test.it", "magazzino")
    whs = client.get("/api/magazzino/magazzini", headers=h).json()["rows"]
    van = client.post(f"{T}/furgoni", headers=h, json={
        "code": "F1", "name": "Ducato bianco", "plate": "ab 123 cd", "series": "a1", "home_warehouse_id": whs[0]["id"],
        "agent_id": agent_id, "max_discount": "10", "cash_account_id": cassa["id"]})
    assert van.status_code == 201, van.text
    van = van.json()
    assert van["series"] == "A1" and van["plate"] == "AB123CD" and van["warehouse"] == "Furgone Ducato bianco"
    return {"h": h, "ha": ha, "hw": hw, "van": van, "acqua": acqua, "yog": yog, "bar": bar, "alim": alim, "terms": terms,
            "central": whs[0]["id"], "cassa": cassa}


def on_hand(client, h, item, wh_id):
    for w in stock(client, h, item["id"])["warehouses"]:
        if w["warehouse_id"] == wh_id:
            return Decimal(w["on_hand"])
    return Decimal(0)


def test_modulo_extra(client, admin_headers):
    t = make_tenant(client, admin_headers, "Senza Furgoni", plan="PRO")
    h = activate_and_login(client, t)
    assert client.get(f"{T}/furgoni", headers=h).status_code == 403


def test_giro_completo(client, admin_headers):
    s = setup(client, admin_headers)
    h, ha, hw, van = s["h"], s["ha"], s["hw"], s["van"]
    today = date.today()
    # giro clienti abituale: il bar oggi, alimentari un altro giorno
    r = client.put(f"{T}/furgoni/{van['id']}/giro-clienti", headers=h, json=[
        {"party_id": s["bar"]["id"], "weekdays": [today.weekday()]}, {"party_id": s["alim"]["id"], "weekdays": [(today.weekday() + 1) % 7]}])
    assert r.status_code == 200 and len(r.json()) == 2
    # ordine da consegnare ad alimentari: entra nel giro di oggi e nella proposta di carico
    o = client.post(f"{V}/documenti", headers=h, json={"doc_type": "ORC", "party_id": s["alim"]["id"], "lines": [
        {"item_id": s["acqua"]["id"], "quantity": "4", "unit_price": "2.80"}]}).json()
    assert client.post(f"{V}/documenti/{o['id']}/conferma", headers=h, json={}).status_code == 200
    # l'agente vede solo il suo furgone e crea il giro di oggi
    assert [v["code"] for v in client.get(f"{T}/furgoni", headers=ha).json()] == ["F1"]
    trip = client.post(f"{T}/giri", headers=ha, json={"van_id": van["id"], "trip_date": today.isoformat()})
    assert trip.status_code == 201, trip.text
    trip = trip.json()
    assert [x["name"] for x in trip["stops"]] == ["Bar Centrale", "Alimentari Rossi"]
    assert client.post(f"{T}/giri", headers=ha, json={"van_id": van["id"], "trip_date": today.isoformat()}).status_code == 409
    prop = {r["code"]: r for r in client.get(f"{T}/giri/{trip['id']}/proposta-carico", headers=h).json()}
    assert prop["ACQUA"]["proposed"] == "4" and prop["ACQUA"]["orders"] == "4"
    # carico: l'agente non può, il magazzino sì (lotti FEFO)
    load = {"lines": [{"item_id": s["acqua"]["id"], "quantity": "20"}, {"item_id": s["yog"]["id"], "quantity": "35"}]}
    assert client.post(f"{T}/giri/{trip['id']}/carico", headers=ha, json=load).status_code == 403
    r = client.post(f"{T}/giri/{trip['id']}/carico", headers=hw, json=load)
    assert r.status_code == 200, r.text
    lots = {ln["lot_number"]: ln["quantity"] for ln in r.json()["lines"] if ln["code"] == "YOG"}
    assert lots == {"L1": "30", "L2": "5"}
    assert on_hand(client, h, s["acqua"], van["warehouse_id"]) == 20 and on_hand(client, h, s["acqua"], s["central"]) == 80
    # senza partenza niente documenti
    doc = {"client_uuid": str(uuid.uuid4()), "doc_type": "DDT", "party_id": s["bar"]["id"],
           "lines": [{"item_id": s["acqua"]["id"], "quantity": "5", "unit_price": "2.459", "discount": "5"}],
           "delivery": {"signer_name": "Mario Bar", "signature_png": png(), "signed_at": "2026-10-28T10:15:00+01:00", "lat": 40.35, "lon": 18.17}}
    assert client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json=doc).status_code == 409
    assert client.post(f"{T}/giri/{trip['id']}/partenza", headers=ha, json={"km_start": 12000}).status_code == 200
    # pacchetto offline: clienti con fido e scadenze, articoli sul furgone con lotti, prezzi per cliente, niente costi
    pk = client.get(f"{T}/giri/{trip['id']}/pacchetto", headers=ha).json()
    assert [c["name"] for c in pk["customers"]] == ["Bar Centrale", "Alimentari Rossi"]
    assert pk["customers"][1]["orders"][0]["lines"][0]["open"] == "4"
    items = {i["code"]: i for i in pk["items"]}
    assert {x["lot_number"] for x in items["YOG"]["stock"]} == {"L1", "L2"}
    assert pk["prices"][s["bar"]["id"]][f"{s['acqua']['id']}:"]["price"] == "2.4590"  # 3,00 IVA inclusa → 2,459 netto
    assert "cost" not in str(pk["items"]) and "avg_cost" not in str(pk)
    # DDT firmato con sconto entro il massimo; ripetuto dalla coda non si duplica
    r = client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json=doc)
    assert r.status_code == 200, r.text
    ddt = r.json()
    assert ddt["label"] == "DDT 1/A1" and ddt["signed"] and ddt["signer_name"] == "Mario Bar"
    again = client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json=doc).json()
    assert again["replayed"] and again["id"] == ddt["id"]
    assert on_hand(client, h, s["acqua"], van["warehouse_id"]) == 15
    # sconto oltre il massimo e prezzo sotto il minimo: rifiutati
    bad = {**doc, "client_uuid": str(uuid.uuid4()), "lines": [{**doc["lines"][0], "discount": "20"}]}
    assert client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json=bad).status_code == 422
    bad["lines"] = [{**doc["lines"][0], "discount": None, "unit_price": "1.00"}]
    assert "minimo" in client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json=bad).json()["detail"]
    # fattura immediata con incasso in contanti: la scadenza si chiude
    fti = client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json={
        "client_uuid": str(uuid.uuid4()), "doc_type": "FTI", "party_id": s["bar"]["id"],
        "lines": [{"item_id": s["yog"]["id"], "quantity": "10", "unit_price": "1.00"}],
        "delivery": {"signer_name": "Mario Bar", "signature_png": png()},
        "collection": {"method": "contanti", "amount": "12.20"}})
    assert fti.status_code == 200, fti.text
    fti = fti.json()
    assert fti["label"] == "Fattura 1/A1" and Decimal(fti["total"]) == Decimal("12.20")
    inst = client.get(f"{SC}/scadenze?party_id={s['bar']['id']}&stato=tutte", headers=h).json()
    mine = [i for i in inst["rows"] if i.get("document_id") == fti["id"]]
    assert mine and all(i["status"] == "pagata" for i in mine)
    # ordine preso dall'agente: evade quello aperto? no, nuovo ordine sul magazzino centrale
    orc = client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json={
        "client_uuid": str(uuid.uuid4()), "doc_type": "ORC", "party_id": s["alim"]["id"],
        "lines": [{"item_id": s["yog"]["id"], "quantity": "6", "unit_price": "1.00"}]})
    assert orc.status_code == 200 and orc.json()["label"] == "Ordine cliente 1/A1"
    # consegna dell'ordine aperto con DDT che lo evade
    pk = client.get(f"{T}/giri/{trip['id']}/pacchetto", headers=ha).json()
    oline = pk["customers"][1]["orders"][0]["lines"][0]
    r = client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json={
        "client_uuid": str(uuid.uuid4()), "doc_type": "DDT", "party_id": s["alim"]["id"],
        "lines": [{"item_id": s["acqua"]["id"], "quantity": "4", "unit_price": "2.80", "origin_line_id": oline["id"]}],
        "delivery": {"signer_name": "Anna Rossi", "signature_png": png()}})
    assert r.status_code == 200, r.text
    assert client.get(f"{V}/documenti/{o['id']}", headers=h).json()["status"] == "evaso"
    # reso dal cliente: rientra sul furgone
    r = client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json={
        "client_uuid": str(uuid.uuid4()), "doc_type": "NC", "party_id": s["bar"]["id"],
        "lines": [{"item_id": s["acqua"]["id"], "quantity": "1", "unit_price": "2.459"}]})
    assert r.status_code == 200, r.text
    assert on_hand(client, h, s["acqua"], van["warehouse_id"]) == 12  # 20 - 5 - 4 + 1
    # incasso di una vecchia fattura con assegno (idempotente)
    old = client.post(f"{V}/documenti", headers=h, json={"doc_type": "FTI", "party_id": s["alim"]["id"], "doc_date": (today - timedelta(days=40)).isoformat(),
                                                         "lines": [{"description": "Fornitura", "quantity": "1", "unit_price": "100"}]}).json()
    assert client.post(f"{V}/documenti/{old['id']}/conferma", headers=h, json={}).status_code == 200
    col = {"client_uuid": str(uuid.uuid4()), "party_id": s["alim"]["id"], "method": "assegno", "amount": "50", "check_info": "BPM n. 123"}
    c1 = client.post(f"{T}/giri/{trip['id']}/incassi", headers=ha, json=col).json()
    c2 = client.post(f"{T}/giri/{trip['id']}/incassi", headers=ha, json=col).json()
    assert c1["id"] == c2["id"] and c2["replayed"] and c1["unallocated"] == "0.00"
    # PDF firmato, invio WhatsApp con link pubblico, invio email con allegato
    r = client.get(f"{T}/documenti/{ddt['id']}/pdf", headers=ha)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    w = client.post(f"{T}/documenti/{ddt['id']}/invia", headers=ha, json={"channel": "whatsapp"}).json()
    assert w["url"].startswith("https://wa.me/393331234567?text=")
    from urllib.parse import unquote
    link = unquote(w["url"]).split(": ", 1)[1].split("\n")[0]
    assert client.get(link[link.index("/api/"):]).content.startswith(b"%PDF")
    assert client.get("/api/tentata/pdf/token-falso").status_code == 404
    from app.core.mailer import OUTBOX
    e = client.post(f"{T}/documenti/{ddt['id']}/invia", headers=ha, json={"channel": "email"})
    assert e.status_code == 200, e.text
    assert OUTBOX[-1]["to"] == ["bar@cliente.test"] and OUTBOX[-1]["attachments"][0][0].endswith(".pdf")
    # rientro dichiarato dall'agente
    r = client.post(f"{T}/giri/{trip['id']}/rientro", headers=ha, json={"km_end": 12140, "cash": {"contanti": "12.00", "assegno": "50"}})
    assert r.status_code == 200, r.text
    assert client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json={**doc, "client_uuid": str(uuid.uuid4())}).status_code == 200  # coda arrivata dopo
    # conta alla cieca: il magazziniere non vede le quantità attese, l'agente sì
    blind = client.get(f"{T}/giri/{trip['id']}/rientro", headers=hw).json()
    assert not blind["revealed"] and all(r["expected"] is None for r in blind["rows"])
    seen = client.get(f"{T}/giri/{trip['id']}/rientro", headers=ha).json()
    exp = {(r["code"], r["lot_number"]): r["expected"] for r in seen["rows"]}
    assert exp == {("ACQUA", None): "7", ("YOG", "L1"): "20", ("YOG", "L2"): "5"}  # 12 - 5 del DDT arrivato dopo
    rows = {(r["code"], r["lot_number"]): r["id"] for r in blind["rows"]}
    counts = [{"id": rows[("ACQUA", None)], "counted": "6"}, {"id": rows[("YOG", "L1")], "counted": "20"}, {"id": rows[("YOG", "L2")], "counted": "5"}]
    sigs = {"agente": {"signer_name": "Luca Agente", "signature_png": png()}, "magazziniere": {"signer_name": "Gino", "signature_png": png()}}
    assert client.post(f"{T}/giri/{trip['id']}/verifica", headers=ha, json={"counts": counts, "signatures": sigs}).status_code == 403
    r = client.post(f"{T}/giri/{trip['id']}/verifica", headers=hw, json={"counts": counts, "signatures": sigs})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "differenze_da_motivare"
    assert r.json()["detail"]["differences"] == [{"id": rows[("ACQUA", None)], "expected": "7", "counted": "6"}]
    counts[0]["reason"] = "rotto"
    r = client.post(f"{T}/giri/{trip['id']}/verifica", headers=hw, json={"counts": counts, "signatures": sigs, "remaining": "rientra"})
    assert r.status_code == 200, r.text
    assert r.json()["differences"] == 1 and r.json()["trip"]["status"] == "chiuso"
    # furgone vuoto, merce rientrata in centrale (80 + 6), lotti conservati
    assert on_hand(client, h, s["acqua"], van["warehouse_id"]) == 0 and on_hand(client, h, s["acqua"], s["central"]) == 86
    assert on_hand(client, h, s["yog"], s["central"]) == 50  # 60 - 35 + 25
    closed = client.get(f"{T}/giri/{trip['id']}/rientro", headers=hw).json()
    acq = next(r for r in closed["rows"] if r["code"] == "ACQUA")
    assert acq["difference"] == "-1" and acq["reason_label"] == "Merce rotta o danneggiata"
    # riepilogo: km, visite, quadratura di cassa (contanti dichiarati 12,00 su 12,20 incassati)
    full = client.get(f"{T}/giri/{trip['id']}", headers=h).json()
    sm = full["summary"]
    assert sm["km"] == 140 and sm["visits"] == {"planned": 2, "visited": 2}
    cash = {c["method"]: c for c in sm["cash"]}
    assert cash["contanti"]["collected"] == "12.20" and cash["contanti"]["difference"] == "-0.20"
    assert cash["assegno"]["difference"] == "0.00"
    assert full["signatures"]["magazziniere"]["url"].startswith("/api/media/file/")
    assert len(client.get(f"{T}/riepilogo", headers=h).json()["trips"]) == 1
    # statistiche: canale furgone e dimensione agente (fattura 10,00 meno reso 2,46; i DDT entrano con la fattura differita)
    q = client.post("/api/bi/vendite/query", headers=h, json={"dimensions": ["agente"], "measures": ["fatturato"],
                                                             "date_from": today.isoformat(), "date_to": today.isoformat()}).json()
    by_agent = {r["dims"]["agente"]["label"]: r["values"]["fatturato"] for r in q["rows"]}
    assert by_agent == {"Luca Agente": "7.54"}
    # chiuso: niente più documenti
    assert client.post(f"{T}/giri/{trip['id']}/documenti", headers=ha, json={**doc, "client_uuid": str(uuid.uuid4())}).status_code == 409


def test_merce_resta_sul_furgone_e_permessi(client, admin_headers):
    s = setup(client, admin_headers, "Bevande Srl")
    h, ha, hw, van = s["h"], s["ha"], s["hw"], s["van"]
    today = date.today()
    trip = client.post(f"{T}/giri", headers=h, json={"van_id": van["id"], "trip_date": today.isoformat(), "party_ids": [s["bar"]["id"]]}).json()
    assert client.post(f"{T}/giri/{trip['id']}/carico", headers=hw, json={"lines": [{"item_id": s["acqua"]["id"], "quantity": "10"}]}).status_code == 200
    client.post(f"{T}/giri/{trip['id']}/partenza", headers=ha, json={})
    # un altro agente non vede né il furgone né il giro
    ho, _ = user(client, h, "Altro Agente", "altro@test.it", "agente")
    assert client.get(f"{T}/furgoni", headers=ho).json() == []
    assert client.get(f"{T}/giri/{trip['id']}", headers=ho).status_code == 404
    # non si apre un nuovo giro finché quello in corso non è chiuso
    assert client.post(f"{T}/giri", headers=h, json={"van_id": van["id"], "trip_date": (today + timedelta(days=1)).isoformat()}).status_code == 409
    client.post(f"{T}/giri/{trip['id']}/rientro", headers=ha, json={"signature": {"signer_name": "Luca", "signature_png": png()}})
    rows = client.get(f"{T}/giri/{trip['id']}/rientro", headers=hw).json()["rows"]
    # merce in più trovata sul furgone (senza motivo → 409), poi motivata; il rimanente resta sul furgone
    body = {"counts": [{"id": rows[0]["id"], "counted": "10"}], "extra": [{"item_id": s["yog"]["id"], "lot_number": "L9", "counted": "2"}],
            "remaining": "resta", "signatures": {"magazziniere": {"signer_name": "Gino", "signature_png": png()}}}
    assert client.post(f"{T}/giri/{trip['id']}/verifica", headers=hw, json=body).status_code == 409
    body["extra"][0]["reason"] = "errore_carico"
    r = client.post(f"{T}/giri/{trip['id']}/verifica", headers=hw, json=body)
    assert r.status_code == 200, r.text
    assert on_hand(client, h, s["acqua"], van["warehouse_id"]) == 10 and on_hand(client, h, s["yog"], van["warehouse_id"]) == 2
    # il giro dopo riparte con la merce già a bordo: la proposta ne tiene conto
    t2 = client.post(f"{T}/giri", headers=h, json={"van_id": van["id"], "trip_date": (today + timedelta(days=1)).isoformat()})
    assert t2.status_code == 201, t2.text
    stock_on_van = {r["code"]: r["quantity"] for r in client.get(f"{T}/furgoni/{van['id']}", headers=ha).json()["stock"]}
    assert stock_on_van == {"ACQUA": "10", "YOG": "2"}
