"""Cassa automatica VNE: incasso solo all'esito della macchina, annullamento, non eseguito, da verificare, gestione."""

import uuid
from decimal import Decimal

from sqlalchemy import text

from tests.test_periferiche import device, done, jobs, pair_agent
from tests.test_pos import P, setup

PER = "/api/periferiche"


def with_machine(client, admin_headers, name):
    h, reg, pane, acqua, dep, cassa, banca = setup(client, admin_headers, name)
    agent, ah, _ = pair_agent(client, h)
    rt = device(client, h, agent["id"], "simulatore_rt", "Registratore")
    vne = device(client, h, agent["id"], "vne_cash", "Cassa automatica", address="192.168.1.80",
                 options={"op_name": "cassiere", "auth_key": "SEGRETA-VNE"})
    body = {k: reg[k] for k in ("code", "name", "store_id", "warehouse_id", "price_list_id", "mode", "cash_account_id", "card_account_id",
                                "quick_keys", "settings", "active")}
    r = client.put(f"{P}/casse/{reg['id']}", headers=h, json={**body, "devices": {"rt": rt["id"], "cash": vne["id"]}})
    assert r.status_code == 200, r.text
    assert client.put(f"{P}/casse/{reg['id']}", headers=h, json={**body, "devices": {"cash": rt["id"]}}).status_code == 422
    ses = client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={"opening_float": "0"}).json()
    return h, r.json(), ses, acqua, ah, vne


def start(client, h, reg, acqua, qty="10", payments=None, cu=None):
    return client.post(f"{P}/casse/{reg['id']}/cassa-automatica/pagamenti", headers=h, json={
        "client_uuid": cu or str(uuid.uuid4()), "lines": [{"item_id": acqua["id"], "quantity": qty, "unit_price_gross": "0.40"}],
        "payments": payments or []})


def cash_job(client, ah):
    return next(j for j in jobs(client, ah) if j["kind"] == "cash.payment")


