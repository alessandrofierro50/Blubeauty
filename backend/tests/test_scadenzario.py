import calendar
from datetime import date, timedelta
from decimal import Decimal

from app.core import mailer
from tests.conftest import activate_and_login, make_tenant

V = "/api/vendite"
A = "/api/acquisti"
SC = "/api/scadenzario"


def eom(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def setup(client, admin_headers, name):
    t = make_tenant(client, admin_headers, name, plan="BASE", sector="Ferramenta", vat_number="02345670984")
    h = activate_and_login(client, t)
    terms = {p["code"]: p["id"] for p in client.get("/api/anagrafiche/tabelle/pagamenti", headers=h).json()}
    cust = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Cliente Bianchi", "is_customer": True, "vat_number": "07123450012", "email": "bianchi@cliente.test",
        "mobile": "333 1234567", "payment_term_id": terms["BB3060"]}).json()
    sup = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Grossista", "is_customer": False, "is_supplier": True, "vat_number": "01114601006", "payment_term_id": terms["BB30"]}).json()
    bank = client.post(f"{SC}/conti", headers=h, json={"name": "Banca Popolare", "kind": "banca", "opening_balance": "1000",
                                                       "opening_date": (date.today() - timedelta(days=90)).isoformat(), "is_default": True}).json()
    return h, cust, sup, terms, bank


