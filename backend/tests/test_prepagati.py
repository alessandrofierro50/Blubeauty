"""BluBeauty: buoni regalo (anche usati in più volte, con residuo) e pacchetti di sedute a scalare."""

import uuid
from datetime import timedelta
from decimal import Decimal

from app.prepagati import service as prepaid
from tests.test_agenda import AG, TUE, book, catalog, client_, salon_with_register
from tests.test_periferiche import done, jobs

PP = "/api/prepagati"


def pay(method="contanti", amount="0"):
    return [{"method": method, "amount": amount}]


def test_buono_regalo_venduto_e_usato_in_piu_volte(client, admin_headers):
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Salone Buoni")
    c = catalog(client, h)
    laura = client_(client, h)
    # vendita: scontrino per l'intero valore (buono monouso), codice, link per chi lo riceve
    cu = str(uuid.uuid4())
    r = client.post(f"{PP}/buoni", headers=h, json={"client_uuid": cu, "kind": "importo", "amount": "100", "purchaser_id": laura["id"],
                                                   "beneficiary_name": "Giulia", "message": "Buon compleanno!", "months": 12,
                                                   "register_id": reg["id"], "payments": pay("carta", "1")})
    assert r.status_code == 201, r.text
    v = r.json()["voucher"]
    assert v["code"].startswith("BR-") and v["balance"] == "100.00" and v["status"] == "attivo" and "/buono/" in v["public_url"]
    assert r.json()["receipt"]["doc_type"] == "SCO" and Decimal(r.json()["receipt"]["total"]) == 100
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.receipt"] and "Buono regalo" in js[0]["payload"]["lines"][0]["description"]
    done(client, ah, js[0], number="0001", z="0001")
    # doppio clic: stesso buono
    assert client.post(f"{PP}/buoni", headers=h, json={"client_uuid": cu, "kind": "importo", "amount": "100",
                                                      "register_id": reg["id"], "payments": pay("carta", "1")}).json()["voucher"]["id"] == v["id"]
    # pagina pubblica del buono (link su WhatsApp)
    token = v["public_url"].rsplit("/", 1)[1]
    slug = client.get(f"{AG}/impostazioni", headers=h).json()["slug"]
    pub = client.get(f"/api/prenota/{slug}/buono/{token}")
    assert pub.status_code == 200 and pub.json()["balance"] == "100.00" and pub.json()["beneficiary_name"] == "Giulia"
    # utilizzo parziale: colore 65 € tutto col buono → ricevuta NON fiscale con il residuo, nessun nuovo scontrino
    a = book(client, h, laura, c["colore"], "09:00", c["giulia"]).json()
    pv = client.get(f"{AG}/appuntamenti/{a['id']}/prepagati", headers=h, params={"buono": v["code"].lower().replace("-", "")}).json()
    assert pv["voucher"]["use"] == "65.00" and pv["voucher"]["left"] == "35.00" and pv["to_pay"] == "0.00"
    r = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json={"register_id": reg["id"], "voucher_code": v["code"],
                                                                             "payments": pay("contanti", "0")})
    assert r.status_code == 200, r.text
    rec = r.json()["receipt"]
    assert Decimal(rec["total"]) == 0 and rec["fiscal"]["nonfiscal"]["reason"] == prepaid.REASON_VOUCHER
    assert rec["fiscal"]["prepaid"]["voucher"] == {"code": v["code"], "used": "65.00", "left": "35.00", "expires_on": v["expires_on"]}
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.nonfiscal"]
    texts = [x.get("text") for x in js[0]["payload"]["lines"]]
    assert "  Credito residuo" in texts and "RICEVUTA NON FISCALE" in texts
    done(client, ah, js[0])
    # secondo utilizzo: taglio 35 € + piega 22 € = 57 €, il buono copre 35 €, scontrino solo per i 22 € di differenza
    a2 = book(client, h, laura, c["piega"], "15:00", c["giulia"]).json()
    r = client.post(f"{AG}/appuntamenti/{a2['id']}/incassa", headers=h, json={"register_id": reg["id"], "voucher_code": v["code"],
                                                                              "payments": pay("carta", "22"),
                                                                              "products": [{"item_id": pane["id"], "quantity": "2", "unit_price_gross": "20.00"}]})
    assert r.status_code == 200, r.text
    rec = r.json()["receipt"]
    assert Decimal(rec["total"]) == Decimal("27.00") and not rec["fiscal"].get("nonfiscal")  # 22 + 40 − 35
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.receipt"]
    assert sum(Decimal(x["amount"]) for x in js[0]["payload"]["lines"]) == Decimal("27.00")
    det = client.get(f"{PP}/buoni/{v['id']}", headers=h).json()
    assert det["balance"] == "0.00" and det["status"] == "esaurito" and [m["kind"] for m in det["moves"]] == ["emissione", "utilizzo", "utilizzo"]
    # buono esaurito, codice sbagliato, buono scaduto
    a3 = book(client, h, laura, c["piega"], "17:00", c["giulia"]).json()
    assert client.post(f"{AG}/appuntamenti/{a3['id']}/incassa", headers=h, json={"register_id": reg["id"], "voucher_code": v["code"],
                                                                                "payments": pay("carta", "22")}).status_code == 422
    assert client.get(f"{PP}/buoni/codice/BR-XXXX-XXXX", headers=h).status_code == 404
    v2 = client.post(f"{PP}/buoni", headers=h, json={"client_uuid": str(uuid.uuid4()), "kind": "servizio", "service_id": c["piega"]["id"],
                                                    "register_id": reg["id"], "payments": pay("contanti", "50")}).json()
    assert v2["voucher"]["initial_amount"] == "22.00" and v2["change"] == "28.00"
    # annullo (solo amministratore)
    assert client.post(f"{PP}/buoni/{v2['voucher']['id']}/annulla", headers=h, json={"note": "Errore"}).json()["status"] == "annullato"


