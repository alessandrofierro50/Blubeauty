"""BluBeauty: agenda, prenotazione online da smartphone, disdetta, incasso con registratore, marketing WhatsApp."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
from sqlalchemy import text

from app.agenda import service as agenda_svc

from app.marketing import service as msg
from tests.conftest import activate_and_login, make_tenant
from tests.test_periferiche import device, done, jobs, pair_agent
from tests.test_pos import P, setup

AG = "/api/agenda"
MK = "/api/marketing"


def today() -> date:
    """Data italiana (il programma ragiona in Europe/Rome; a mezzanotte UTC è già il giorno dopo)."""
    return datetime.now(agenda_svc.TZ).date()


def next_weekday(wd: int, min_days: int = 2) -> date:
    """Prossimo giorno della settimana `wd` (0 = lunedì) ad almeno `min_days` giorni da oggi."""
    d = date.today() + timedelta(days=min_days)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


TUE = next_weekday(1)  # martedì: aperto 9:00-19:30 con gli orari predefiniti


def salon(client, admin_headers, name="Salone Aurora", plan="SALONE", **kw):
    t = make_tenant(client, admin_headers, name, plan=plan, **kw)
    h = activate_and_login(client, t)
    return t, h


def catalog(client, h):
    """Due operatrici, una cabina, colore con posa, piega, pressoterapia in cabina."""
    giulia = client.post(f"{AG}/operatori", headers=h, json={"first_name": "Giulia", "color": "#2340a8"}).json()
    sara = client.post(f"{AG}/operatori", headers=h, json={"first_name": "Sara", "color": "#ffc83d"}).json()
    cab = client.post(f"{AG}/risorse", headers=h, json={"name": "Cabina 1", "kind": "cabina"}).json()
    cat = client.post(f"{AG}/categorie", headers=h, json={"name": "Capelli"}).json()
    colore = client.post(f"{AG}/servizi", headers=h, json={
        "name": "Colore + piega", "category_id": cat["id"], "price": "65", "duration_min": 80, "processing_start_min": 20,
        "processing_min": 35, "staff_ids": [giulia["id"]], "recall_days": 35})
    assert colore.status_code == 201, colore.text
    piega = client.post(f"{AG}/servizi", headers=h, json={"name": "Piega", "category_id": cat["id"], "price": "22", "duration_min": 30,
                                                          "staff_ids": [giulia["id"], sara["id"]]}).json()
    presso = client.post(f"{AG}/servizi", headers=h, json={"name": "Pressoterapia", "price": "40", "duration_min": 45,
                                                           "staff_ids": [sara["id"]], "resource_ids": [cab["id"]]}).json()
    return {"giulia": giulia, "sara": sara, "cabina": cab, "colore": colore.json(), "piega": piega, "presso": presso}


def client_(client, h, first="Laura", last="Esposito", mobile="333 1111111", marketing=True, **kw):
    r = client.post(f"{AG}/clienti", headers=h, json={"first_name": first, "last_name": last, "mobile": mobile,
                                                       "privacy": True, "marketing": marketing, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def book(client, h, party, service, time, staff=None, day=TUE, **kw):
    return client.post(f"{AG}/appuntamenti", headers=h, json={
        "party_id": party["id"] if party else None, "day": day.isoformat(), "time": time,
        "items": [{"service_id": service["id"], "staff_id": staff["id"] if staff else None}], **kw})


# ----------------------------------------------------------------------------------------------------- pacchetti
def test_pacchetto_agenda_senza_cassa_e_marketing(client, admin_headers):
    _, h = salon(client, admin_headers, "Solo Agenda", plan="AGENDA")
    c = catalog(client, h)
    laura = client_(client, h)
    a = book(client, h, laura, c["piega"], "10:00")
    assert a.status_code == 201, a.text
    # conferma WhatsApp anche nel pacchetto AGENDA
    assert [m["kind"] for m in a.json()["messages"]] == ["conferma"]
    r = client.post(f"{AG}/appuntamenti/{a.json()['id']}/incassa", headers=h, json={"payments": [{"method": "contanti", "amount": "22"}]})
    assert r.status_code == 403 and r.json()["detail"]["module"] == "pos"
    assert client.get(f"{MK}/campagne", headers=h).status_code == 403
    assert client.get(f"{P}/casse", headers=h).status_code == 403
    autos = {x["kind"]: x for x in client.get(f"{MK}/automatici", headers=h).json()}
    assert autos["conferma"]["available"] and not autos["compleanno"]["available"]


# -------------------------------------------------------------------------------------------------- disponibilità
def test_tempo_di_posa_e_cabine(client, admin_headers):
    _, h = salon(client, admin_headers)
    c = catalog(client, h)
    laura, chiara = client_(client, h), client_(client, h, "Chiara", "Colombo", "333 2222222")
    assert book(client, h, laura, c["colore"], "09:00", c["giulia"]).status_code == 201
    # 9:00-9:20 applicazione, 9:20-9:55 posa (Giulia libera), 9:55-10:20 lavaggio e piega
    slots = client.get(f"{AG}/disponibilita", headers=h, params={"service_id": c["piega"]["id"], "day": TUE.isoformat(),
                                                                  "staff_id": c["giulia"]["id"]}).json()
    times = [x["time"] for x in slots]
    assert "09:00" not in times and "09:15" not in times
    assert "09:30" not in times  # 9:30-10:00 sfora nella seconda fase del colore (9:55)
    assert "10:15" not in times and "10:30" in times
    # durante la posa una piega da 20' ci sta? no (30'); ma un servizio che cade tutto nella posa sì:
    corto = client.post(f"{AG}/servizi", headers=h, json={"name": "Frangia", "price": "8", "duration_min": 20,
                                                          "staff_ids": [c["giulia"]["id"]]}).json()
    ok = book(client, h, chiara, corto, "09:25", c["giulia"])
    assert ok.status_code == 201, ok.text
    assert book(client, h, chiara, corto, "09:45", c["giulia"]).status_code == 409  # si sovrappone alla frangia
    # cabina: due pressoterapie alla stessa ora non ci stanno (una sola cabina)
    assert book(client, h, laura, c["presso"], "15:00", c["sara"]).status_code == 201
    r = book(client, h, chiara, c["presso"], "15:15")
    assert r.status_code == 409 and ("cabina" in r.text or "disponibile" in r.text)
    # orari di chiusura: lunedì chiuso
    mon = next_weekday(0)
    assert client.get(f"{AG}/disponibilita", headers=h, params={"service_id": c["piega"]["id"], "day": mon.isoformat()}).json() == []


# ------------------------------------------------------------------------------------------- prenotazione online
def test_prenotazione_online_e_disdetta_dallo_smartphone(client, admin_headers, owner_db):
    _, h = salon(client, admin_headers)
    c = catalog(client, h)
    cfg = client.get(f"{AG}/impostazioni", headers=h).json()
    slug = cfg["slug"]
    assert slug == "salone-aurora" and cfg["booking_url"].endswith("/prenota/salone-aurora")
    page = client.get(f"/api/prenota/{slug}").json()
    assert page["name"] and {x["name"] for x in page["services"]} == {"Colore + piega", "Piega", "Pressoterapia"}
    times = client.get(f"/api/prenota/{slug}/orari", params={"service_id": c["piega"]["id"], "day": TUE.isoformat()}).json()
    assert times[0] == "09:00"
    body = {"service_id": c["piega"]["id"], "day": TUE.isoformat(), "time": "11:00", "first_name": "Giorgia", "last_name": "Ferrari",
            "phone": "347 123 4567", "privacy": True, "marketing": True}
    assert client.post(f"/api/prenota/{slug}/prenotazioni", json={**body, "privacy": False}).status_code == 422
    assert client.post(f"/api/prenota/{slug}/prenotazioni", json={**body, "website": "spam"}).status_code == 422
    r = client.post(f"/api/prenota/{slug}/prenotazioni", json=body)
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    assert len(token) >= 30 and r.json()["url"].endswith(f"/prenota/{slug}/a/{token}")
    # il cliente è stato creato con i consensi e ha ricevuto la conferma (WhatsApp simulato)
    cl = client.get(f"{AG}/clienti", headers=h, params={"q": "Ferrari"}).json()
    assert len(cl) == 1 and cl[0]["privacy"] and cl[0]["marketing"] and cl[0]["mobile"] == "+393471234567"
    det = client.get(f"{AG}/clienti/{cl[0]['id']}", headers=h).json()
    assert det["messages"][0]["kind"] == "conferma" and det["messages"][0]["status"] == "simulato"
    assert token in det["messages"][0]["body"]
    # stesso numero: niente doppione in anagrafica
    r2 = client.post(f"/api/prenota/{slug}/prenotazioni", json={**body, "time": "15:00", "phone": "+39 347 1234567"})
    assert r2.status_code == 201
    assert len(client.get(f"{AG}/clienti", headers=h, params={"q": "Ferrari"}).json()) == 1
    # orario già preso: non si può prenotare due volte (2 operatrici fanno la piega: alla terza no)
    client.post(f"/api/prenota/{slug}/prenotazioni", json={**body, "time": "11:00", "phone": "3330000001"})
    assert client.post(f"/api/prenota/{slug}/prenotazioni", json={**body, "time": "11:00", "phone": "3330000002"}).status_code == 409
    # pagina personale e disdetta
    mine = client.get(f"/api/prenota/{slug}/a/{token}").json()
    assert mine["status"] == "confermato" and mine["can_cancel"] and mine["items"][0]["service"] == "Piega"
    assert client.get(f"/api/prenota/{slug}/a/token-inventato").status_code == 404
    r = client.post(f"/api/prenota/{slug}/a/{token}/disdici")
    assert r.status_code == 200 and r.json()["status"] == "disdetto" and not r.json()["can_cancel"]
    det = client.get(f"{AG}/clienti/{cl[0]['id']}", headers=h).json()
    assert "disdetta" in [m["kind"] for m in det["messages"]]
    assert "11:00" in client.get(f"/api/prenota/{slug}/orari", params={"service_id": c["piega"]["id"], "day": TUE.isoformat()}).json()


def test_disdetta_online_solo_fino_a_24_ore_prima(client, admin_headers, owner_db):
    _, h = salon(client, admin_headers)
    c = catalog(client, h)
    laura = client_(client, h)
    a = book(client, h, laura, c["piega"], "10:00").json()
    token = a["public_url"].rsplit("/", 1)[1]
    soon = datetime.now(agenda_svc.TZ) + timedelta(hours=5)
    owner_db.execute(text("UPDATE agenda_appointments SET starts_at = :s WHERE id = :i"), {"s": soon, "i": a["id"]})
    owner_db.commit()
    slug = client.get(f"{AG}/impostazioni", headers=h).json()["slug"]
    assert not client.get(f"/api/prenota/{slug}/a/{token}").json()["can_cancel"]
    r = client.post(f"/api/prenota/{slug}/a/{token}/disdici")
    assert r.status_code == 409 and "24 ore" in r.text
    # dal gestionale invece si può
    assert client.post(f"{AG}/appuntamenti/{a['id']}/disdici", headers=h).json()["status"] == "disdetto"


def test_pagina_non_attiva_se_abbonamento_sospeso_e_isolamento(client, admin_headers):
    t, h = salon(client, admin_headers)
    c = catalog(client, h)
    slug = client.get(f"{AG}/impostazioni", headers=h).json()["slug"]
    laura = client_(client, h)
    a = book(client, h, laura, c["piega"], "10:00").json()
    # un altro salone non vede né appuntamenti né clienti (RLS)
    _, h2 = salon(client, admin_headers, "Barber Shop")
    assert client.get(f"{AG}/appuntamenti/{a['id']}", headers=h2).status_code == 404
    assert client.get(f"{AG}/clienti", headers=h2).json() == []
    assert client.get(f"{AG}/impostazioni", headers=h2).json()["slug"] == "barber-shop"
    r = client.put(f"{AG}/impostazioni", headers=h2, json={**client.get(f"{AG}/impostazioni", headers=h2).json(), "slug": slug})
    assert r.status_code == 409  # indirizzo già usato
    client.post(f"/api/admin/tenants/{t['id']}/suspend", headers=admin_headers)
    assert client.get(f"/api/prenota/{slug}").status_code == 404


# ------------------------------------------------------------------------------------------------- cassa e fisco
def salon_with_register(client, admin_headers, name="Cassa Salone"):
    h, reg, pane, acqua, dep, cassa, banca = setup(client, admin_headers, name, plan="SALONE")
    agent, ah, _ = pair_agent(client, h)
    rt = device(client, h, agent["id"], "simulatore_rt", "Registratore")
    body = {k: reg[k] for k in ("code", "name", "store_id", "warehouse_id", "price_list_id", "mode", "cash_account_id",
                                "card_account_id", "quick_keys", "settings", "active")}
    assert client.put(f"{P}/casse/{reg['id']}", headers=h, json={**body, "devices": {"rt": rt["id"]}}).status_code == 200
    assert client.post(f"{P}/casse/{reg['id']}/apri", headers=h, json={"opening_float": "50"}).status_code == 201
    return h, reg, pane, ah


def test_incasso_scontrino_sul_registratore(client, admin_headers):
    h, reg, pane, ah = salon_with_register(client, admin_headers)
    c = catalog(client, h)
    laura = client_(client, h)
    a = book(client, h, laura, c["colore"], "09:00", c["giulia"]).json()
    assert client.post(f"{AG}/appuntamenti/{a['id']}/stato", headers=h, json={"status": "arrivato"}).status_code == 200
    body = {"register_id": reg["id"], "payments": [{"method": "carta", "amount": "61.00"}], "discount": "7.50",
            "products": [{"item_id": pane["id"], "quantity": "1", "unit_price_gross": "3.50"}]}
    r = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["appointment"]["status"] == "pagato" and out["receipt"]["doc_type"] == "SCO"
    assert Decimal(out["receipt"]["total"]) == Decimal("61.00")  # 65 − 7,50 di sconto + 3,50 di prodotto
    assert out["receipt"]["fiscal"]["rt"]["status"] == "in_coda"
    # il registratore (tramite BluBeauty Agent) riceve il documento commerciale
    js = jobs(client, ah)
    assert len(js) == 1 and js[0]["kind"] == "rt.receipt"
    assert any("Colore" in ln["description"] for ln in js[0]["payload"]["lines"])
    done(client, ah, js[0], number="0001", z="0001", date=date.today().isoformat(), serial="99SIM000001")
    det = client.get(f"{AG}/appuntamenti/{a['id']}", headers=h).json()
    assert det["document"]["rt"]["status"] == "emesso" and det["document"]["rt"]["number"] == "0001"
    # doppio clic: nessun secondo scontrino
    again = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json=body).json()
    assert again["replayed"] and again["receipt"]["id"] == out["receipt"]["id"] and jobs(client, ah) == []
    # punti fedeltà e messaggio di ringraziamento
    cli = client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()
    assert cli["loyalty_points"] == 61 and "grazie" in [m["kind"] for m in cli["messages"]]


def test_incasso_con_fattura(client, admin_headers):
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Fattura Salone")
    c = catalog(client, h)
    fr = client_(client, h, "Francesca", "Romano", "333 2222222")
    a = book(client, h, fr, c["piega"], "11:00").json()
    pay = {"register_id": reg["id"], "invoice": True, "payments": [{"method": "carta", "amount": "22"}]}
    r = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json=pay)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "dati_fatturazione"
    p = client.get(f"/api/anagrafiche/soggetti/{fr['id']}", headers=h).json()
    p.update({"tax_code": "RMNFNC85M41H501D", "address": "Via Appia Nuova 100", "zip_code": "00183", "city": "Roma", "province": "RM"})
    rr = client.put(f"/api/anagrafiche/soggetti/{fr['id']}", headers=h, json=p)
    assert rr.status_code == 200, rr.text
    r = client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json=pay)
    assert r.status_code == 200, r.text
    rec = r.json()["receipt"]
    assert rec["doc_type"] == "FTI" and Decimal(rec["total"]) == Decimal("22.00")
    assert jobs(client, ah) == []  # la fattura non passa dal registratore


# --------------------------------------------------------------------------------------------------- marketing
def test_campagne_solo_con_consenso(client, admin_headers):
    _, h = salon(client, admin_headers)
    client_(client, h, "Laura", "Esposito", "333 1111111", marketing=True)
    client_(client, h, "Elena", "Mancini", "333 8888888", marketing=False)
    client_(client, h, "Sofia", "Costa", "333 9999999", marketing=True, birth_date=date(1990, today().month, 14).isoformat())
    seg = {x["code"]: x["count"] for x in client.get(f"{MK}/segmenti", headers=h).json()}
    assert seg["tutti"] == 2 and seg["compleanno_mese"] == 1 and seg["inattivi_60"] == 2
    r = client.post(f"{MK}/campagne", headers=h, json={"name": "Promo", "segment": "tutti",
                                                      "body": "Ciao {nome}! Piega a 15 € da {salone}: {link}"})
    assert r.status_code == 201 and r.json()["recipients"] == 2
    assert client.get(f"{MK}/riepilogo", headers=h).json()["sent_30"] == 2
    cl = client.get(f"{AG}/clienti", headers=h, params={"q": "Mancini"}).json()[0]
    assert client.get(f"{AG}/clienti/{cl['id']}", headers=h).json()["messages"] == []  # niente consenso, niente messaggi
    la = client.get(f"{AG}/clienti", headers=h, params={"q": "Esposito"}).json()[0]
    body = client.get(f"{AG}/clienti/{la['id']}", headers=h).json()["messages"][0]["body"]
    assert body.startswith("Ciao Laura! Piega a 15 €") and "/prenota/salone-aurora" in body
    # la campagna già inviata non riparte
    assert client.get(f"{MK}/campagne", headers=h).json()[0]["status"] == "inviata"


def test_promemoria_e_automatici_una_volta_sola(client, admin_headers, owner_db):
    t, h = salon(client, admin_headers)
    c = catalog(client, h)
    laura = client_(client, h, birth_date=date(1990, today().month, today().day).isoformat())
    a = book(client, h, laura, c["piega"], "10:00").json()
    soon = datetime.now(agenda_svc.TZ) + timedelta(hours=20)
    owner_db.execute(text("UPDATE agenda_appointments SET starts_at = :s, created_at = :c WHERE id = :i"),
                     {"s": soon, "c": soon - timedelta(days=3), "i": a["id"]})
    owner_db.commit()
    from app.core.db import new_session
    from app.marketing import jobs as mj
    for _ in range(2):  # due giri del job: un solo promemoria
        r = mj.run_reminders(new_session, today())
    assert r == {} or r.get(t["id"]) in (None, 0)
    kinds = [m["kind"] for m in client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()["messages"]]
    assert kinds.count("promemoria") == 1
    for _ in range(2):
        mj.run_daily_marketing(new_session, today())
    kinds = [m["kind"] for m in client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()["messages"]]
    assert kinds.count("compleanno") == 1


def test_whatsapp_cloud_api(client, admin_headers):
    _, h = salon(client, admin_headers)
    c = catalog(client, h)
    sent = []

    def handler(request: httpx.Request):
        sent.append((request.url.path, request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"messages": [{"id": "wamid.TEST1"}]})

    msg._transport = httpx.MockTransport(handler)
    try:
        assert client.put(f"{MK}/impostazioni", headers=h, json={"whatsapp_mode": "cloud_api"}).status_code == 422
        r = client.put(f"{MK}/impostazioni", headers=h, json={"whatsapp_mode": "cloud_api", "whatsapp_phone_id": "1234567890",
                                                              "whatsapp_token": "EAAG-segreto"})
        assert r.status_code == 200 and r.json()["whatsapp_token_set"] and "segreto" not in r.text
        laura = client_(client, h)
        a = book(client, h, laura, c["piega"], "10:00").json()
        assert a["messages"][0]["status"] == "inviato"
        path, auth, payload = sent[0]
        assert path.endswith("/1234567890/messages") and auth == "Bearer EAAG-segreto"
        assert payload["to"] == "393331111111" and "Piega" in payload["text"]["body"]
    finally:
        msg._transport = None


# ------------------------------------------------------------------------------------------- fidelity e ricevuta
def test_raccolta_punti_tessera_premi_e_porta_un_amica(client, admin_headers):
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Punti Salone")
    c = catalog(client, h)
    laura = client_(client, h)
    cfg = client.get(f"{MK}/fidelity", headers=h).json()
    assert cfg["enabled"] and cfg["points_per_euro"] == 1 and [r["points"] for r in cfg["rewards"]] == [100, 250]
    # tessera con numero progressivo, si ritrova col lettore
    card = client.post(f"{MK}/fidelity/clienti/{laura['id']}/tessera", headers=h).json()
    assert card["number"] == "BB000001"
    assert client.post(f"{MK}/fidelity/clienti/{laura['id']}/tessera", headers=h).json()["number"] == "BB000001"  # una sola
    assert client.get(f"{MK}/fidelity/tessera/bb000001", headers=h).json()["party_id"] == laura["id"]
    # Laura presenta Chiara: alla prima visita pagata di Chiara, Laura riceve 50 punti
    chiara = client_(client, h, "Chiara", "Colombo", "333 3333333", referred_by=laura["id"])
    a = book(client, h, chiara, c["piega"], "11:00").json()
    pay = {"register_id": reg["id"], "payments": [{"method": "contanti", "amount": "22"}]}
    assert client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json=pay).status_code == 200
    det = client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()
    assert det["loyalty"]["points"] == 50 and det["loyalty"]["card"] == "BB000001"
    assert client.get(f"{AG}/clienti/{chiara['id']}", headers=h).json()["loyalty"]["points"] == 22
    # premio: servono 100 punti
    a2 = book(client, h, laura, c["colore"], "09:00", c["giulia"]).json()
    reward = cfg["rewards"][0]["id"]
    r = client.post(f"{AG}/appuntamenti/{a2['id']}/incassa", headers=h, json={**pay, "reward_id": reward,
                                                                                "payments": [{"method": "carta", "amount": "60"}]})
    assert r.status_code == 409 and "servono 100" in r.text
    assert client.post(f"{MK}/fidelity/clienti/{laura['id']}/rettifica", headers=h,
                       json={"points": 60, "note": "Punti della vecchia tessera di carta"}).json()["points"] == 110
    r = client.post(f"{AG}/appuntamenti/{a2['id']}/incassa", headers=h, json={**pay, "reward_id": reward,
                                                                                "payments": [{"method": "carta", "amount": "60"}]})
    assert r.status_code == 200, r.text
    assert Decimal(r.json()["receipt"]["total"]) == Decimal("60.00")  # 65 − 5 € di premio
    det = client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()
    assert det["loyalty"]["points"] == 110 - 100 + 60
    assert {m["reason"] for m in det["loyalty"]["moves"]} >= {"presenta_amica", "rettifica", "premio", "acquisto"}
    # avviso WhatsApp quando si raggiunge un premio (Laura passa da 10 a 70: nessuno; un'altra visita da 65 sì)
    a3 = book(client, h, laura, c["colore"], "15:00", c["giulia"]).json()
    client.post(f"{AG}/appuntamenti/{a3['id']}/incassa", headers=h, json={**pay, "payments": [{"method": "carta", "amount": "65"}]})
    kinds = [m["kind"] for m in client.get(f"{AG}/clienti/{laura['id']}", headers=h).json()["messages"]]
    assert "premio" in kinds


def test_ricevuta_non_fiscale_termica_e_registratore(client, admin_headers):
    h, reg, pane, ah = salon_with_register(client, admin_headers, "Ricevute Salone")
    c = catalog(client, h)
    laura = client_(client, h)
    a = book(client, h, laura, c["piega"], "10:00").json()
    prev = client.get(f"{AG}/appuntamenti/{a['id']}/ricevuta", headers=h).json()["lines"]
    texts = [ln.get("text", "") for ln in prev]
    assert "PROMEMORIA APPUNTAMENTO" in texts and not any("NON VALIDO" in t for t in texts)
    # la cassa deve essere quella predefinita dell'agenda
    st = client.get(f"{AG}/impostazioni", headers=h).json()
    assert client.post(f"{AG}/appuntamenti/{a['id']}/ricevuta", headers=h, json={"where": "registratore"}).status_code == 422
    client.put(f"{AG}/impostazioni", headers=h, json={**st, "register_id": reg["id"]})
    # niente termica collegata: errore chiaro
    r = client.post(f"{AG}/appuntamenti/{a['id']}/ricevuta", headers=h, json={"where": "termica"})
    assert r.status_code == 422 and "termica" in r.text
    # sul registratore come documento NON fiscale
    client.post(f"{AG}/appuntamenti/{a['id']}/incassa", headers=h, json={"payments": [{"method": "carta", "amount": "22"}]})
    jobs(client, ah)  # lo scontrino fiscale
    r = client.post(f"{AG}/appuntamenti/{a['id']}/ricevuta", headers=h, json={"where": "registratore"})
    assert r.status_code == 200, r.text
    js = jobs(client, ah)
    assert len(js) == 1 and js[0]["kind"] == "rt.nonfiscal"
    lines = [ln.get("text", "") for ln in js[0]["payload"]["lines"]]
    assert "RICEVUTA NON FISCALE" in lines and any(t.startswith("I tuoi punti fedeltà: 22") for t in lines)
    assert any(t.startswith("Scontrino fiscale n.") for t in lines)