def invoice(client, h, party, amount="100", when=None, doc_type="FTI", **extra):
    body = {"doc_type": doc_type, "party_id": party["id"], "lines": [{"description": "Servizio", "quantity": "1", "unit_price": amount}], **extra}
    if when:
        body["doc_date"] = when.isoformat()
    d = client.post(f"{V}/documenti", headers=h, json=body).json()
    r = client.post(f"{V}/documenti/{d['id']}/conferma", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def rows(client, h, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    return client.get(f"{SC}/scadenze?{q}", headers=h).json()


def test_rate_incassi_e_annullamento(client, admin_headers):
    h, cust, _, _, bank = setup(client, admin_headers, "Rate Srl")
    f = invoice(client, h, cust, "1000")  # 1.220 € in due rate 30/60 gg fine mese
    data = rows(client, h, direzione="attiva")
    inst = data["rows"]
    today = date.today()
    assert [x["due_date"] for x in inst] == [eom(today + timedelta(days=30)).isoformat(), eom(today + timedelta(days=60)).isoformat()]
    assert [Decimal(x["amount"]) for x in inst] == [Decimal("610.00"), Decimal("610.00")]
    assert Decimal(data["totals"]["receivable"]) == Decimal("1220.00")
    # incasso parziale e poi totale
    r = client.post(f"{SC}/scadenze/{inst[0]['id']}/pagamenti", headers=h, json={"pay_date": today.isoformat(), "amount": "200"}).json()
    assert r["status"] == "parziale" and Decimal(r["residual"]) == 410
    too_much = client.post(f"{SC}/scadenze/{inst[0]['id']}/pagamenti", headers=h, json={"pay_date": today.isoformat(), "amount": "500"})
    assert too_much.status_code == 422
    r = client.post(f"{SC}/incasso-multiplo", headers=h, json={"ids": [x["id"] for x in inst], "pay_date": today.isoformat()}).json()
    assert r["paid"] == 2 and Decimal(r["total"]) == Decimal("1020.00")
    assert client.get(f"{V}/documenti/{f['id']}", headers=h).json()["settled"] is True
    assert Decimal(client.get(f"{SC}/conti", headers=h).json()[0]["balance"]) == Decimal("2220.00")
    # la fattura con incassi non si annulla; tolti gli incassi sì, e le scadenze spariscono
    assert client.post(f"{V}/documenti/{f['id']}/annulla", headers=h).status_code == 409
    full = client.get(f"{SC}/scadenze/{inst[0]['id']}", headers=h).json()
    for p in full["payments"]:
        client.delete(f"{SC}/pagamenti/{p['id']}", headers=h)
    client.post(f"{V}/documenti/{f['id']}/incassata", headers=h, json={"settled": False})
    assert client.post(f"{V}/documenti/{f['id']}/annulla", headers=h).status_code == 200
    assert rows(client, h, stato="tutte")["total"] == 0


def test_nota_credito_split_payment_e_acquisti(client, admin_headers):
    h, cust, sup, terms, _ = setup(client, admin_headers, "Split Srl")
    pa = client.post("/api/anagrafiche/soggetti", headers=h, json={"name": "Comune", "is_customer": True, "tax_code": "80008870752",
                                                                  "split_payment": True, "payment_term_id": terms["BB30"]}).json()
    invoice(client, h, pa, "500")
    sp = rows(client, h, party_id=pa["id"])["rows"]
    assert Decimal(sp[0]["amount"]) == 500  # l'IVA la versa l'ente
    invoice(client, h, cust, "100", doc_type="NC")
    nc = rows(client, h, party_id=cust["id"])["rows"]
    assert Decimal(nc[0]["amount"]) == Decimal("-122.00") and nc[0]["due_date"] == date.today().isoformat()
    # fattura fornitore: scadenza passiva a 30 giorni dalla data della fattura del fornitore
    ext = date.today() - timedelta(days=5)
    d = client.post(f"{A}/documenti", headers=h, json={"doc_type": "FTF", "party_id": sup["id"], "external_number": "77",
                                                     "external_date": ext.isoformat(), "lines": [{"description": "Merce", "quantity": "1", "unit_price": "50"}]}).json()
    client.post(f"{A}/documenti/{d['id']}/conferma", headers=h)
    pas = rows(client, h, direzione="passiva")["rows"]
    assert pas[0]["due_date"] == (ext + timedelta(days=30)).isoformat() and Decimal(pas[0]["amount"]) == Decimal("61.00")
    assert pas[0]["description"].startswith("Fattura n. 77")


def test_scadenze_manuali_e_liquidita(client, admin_headers):
    h, cust, _, _, bank = setup(client, admin_headers, "Liquidita Srl")
    today = date.today()
    r = client.post(f"{SC}/scadenze", headers=h, json={"direction": "passiva", "description": "Affitto negozio", "amount": "800",
                                                      "due_date": (today + timedelta(days=3)).isoformat(), "repeat_months": 1, "repeat_count": 3}).json()
    assert r["created"] == 3
    f = invoice(client, h, cust, "1000", when=today - timedelta(days=20))
    inst = rows(client, h, direzione="attiva")["rows"]
    client.post(f"{SC}/scadenze/{inst[0]['id']}/pagamenti", headers=h, json={"pay_date": (today - timedelta(days=2)).isoformat()})
    # oggi: 1000 + 610 incassati
    now = client.get(f"{SC}/liquidita", headers=h).json()
    assert Decimal(now["liquidity"]) == Decimal("1610.00")
    assert Decimal(now["receivables"]["open"]) == Decimal("610.00") and Decimal(now["payables"]["open"]) == Decimal("2400.00")
    assert now["weeks"][0]["label"] == "Già scaduto"
    assert Decimal(now["weeks"][1]["out"]) == 800  # affitto fra 3 giorni
    # fotografia di 10 giorni fa: fattura già emessa, incasso non ancora arrivato, affitto non ancora inserito
    past = client.get(f"{SC}/liquidita?as_of={(today - timedelta(days=10)).isoformat()}", headers=h).json()
    assert Decimal(past["liquidity"]) == 1000 and Decimal(past["receivables"]["open"]) == Decimal("1220.00")
    assert Decimal(past["payables"]["open"]) == 0
    # fotografia salvata e congelata
    snap = client.post(f"{SC}/fotografie", headers=h, json={"name": "Fine mese", "as_of": today.isoformat()}).json()
    client.post(f"{SC}/scadenze/{inst[1]['id']}/pagamenti", headers=h, json={"pay_date": today.isoformat()})
    assert client.get(f"{SC}/fotografie/{snap['id']}", headers=h).json()["data"]["liquidity"] == "1610.00"
    x = client.get(f"{SC}/fotografie/{snap['id']}/excel", headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert client.get(f"{SC}/scadenze/excel?stato=tutte", headers=h).content[:2] == b"PK"
    assert f["id"]


def test_solleciti_e_blocco_insolventi(client, admin_headers):
    h, cust, _, terms, _ = setup(client, admin_headers, "Solleciti Srl")
    p = client.get(f"/api/anagrafiche/soggetti/{cust['id']}", headers=h).json()
    p["payment_term_id"] = terms["BB0"]
    client.put(f"/api/anagrafiche/soggetti/{cust['id']}", headers=h, json=p)
    invoice(client, h, cust, "100", when=date.today() - timedelta(days=40))
    prop = client.get(f"{SC}/solleciti/proposta", headers=h).json()
    assert prop[0]["days_late"] == 40 and prop[0]["suggested_level"] == 1 and prop[0]["due_now"] is True
    mailer.OUTBOX.clear()
    r = client.post(f"{SC}/solleciti/invia", headers=h, json={"party_ids": [cust["id"]]}).json()
    assert r["sent"] == 1 and r["results"][0]["level"] == 1
    mail = mailer.OUTBOX[-1]
    assert mail["to"] == ["bianchi@cliente.test"] and "122,00 €" in mail["html"] and "Promemoria" in mail["subject"]
    # automatico: a 40 giorni scatta il 2° livello (soglie 7/30/60)
    cfg = client.get(f"{SC}/solleciti/impostazioni", headers=h).json()
    cfg["auto"] = True
    assert client.put(f"{SC}/solleciti/impostazioni", headers=h, json=cfg).status_code == 200
    from app.core.db import new_session
    from app.scadenzario.reminders import run_all_tenants
    run_all_tenants(new_session, date.today())
    hist = client.get(f"{SC}/solleciti/storico", headers=h).json()
    assert [x["level"] for x in hist] == [2, 1] and hist[0]["automatic"] is True
    run_all_tenants(new_session, date.today())  # nessun doppione
    assert len(client.get(f"{SC}/solleciti/storico", headers=h).json()) == 2
    wa = client.post(f"{SC}/solleciti/whatsapp", headers=h, json={"party_id": cust["id"]}).json()
    assert wa["url"].startswith("https://wa.me/393331234567") and "122,00" in wa["text"]
    # cliente in ritardo oltre la soglia: la vendita si blocca (criterio "blocca" del cliente)
    cfg["block_overdue_days"] = 30
    client.put(f"{SC}/solleciti/impostazioni", headers=h, json=cfg)
    d = client.post(f"{V}/documenti", headers=h, json={"doc_type": "FTI", "party_id": cust["id"], "lines": [{"description": "x", "quantity": "1", "unit_price": "1"}]}).json()
    r = client.post(f"{V}/documenti/{d['id']}/conferma", headers=h, json={})
    assert r.status_code == 409 and "ritardo" in r.json()["detail"]["message"]


def test_insoluto(client, admin_headers):
    h, cust, _, _, _ = setup(client, admin_headers, "Insoluti Srl")
    invoice(client, h, cust, "100")
    i = rows(client, h)["rows"][0]
    client.post(f"{SC}/scadenze/{i['id']}/pagamenti", headers=h, json={"pay_date": date.today().isoformat()})
    r = client.post(f"{SC}/scadenze/{i['id']}/insoluta", headers=h, json={"unpaid": True}).json()
    assert r["unpaid"] is True and r["status"] == "aperta" and r["payments"] == []
    assert rows(client, h, stato="insolute")["total"] == 1
    st = client.get(f"{V}/clienti/{cust['id']}/fido", headers=h).json()
    assert st["insolvent"] is True and st["blocked"] is True
