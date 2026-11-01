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


def test_buono_multiuso_venduto_e_usato_in_piu_volte(client, admin_headers):
    """Buono multiuso (predefinito): alla vendita ricevuta non fiscale, scontrino a ogni utilizzo pagato «con buono regalo»."""
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Salone Buoni")
    c = catalog(client, h)
    laura = client_(client, h)
    giulia = client_(client, h, "Giulia", "Bianchi", "333 2222222")
    assert client.get(f"{PP}/impostazioni", headers=h).json() == {"voucher_mode": "multiuso"}
    # vendita: incasso registrato, ricevuta NON fiscale con il codice, nessun documento commerciale
    cu = str(uuid.uuid4())
    r = client.post(f"{PP}/buoni", headers=h, json={"client_uuid": cu, "kind": "importo", "amount": "100", "purchaser_id": laura["id"],
                                                   "beneficiary_id": giulia["id"], "message": "Buon compleanno!", "months": 12,
                                                   "register_id": reg["id"], "payments": pay("contanti", "100")})
    assert r.status_code == 201, r.text
    v = r.json()["voucher"]
    assert v["code"].startswith("BR-") and v["balance"] == "100.00" and v["fiscal_mode"] == "multiuso"
    assert v["beneficiary_id"] == giulia["id"] and v["beneficiary_name"] == "Bianchi Giulia"
    rec = r.json()["receipt"]
    assert rec["fiscal"]["nonfiscal"]["reason"] == prepaid.REASON_VOUCHER_SALE and rec["fiscal"]["voucher_sale"]["code"] == v["code"]
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.nonfiscal"]
    texts = [x.get("text") for x in js[0]["payload"]["lines"]]
    assert f"Buono regalo {v['code']}" in texts and "di cui IVA" not in texts  # IVA all'utilizzo
    done(client, ah, js[0])
    # doppio clic: stesso buono
    assert client.post(f"{PP}/buoni", headers=h, json={"client_uuid": cu, "kind": "importo", "amount": "100",
                                                      "register_id": reg["id"], "payments": pay("contanti", "100")}).json()["voucher"]["id"] == v["id"]
    # il buono è nella scheda di chi lo riceve; pagina pubblica per WhatsApp
    assert [x["code"] for x in client.get(f"{PP}/clienti/{giulia['id']}", headers=h).json()["received"]] == [v["code"]]
    slug = client.get(f"{AG}/impostazioni", headers=h).json()["slug"]
    pub = client.get(f"/api/prenota/{slug}/buono/{v['public_url'].rsplit('/', 1)[1]}")
    assert pub.status_code == 200 and pub.json()["balance"] == "100.00"
    # primo utilizzo: colore 65 € → scontrino da 65 € pagato col buono, ricevuta non fiscale del saldo (35 €)
    a = book(client, h, giulia, c["colore"], "09:00", c["giulia"]).json()
    pv = client.get(f"{AG}/appuntamenti/{a['id']}/prepagati", headers=h, params={"buono": v["code"].lower().replace("-", "")}).json()
    assert pv["voucher"]["use"] == "65.00" and pv["voucher"]["left"] == "35.00" and pv["to_pay"] == "0.00" and pv["voucher"]["fiscal_mode"] == "multiuso"
    r = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json={"register_id": reg["id"], "voucher_code": v["code"],
                                                                             "payments": pay("contanti", "0")})
    assert r.status_code == 200, r.text
    rec = r.json()["receipt"]
    assert Decimal(rec["total"]) == Decimal("65.00") and not rec["fiscal"].get("nonfiscal")
    assert [(p["method"], p["amount"]) for p in rec["payments"]] == [("buono_regalo", "65.00")]
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.receipt", "rt.nonfiscal"]
    assert js[0]["payload"]["payments"] == [{"method": "buono_regalo", "amount": "65.00"}]
    slip = [x.get("text") for x in js[1]["payload"]["lines"]]
    assert "SALDO BUONO REGALO" in slip and "CREDITO RESIDUO" in slip
    for j in js:
        done(client, ah, j, number="0001", z="0001")
    assert client.get(f"{AG}/clienti/{giulia['id']}", headers=h).json()["loyalty_points"] == 0  # pagato col buono
    # secondo utilizzo: piega 22 € + prodotti 40 € = 62 €; il buono copre 35 €, la cliente paga 27 € con carta
    a2 = book(client, h, giulia, c["piega"], "15:00", c["giulia"]).json()
    r = client.post(f"{AG}/appuntamenti/{a2['id']}/incassa", headers=h, json={"register_id": reg["id"], "voucher_code": v["code"],
                                                                              "payments": pay("carta", "27"),
                                                                              "products": [{"item_id": pane["id"], "quantity": "2", "unit_price_gross": "20.00"}]})
    assert r.status_code == 200, r.text
    rec = r.json()["receipt"]
    assert Decimal(rec["total"]) == Decimal("62.00")
    assert sorted((p["method"], p["amount"]) for p in rec["payments"]) == [("buono_regalo", "35.00"), ("carta", "27.00")]
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.receipt"]  # buono finito: niente ricevuta del saldo
    assert sum(Decimal(x["amount"]) for x in js[0]["payload"]["lines"]) == Decimal("62.00")
    det = client.get(f"{PP}/buoni/{v['id']}", headers=h).json()
    assert det["balance"] == "0.00" and det["status"] == "esaurito" and [m["kind"] for m in det["moves"]] == ["emissione", "utilizzo", "utilizzo"]
    assert client.get(f"{AG}/clienti/{giulia['id']}", headers=h).json()["loyalty_points"] == 27
    msgs = client.get(f"{AG}/clienti/{giulia['id']}", headers=h).json()["messages"]
    assert [m["kind"] for m in msgs if m["kind"].startswith("buono")].count("buono_saldo") == 2
    rec_msg = next(m for m in msgs if m["kind"] == "buono_ricevuto")
    assert v["code"] in rec_msg["body"] and "100,00 €" in rec_msg["body"]
    assert any("ti restano 35,00 €" in m["body"] for m in msgs if m["kind"] == "buono_saldo")
    # buono esaurito, codice sbagliato, annullo
    a3 = book(client, h, laura, c["piega"], "17:00", c["giulia"]).json()
    assert client.post(f"{AG}/appuntamenti/{a3['id']}/incassa", headers=h, json={"register_id": reg["id"], "voucher_code": v["code"],
                                                                                "payments": pay("carta", "22")}).status_code == 422
    assert client.get(f"{PP}/buoni/codice/BR-XXXX-XXXX", headers=h).status_code == 404
    v2 = client.post(f"{PP}/buoni", headers=h, json={"client_uuid": str(uuid.uuid4()), "kind": "servizio", "service_id": c["piega"]["id"],
                                                    "register_id": reg["id"], "payments": pay("contanti", "50")}).json()
    assert v2["voucher"]["initial_amount"] == "22.00" and v2["change"] == "28.00"
    assert client.post(f"{PP}/buoni/{v2['voucher']['id']}/annulla", headers=h, json={"note": "Errore"}).json()["status"] == "annullato"