def test_pacchetto_di_sedute_a_scalare(client, admin_headers):
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Salone Pacchetti")
    c = catalog(client, h)
    laura = client_(client, h)
    r = client.post(f"{PP}/pacchetti", headers=h, json={"name": "3 pressoterapie", "price": "100", "validity_days": 180, "min_days": 7,
                                                       "items": [{"service_id": c["presso"]["id"], "sessions": 3}]})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["list_value"] == "120.00" and p["saving"] == "20.00"
    # vendita alla cliente: scontrino per il prezzo del pacchetto
    r = client.post(f"{PP}/pacchetti/{p['id']}/vendi", headers=h, json={"client_uuid": str(uuid.uuid4()), "party_id": laura["id"],
                                                                       "register_id": reg["id"], "payments": pay("carta", "100")})
    assert r.status_code == 201, r.text
    cp = r.json()["package"]
    assert cp["remaining"] == 3 and cp["status"] == "attivo" and Decimal(r.json()["receipt"]["total"]) == 100
    done(client, ah, jobs(client, ah)[0], number="0002", z="0001")
    # seduta: si scala da sola, ricevuta non fiscale «seduta 1 di 3»
    a = book(client, h, laura, c["presso"], "10:00", c["sara"]).json()
    pv = client.get(f"{AG}/appuntamenti/{a['id']}/prepagati", headers=h).json()
    assert pv["packages"][0]["session"] == 1 and pv["packages"][0]["of"] == 3 and pv["to_pay"] == "0.00"
    r = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json={"register_id": reg["id"], "payments": pay("contanti", "0")})
    assert r.status_code == 200, r.text
    rec = r.json()["receipt"]
    assert rec["fiscal"]["nonfiscal"]["reason"] == prepaid.REASON_PACKAGE
    assert rec["fiscal"]["prepaid"]["packages"][0] | {} == {"name": "3 pressoterapie", "service": "Pressoterapia", "session": 1, "of": 3,
                                                            "remaining": 2, "expires_on": cp["expires_on"]}
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.nonfiscal"] and "  Pressoterapia: seduta 1 di 3" in [x.get("text") for x in js[0]["payload"]["lines"]]
    done(client, ah, js[0])
    # nessun punto fedeltà sulla seduta già pagata
    assert client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()["loyalty_points"] == 0
    # seduta + prodotto venduto: scontrino solo per il prodotto
    a2 = book(client, h, laura, c["presso"], "10:00", c["sara"], day=TUE + timedelta(days=7)).json()
    r = client.post(f"{AG}/appuntamenti/{a2['id']}/incassa", headers=h, json={"register_id": reg["id"], "payments": pay("contanti", "0"),
                                                                              "products": [{"item_id": pane["id"], "quantity": "1", "unit_price_gross": "9.50"}]})
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["receipt"]["total"]) == Decimal("9.50") and r.json()["receipt"]["fiscal"]["prepaid"]["packages"][0]["remaining"] == 1
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.receipt"] and [x["description"] for x in js[0]["payload"]["lines"]] == [pane["description"]]
    done(client, ah, js[0], number="0003", z="0001")
    # terza e ultima seduta: pacchetto esaurito
    a3 = book(client, h, laura, c["presso"], "10:00", c["sara"], day=TUE + timedelta(days=14)).json()
    client.post(f"{AG}/appuntamenti/{a3['id']}/incassa", headers=h, json={"register_id": reg["id"], "payments": pay("contanti", "0")})
    sold = client.get(f"{PP}/clienti/{laura['id']}", headers=h).json()["packages"][0]
    assert sold["remaining"] == 0 and sold["status"] == "esaurito"
    # senza sedute: si paga normalmente
    a4 = book(client, h, laura, c["presso"], "10:00", c["sara"], day=TUE + timedelta(days=21)).json()
    assert client.get(f"{AG}/appuntamenti/{a4['id']}/prepagati", headers=h).json() == {"packages": [], "voucher": None, "to_pay": "40.00"}
    # controlli e isolamento tra aziende
    assert client.post(f"{PP}/pacchetti", headers=h, json={"name": "x", "price": "10", "items": []}).status_code == 422
    h2, *_ = salon_with_register(client, admin_headers, "Altro Salone Pacchetti")
    assert client.get(f"{PP}/venduti", headers=h2).json() == [] and client.get(f"{PP}/buoni", headers=h2).json() == []