def pay_get(client, h, p):
    r = client.get(f"{P}/cassa-automatica/pagamenti/{p['id']}", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_dispositivo_authkey_mai_al_browser(client, admin_headers):
    h, reg, ses, acqua, ah, vne = with_machine(client, admin_headers, "Salone Vne Uno")
    assert "auth_key" not in vne["options"] and vne["options"]["auth_key_set"] is True
    assert vne["options"]["port"] == 443 and vne["options"]["verify_tls"] is False and vne["options"]["max_wait"] == 600
    cfg = client.get("/api/agent/configurazione", headers=ah).json()
    assert next(d for d in cfg["devices"] if d["driver"] == "vne_cash")["options"]["auth_key"] == "SEGRETA-VNE"  # solo all'agent
    # salvato di nuovo senza chiave: resta quella di prima; si toglie solo esplicitamente
    r = client.put(f"{PER}/dispositivi/{vne['id']}", headers=h, json={"agent_id": vne["agent_id"], "name": "Cassa automatica",
                                                                         "driver": "vne_cash", "address": "192.168.1.81", "options": vne["options"]})
    assert r.status_code == 200 and r.json()["options"]["auth_key_set"] is True
    cfg = client.get("/api/agent/configurazione", headers=ah).json()
    assert next(d for d in cfg["devices"] if d["driver"] == "vne_cash")["options"]["auth_key"] == "SEGRETA-VNE"
    per = client.get(f"{PER}/cassa/{reg['id']}", headers=h).json()
    assert "auth_key" not in per["devices"]["cash"]["options"]
    ov = client.get(f"{P}/casse/{reg['id']}/cassa-automatica", headers=h).json()
    assert ov["device"]["webtool_url"] == "https://192.168.1.81/tool/" and ov["device"]["agent_online"] is True
    r = client.put(f"{PER}/dispositivi/{vne['id']}", headers=h, json={"agent_id": vne["agent_id"], "name": "Cassa automatica",
                                                                         "driver": "vne_cash", "address": "192.168.1.81", "options": {"auth_key_clear": True}})
    assert r.json()["options"]["auth_key_set"] is False


def test_pagato_solo_all_esito_con_resto(client, admin_headers):
    h, reg, ses, acqua, ah, vne = with_machine(client, admin_headers, "Salone Vne Due")
    assert start(client, h, reg, acqua, payments=[{"method": "contanti", "amount": "4"}]).status_code == 422  # il contante lo prende la macchina
    cu = str(uuid.uuid4())
    r = start(client, h, reg, acqua, cu=cu)
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["status"] == "in_corso" and p["amount"] == "4.00" and p["amount_cents"] == 400
    assert start(client, h, reg, acqua, cu=cu).json()["id"] == p["id"]  # doppio clic: stesso pagamento
    assert start(client, h, reg, acqua).status_code == 409  # mai due operazioni insieme
    assert client.post(f"{P}/casse/{reg['id']}/cassa-automatica/stato", headers=h, json={}).status_code == 409
    assert client.get(f"{P}/scontrini?register_id={reg['id']}", headers=h).json() == []  # nessuna vendita prima dell'esito
    assert client.post(f"{P}/aperture/{ses['id']}/chiudi", headers=h, json={"counted_cash": "0"}).status_code == 409
    js = jobs(client, ah)
    assert len(js) == 1 and js[0]["kind"] == "cash.payment" and js[0]["payload"]["amount_cents"] == 400
    assert js[0]["device"]["options"]["auth_key"] == "SEGRETA-VNE"
    r = client.post(f"/api/agent/lavori/{js[0]['id']}/avanzamento", headers=ah, json={"progress": {"inserted": 200, "status": "pending"}})
    assert r.json() == {"cancel": 0}
    assert pay_get(client, h, p)["live"]["inserted"] == 200
    done(client, ah, js[0], id="1730000000001", status="completed", amount=400, inserted=1000, rest=600, card=False)
    p = pay_get(client, h, p)
    assert p["status"] == "pagato" and p["document_id"] and "resto 6,00" in p["message"]
    rec = p["receipt"]
    assert Decimal(rec["total"]) == Decimal("4") and rec["change"] == "6.00"
    assert rec["payments"] == [{"method": "contanti", "label": "Contanti", "amount": "4.00", "tendered": "10.00"}]
    assert rec["fiscal"]["cash_machine"]["inserted"] == 1000
    rj = jobs(client, ah)  # poi come sempre il documento commerciale sul registratore
    assert len(rj) == 1 and rj[0]["kind"] == "rt.receipt" and rj[0]["payload"]["payments"] == [{"method": "contanti", "amount": "10.00"}]
    # esito ripetuto dall'agent: nessuna seconda vendita
    done(client, ah, js[0], status="completed", amount=400, inserted=1000, rest=600)
    assert len(client.get(f"{P}/scontrini?register_id={reg['id']}", headers=h).json()) == 1


def test_carta_sulla_macchina_e_parte_con_carta(client, admin_headers):
    h, reg, ses, acqua, ah, vne = with_machine(client, admin_headers, "Salone Vne Tre")
    p = start(client, h, reg, acqua, payments=[{"method": "carta", "amount": "1.50"}]).json()
    assert p["amount"] == "2.50" and p["total"] == "4.00"
    j = jobs(client, ah)[0]
    done(client, ah, j, status="completed", amount=250, inserted=-2, rest=0)
    rec = pay_get(client, h, p)["receipt"]
    assert sorted((x["method"], x["amount"]) for x in rec["payments"]) == [("carta", "1.50"), ("carta", "2.50")]


def test_annullamento_restituisce_e_resta_da_incassare(client, admin_headers):
    h, reg, ses, acqua, ah, vne = with_machine(client, admin_headers, "Salone Vne Quattro")
    # ancora in coda: si ritira subito, l'agent non lo riceve
    p = start(client, h, reg, acqua).json()
    r = client.post(f"{P}/cassa-automatica/pagamenti/{p['id']}/annulla", headers=h, json={"mode": "restituisci"})
    assert r.json()["status"] == "annullato"
    assert jobs(client, ah) == []
    # già sulla macchina: l'annullamento arriva all'agent con l'avanzamento
    p = start(client, h, reg, acqua).json()
    j = jobs(client, ah)[0]
    assert client.post(f"{P}/cassa-automatica/pagamenti/{p['id']}/annulla", headers=h, json={"mode": "restituisci"}).json()["cancel_request"] == 2
    assert client.post(f"/api/agent/lavori/{j['id']}/avanzamento", headers=ah, json={"progress": {"inserted": 200}}).json() == {"cancel": 2}
    done(client, ah, j, status="returned", amount=400, inserted=200, rest=200, cancelled_by="cassiere")
    p = pay_get(client, h, p)
    assert p["status"] == "annullato" and "restituiti" in p["message"] and not p["document_id"]
    assert client.get(f"{P}/scontrini?register_id={reg['id']}", headers=h).json() == []
    assert client.post(f"{P}/cassa-automatica/pagamenti/{p['id']}/annulla", headers=h, json={}).status_code == 409


def test_non_eseguito_e_scadenza_45_secondi(client, admin_headers, owner_db):
    h, reg, ses, acqua, ah, vne = with_machine(client, admin_headers, "Salone Vne Cinque")
    p = start(client, h, reg, acqua).json()
    j = jobs(client, ah)[0]
    r = client.post(f"/api/agent/lavori/{j['id']}/esito", headers=ah, json={"ok": False, "error": "Cassa automatica non raggiungibile",
                                                                          "result": {"sent": False}})
    assert r.status_code == 200
    assert pay_get(client, h, p)["status"] == "non_eseguito"
    # lavoro mai preso dal computer del negozio: dopo 45 s scade come non eseguito e l'agent non lo riceve più
    p = start(client, h, reg, acqua).json()
    owner_db.execute(text("UPDATE device_jobs SET created_at = now() - interval '50 seconds' WHERE kind = 'cash.payment' AND status = 'in_coda'"))
    owner_db.commit()
    p = pay_get(client, h, p)
    assert p["status"] == "non_eseguito" and "45 secondi" in p["message"]
    assert jobs(client, ah) == []


def test_da_verificare_mai_nuovo_incasso_automatico(client, admin_headers):
    h, reg, ses, acqua, ah, vne = with_machine(client, admin_headers, "Salone Vne Sei")
    # nessun riscontro dopo l'invio: da verificare, la vendita non si registra da sola
    p = start(client, h, reg, acqua).json()
    j = cash_job(client, ah)
    client.post(f"/api/agent/lavori/{j['id']}/esito", headers=ah, json={"ok": False, "error": "Nessuna risposta dalla cassa automatica"})
    p = pay_get(client, h, p)
    assert p["status"] == "da_verificare" and not p["document_id"]
    ov = client.get(f"{P}/casse/{reg['id']}/cassa-automatica", headers=h).json()
    assert [x["id"] for x in ov["payments"]] == [p["id"]]
    r = client.post(f"{P}/cassa-automatica/pagamenti/{p['id']}/risolvi", headers=h, json={"esito": "pagato", "note": "visto sul display"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pagato" and r.json()["receipt"]["payments"][0]["amount"] == "4.00"
    # parziale: la cassa trattiene solo l'inserito, la differenza si incassa in altro modo
    p = start(client, h, reg, acqua).json()
    j = cash_job(client, ah)
    done(client, ah, j, status="partial", amount=400, inserted=300, rest=0, cancelled_by="cassiere")
    p = pay_get(client, h, p)
    assert p["status"] == "da_verificare" and p["partial"] and p["kept_cents"] == 300
    assert client.post(f"{P}/cassa-automatica/pagamenti/{p['id']}/risolvi", headers=h, json={"esito": "pagato"}).status_code == 422
    r = client.post(f"{P}/cassa-automatica/pagamenti/{p['id']}/risolvi", headers=h, json={"esito": "pagato", "metodo": "carta"})
    pays = sorted((x["method"], x["amount"]) for x in r.json()["receipt"]["payments"])
    assert pays == [("carta", "1.00"), ("contanti", "3.00")]
    # verificato come non pagato: si libera
    r = start(client, h, reg, acqua)
    assert r.status_code == 201, r.text
    p = r.json()
    j = cash_job(client, ah)
    client.post(f"/api/agent/lavori/{j['id']}/esito", headers=ah, json={"ok": False, "error": "x"})
    r = client.post(f"{P}/cassa-automatica/pagamenti/{p['id']}/risolvi", headers=h, json={"esito": "non_pagato"})
    assert r.json()["status"] == "non_pagato"
    assert len(client.get(f"{P}/scontrini?register_id={reg['id']}", headers=h).json()) == 2


def test_gestione_carico_prelievo(client, admin_headers):
    h, reg, ses, acqua, ah, vne = with_machine(client, admin_headers, "Salone Vne Sette")
    base = f"{P}/casse/{reg['id']}/cassa-automatica"
    assert client.post(f"{base}/prelievo", headers=h, json={}).status_code == 422  # serve l'importo
    r = client.post(f"{base}/carico", headers=h, json={"accept_all": True})
    assert r.status_code == 201, r.text
    op = r.json()
    assert op["op"] == "carico" and op["status"] == "in_coda"
    assert client.post(f"{base}/stato", headers=h, json={}).status_code == 409  # una operazione per volta
    assert start(client, h, reg, acqua).status_code == 409  # niente pagamento durante la gestione
    j = jobs(client, ah)[0]
    assert j["kind"] == "cash.admin" and j["payload"]["op"] == "carico" and j["payload"]["accept_all"] is True
    client.post(f"/api/agent/lavori/{j['id']}/avanzamento", headers=ah, json={"progress": {"status": "carico", "amount": 1500}})
    assert client.get(f"{P}/cassa-automatica/lavori/{op['id']}", headers=h).json()["progress"]["amount"] == 1500
    assert client.post(f"{P}/cassa-automatica/lavori/{op['id']}/stop", headers=h).json()["cancel_request"] == 2  # «Fine carico»
    assert client.post(f"/api/agent/lavori/{j['id']}/avanzamento", headers=ah, json={"progress": {"amount": 2000}}).json() == {"cancel": 2}
    cash = {"total_cents": 12000, "notes": [], "coins": [], "problems": [], "low": []}
    done(client, ah, j, status="completed", amount=2000, cash=cash)
    out = client.get(f"{P}/cassa-automatica/lavori/{op['id']}", headers=h).json()
    assert out["status"] == "eseguito" and out["result"]["amount"] == 2000
    assert client.get(base, headers=h).json()["cash"]["total_cents"] == 12000
    r = client.post(f"{base}/prelievo", headers=h, json={"denoms": {"banconota_1000": 2, "moneta_200": 1}})
    assert r.status_code == 201 and jobs(client, ah)[0]["payload"]["amount_cents"] == 2200
    assert client.post(f"{base}/apri", headers=h, json={"wait": "x"}).status_code == 422