def test_buono_monouso(client, admin_headers):
    """Buono monouso (a scelta del salone): scontrino alla vendita, all'utilizzo ricevuta non fiscale o scontrino della differenza."""
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Salone Monouso")
    c = catalog(client, h)
    laura = client_(client, h)
    assert client.put(f"{PP}/impostazioni", headers=h, json={"voucher_mode": "monouso"}).json()["voucher_mode"] == "monouso"
    r = client.post(f"{PP}/buoni", headers=h, json={"client_uuid": str(uuid.uuid4()), "kind": "importo", "amount": "100",
                                                   "register_id": reg["id"], "payments": pay("carta", "100")})
    v = r.json()["voucher"]
    assert v["fiscal_mode"] == "monouso" and not r.json()["receipt"]["fiscal"].get("nonfiscal")
    js = jobs(client, ah)
    assert [j["kind"] for j in js] == ["rt.receipt"]
    done(client, ah, js[0], number="0001", z="0001")
    a = book(client, h, laura, c["colore"], "09:00", c["giulia"]).json()
    r = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json={"register_id": reg["id"], "voucher_code": v["code"],
                                                                             "payments": pay("contanti", "0")})
    rec = r.json()["receipt"]
    assert Decimal(rec["total"]) == 0 and rec["fiscal"]["nonfiscal"]["reason"] == prepaid.REASON_VOUCHER
    assert rec["fiscal"]["prepaid"]["voucher"]["left"] == "35.00"
    assert [j["kind"] for j in jobs(client, ah)] == ["rt.nonfiscal"]


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
    kinds = [m["kind"] for m in client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()["messages"]]
    assert kinds.count("pacchetto_acquistato") == 1 and kinds.count("pacchetto_seduta") == 3  # WhatsApp a ogni seduta
    # senza sedute: si paga normalmente
    a4 = book(client, h, laura, c["presso"], "10:00", c["sara"], day=TUE + timedelta(days=21)).json()
    assert client.get(f"{AG}/appuntamenti/{a4['id']}/prepagati", headers=h).json() == {"packages": [], "voucher": None, "to_pay": "40.00"}
    # controlli e isolamento tra aziende
    assert client.post(f"{PP}/pacchetti", headers=h, json={"name": "x", "price": "10", "items": []}).status_code == 422
    h2, *_ = salon_with_register(client, admin_headers, "Altro Salone Pacchetti")
    assert client.get(f"{PP}/venduti", headers=h2).json() == [] and client.get(f"{PP}/buoni", headers=h2).json() == []


def test_buono_alla_cassa_al_banco_e_scadenze(client, admin_headers):
    """Cassa al banco: pagamento «buono regalo» solo con un codice valido; scontrino, buono scalato, ricevuta del saldo.
    Avviso WhatsApp dei buoni e pacchetti in scadenza."""
    from app.core.db import new_session, set_tenant
    from app.marketing import jobs as mjobs
    from app.prepagati.models import GiftVoucher
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Salone Banco")
    giulia = client_(client, h, "Giulia", "Bianchi", "333 2222222")
    v = client.post(f"{PP}/buoni", headers=h, json={"client_uuid": str(uuid.uuid4()), "kind": "importo", "amount": "50", "beneficiary_id": giulia["id"],
                                                   "register_id": reg["id"], "payments": pay("contanti", "50")}).json()["voucher"]
    for j in jobs(client, ah):
        done(client, ah, j)
    sale = lambda **kw: client.post(f"/api/pos/casse/{reg['id']}/vendite", headers=h, json={
        "client_uuid": str(uuid.uuid4()), "lines": [{"item_id": pane["id"], "quantity": "2", "unit_price_gross": "10.00"}], **kw})
    # senza codice, codice sbagliato, credito insufficiente, ricevuta non fiscale: rifiutato
    assert sale(payments=pay("buono_regalo", "20")).status_code == 422
    assert sale(payments=pay("buono_regalo", "20"), voucher_code="BR-XXXX-XXXX").status_code == 404
    r = sale(payments=pay("buono_regalo", "20"), voucher_code=v["code"], nonfiscal_reason="Altro")
    assert r.status_code == 422
    # 20 € pagati col buono: scontrino, residuo 30 €, ricevuta del saldo
    r = sale(payments=pay("buono_regalo", "20"), voucher_code=v["code"].replace("-", "").lower(), customer_id=giulia["id"])
    assert r.status_code in (200, 201), r.text
    assert r.json()["fiscal"]["prepaid"]["voucher"]["left"] == "30.00"
    assert [j["kind"] for j in jobs(client, ah)] == ["rt.receipt", "rt.nonfiscal"]
    assert client.get(f"{PP}/buoni/{v['id']}", headers=h).json()["balance"] == "30.00"
    assert sale(payments=pay("buono_regalo", "40"), voucher_code=v["code"]).status_code == 422  # restano 30
    # scadenza tra 20 giorni: avviso WhatsApp una volta sola
    tid = client.get("/api/auth/me", headers=h).json()["tenant"]["id"]
    db = new_session()
    try:
        set_tenant(db, tid)
        g = db.get(GiftVoucher, uuid.UUID(v["id"]))
        g.expires_on = prepaid.today() + timedelta(days=20)
        db.commit()
        set_tenant(db, tid)
        assert mjobs.prepaid_expiry(db, tid, prepaid.today()) == 1
        assert mjobs.prepaid_expiry(db, tid, prepaid.today()) == 0
        db.commit()
    finally:
        db.close()
    body = next(m["body"] for m in client.get(f"{AG}/clienti/{giulia['id']}", headers=h).json()["messages"] if m["kind"] == "prepagato_scadenza")
    assert v["code"] in body and "30,00 €" in body
