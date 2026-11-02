"""Pagamenti online degli abbonamenti (contratto comune progetto_blucode_informatica/comune/pagamenti.md).

Stripe, PayPal e Aruba sono simulati con httpx.MockTransport: nessuna chiamata esterna."""

import json
import time
from datetime import timedelta
from decimal import Decimal
from urllib.parse import parse_qs

import httpx
import pytest
from lxml import etree
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import new_session
from app.core.mailer import OUTBOX
from app.fatturapa import service as sdi_service
from app.fatturapa import xml_builder as xb
from app.pagamenti import invoice as inv
from app.pagamenti import providers as pv
from app.pagamenti.models import Payment
from app.saas.console import build_summary
from app.saas.service import today
from tests.conftest import activate_and_login, make_tenant

P = "/api/app/pagamenti"
A = "/api/admin/pagamenti"
WHSEC = "whsec_test_segreto"
NS = {"p": xb.NS}

AZIENDA = {"tipo": "azienda", "denominazione": "Ferramenta Rossi Srl", "partita_iva": "02345670984", "indirizzo": "Via Roma 1",
           "cap": "73100", "comune": "Lecce", "provincia": "LE", "codice_destinatario": "KRRH6B9", "email": "amministrazione@rossi.it"}
PRIVATO = {"tipo": "privato", "nome": "Mario", "cognome": "Rossi", "codice_fiscale": "RSSMRA80A01H501U", "indirizzo": "Via Verdi 2",
           "cap": "00100", "comune": "Roma", "provincia": "RM"}
PA = {"tipo": "pa", "denominazione": "Comune di Prova", "codice_fiscale": "80000000002", "indirizzo": "Piazza Municipio 1",
      "cap": "73036", "comune": "Muro Leccese", "provincia": "LE", "codice_destinatario": "UF1234"}


class Gateway:
    """Stripe e PayPal finti: registrano le richieste e rispondono come le API vere."""

    def __init__(self):
        self.stripe_sessions: list[dict] = []
        self.paypal_orders: list[dict] = []
        self.captures = 0
        self.capture_fails = False
        self.verify = "SUCCESS"
        self.expired: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "api.stripe.com":
            assert request.headers["Authorization"] == "Bearer sk_test_123"
            if path == "/v1/checkout/sessions":
                form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
                sid = f"cs_test_{len(self.stripe_sessions) + 1}"
                self.stripe_sessions.append({"id": sid, "form": form, "idem": request.headers.get("Idempotency-Key")})
                return httpx.Response(200, json={"id": sid, "url": f"https://checkout.stripe.com/c/pay/{sid}"})
            if path.endswith("/expire"):
                self.expired.append(path.split("/")[-2])
                return httpx.Response(200, json={})
        if "paypal.com" in request.url.host:
            if path == "/v1/oauth2/token":
                return httpx.Response(200, json={"access_token": "pp-token", "expires_in": 3000})
            assert request.headers["Authorization"] == "Bearer pp-token"
            if path == "/v2/checkout/orders":
                body = json.loads(request.content)
                oid = f"ORDER{len(self.paypal_orders) + 1}"
                self.paypal_orders.append({"id": oid, "body": body})
                return httpx.Response(201, json={"id": oid, "status": "PAYER_ACTION_REQUIRED", "links": [
                    {"rel": "self", "href": f"https://api-m.sandbox.paypal.com/v2/checkout/orders/{oid}"},
                    {"rel": "payer-action", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={oid}"}]})
            if path.endswith("/capture"):
                self.captures += 1
                if self.capture_fails:
                    return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "INSTRUMENT_DECLINED"}]})
                return httpx.Response(201, json={"id": path.split("/")[-2], "status": "COMPLETED", "purchase_units": [
                    {"payments": {"captures": [{"id": "CAPTURE1", "status": "COMPLETED"}]}}]})
            if path == "/v1/notifications/verify-webhook-signature":
                body = json.loads(request.content)
                assert body["webhook_id"] == "WH-123"
                return httpx.Response(200, json={"verification_status": self.verify})
        return httpx.Response(404, json={"error": "not mocked", "path": path})


@pytest.fixture
def gw(monkeypatch):
    s = get_settings()
    for k, v in {"stripe_secret_key": "sk_test_123", "stripe_webhook_secret": WHSEC, "paypal_client_id": "pp-id",
                 "paypal_secret": "pp-secret", "paypal_webhook_id": "WH-123", "paypal_mode": "sandbox",
                 "bonifico_iban": "IT60X0542811101000000123456", "bonifico_intestatario": "BluCode Informatica",
                 "cedente_denominazione": "BluCode Informatica", "cedente_piva": "05357210755", "cedente_cf": "",
                 "cedente_indirizzo": "Via Napoli 78", "cedente_cap": "73036", "cedente_comune": "Muro Leccese",
                 "cedente_provincia": "LE", "regime_fiscale": "RF19", "bollo_a_carico": "cliente", "fatture_sezionale": "BB",
                 "fatture_invio": "manuale", "pagamenti_metodi": "carta,paypal,bonifico",
                 "public_url": "https://blubeauty.test"}.items():
        monkeypatch.setattr(s, k, v)
    g = Gateway()
    monkeypatch.setattr(pv, "_transport", httpx.MockTransport(g))
    return g


@pytest.fixture
def customer(client, admin_headers):
    t = make_tenant(client, admin_headers, "Ferramenta Rossi", plan="BASE", email="rossi@test.it")
    h = activate_and_login(client, t)
    OUTBOX.clear()  # email di attivazione: i test contano solo quelle dei pagamenti
    return t, h


def _billing(client, h, data=AZIENDA):
    r = client.put(f"{P}/dati-fatturazione", json=data, headers=h)
    assert r.status_code == 200, r.text
    return r.json()["dati_fatturazione"]


def _period(owner_db, tenant_id, start, end, **cols):
    sets = "".join(f", {k} = :{k}" for k in cols)
    owner_db.execute(text(f"UPDATE subscriptions SET start_date = :s, end_date = :e{sets} WHERE tenant_id = :t"),
                     {"s": start, "e": end, "t": tenant_id, **cols})
    owner_db.commit()


def _subs(owner_db, tenant_id):
    owner_db.expire_all()
    return owner_db.execute(text("SELECT start_date, end_date, amount, period, is_trial FROM subscriptions "
                                 "WHERE tenant_id = :t ORDER BY start_date"), {"t": tenant_id}).all()


def _payment(owner_db, pid) -> Payment:
    owner_db.expire_all()
    return owner_db.get(Payment, pid)


def _stripe_event(session_id, pid, total_cents, evt="evt_1", kind="checkout.session.completed", paid="paid"):
    return {"id": evt, "type": kind, "data": {"object": {
        "id": session_id, "object": "checkout.session", "client_reference_id": pid, "metadata": {"payment_id": pid},
        "payment_status": paid, "amount_total": total_cents, "currency": "eur", "payment_intent": "pi_123"}}}


def _post_stripe(client, event, secret=WHSEC, ts=None):
    body = json.dumps(event).encode()
    return client.post("/api/pagamenti/webhook/stripe", content=body,
                       headers={"Stripe-Signature": pv.stripe_sign(body, secret, ts), "Content-Type": "application/json"})


PP_HEADERS = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/v1/notifications/certs/X",
              "PAYPAL-TRANSMISSION-ID": "t-1", "PAYPAL-TRANSMISSION-SIG": "sig", "PAYPAL-TRANSMISSION-TIME": "2026-10-29T10:00:00Z"}


def _paypal_capture_event(order_id, pid, value, evt="WH-EVT-1"):
    return {"id": evt, "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {
        "id": "CAPTURE1", "status": "COMPLETED", "custom_id": pid, "amount": {"currency_code": "EUR", "value": value},
        "supplementary_data": {"related_ids": {"order_id": order_id}}}}


def _xml(owner_db, pid):
    p = _payment(owner_db, pid)
    return p, etree.fromstring(p.invoice_xml)


# ====================================================================== dati di fatturazione


def test_dati_fatturazione_validati(client, gw, customer):
    _, h = customer
    bad = {**AZIENDA, "partita_iva": "02345670985"}
    r = client.put(f"{P}/dati-fatturazione", json=bad, headers=h)
    assert r.status_code == 422 and "Partita IVA" in r.json()["detail"]["message"]
    r = client.put(f"{P}/dati-fatturazione", json={**AZIENDA, "codice_destinatario": "ABC"}, headers=h)
    assert r.status_code == 422 and "7 caratteri" in r.json()["detail"]["message"]
    r = client.put(f"{P}/dati-fatturazione", json={**AZIENDA, "codice_destinatario": None, "pec": None}, headers=h)
    assert r.status_code == 422 and "PEC" in r.json()["detail"]["message"]
    r = client.put(f"{P}/dati-fatturazione", json={**PRIVATO, "codice_fiscale": "RSSMRA80A01H501X"}, headers=h)
    assert r.status_code == 422 and "Codice fiscale" in r.json()["detail"]["message"]
    r = client.put(f"{P}/dati-fatturazione", json={**PA, "codice_destinatario": "UF12345"}, headers=h)
    assert r.status_code == 422 and "univoco ufficio" in r.json()["detail"]["message"]
    # privato senza codice destinatario: 0000000
    data = _billing(client, h, PRIVATO)
    assert data["codice_destinatario"] == "0000000"
    # prefisso IT tolto, maiuscole
    data = _billing(client, h, {**AZIENDA, "partita_iva": "it 02345670984", "provincia": "le"})
    assert data["partita_iva"] == "02345670984" and data["provincia"] == "LE"
    o = client.get(f"{P}/opzioni", headers=h).json()
    assert o["dati_completi"] is True and o["dati_fatturazione"]["denominazione"] == "Ferramenta Rossi Srl"


def test_checkout_richiede_i_dati_di_fatturazione(client, gw, customer):
    _, h = customer
    r = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "annuale", "metodo": "bonifico"}, headers=h)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "dati_fatturazione"


def test_metodi_senza_chiavi_nascosti(client, gw, customer, monkeypatch):
    _, h = customer
    o = client.get(f"{P}/opzioni", headers=h).json()
    assert [m["code"] for m in o["metodi"]] == ["carta", "paypal", "bonifico"]
    base = next(p for p in o["piani"] if p["code"] == "BASE")
    assert base["prezzi"]["annuale"] == {"importo": "290.00", "bollo": "2.00", "totale": "292.00"}
    assert base["prezzi"]["mensile"] == {"importo": "29.00", "bollo": "0.00", "totale": "29.00"}
    s = get_settings()
    monkeypatch.setattr(s, "stripe_webhook_secret", "")
    monkeypatch.setattr(s, "paypal_secret", "")
    o = client.get(f"{P}/opzioni", headers=h).json()
    assert [m["code"] for m in o["metodi"]] == ["bonifico"]  # il bonifico funziona senza account
    _billing(client, h)
    r = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "annuale", "metodo": "carta"}, headers=h)
    assert r.status_code == 400
    monkeypatch.setattr(s, "bonifico_iban", "")
    assert client.get(f"{P}/opzioni", headers=h).json()["metodi"] == []
    # i webhook dei gestori non configurati non esistono
    assert client.post("/api/pagamenti/webhook/stripe", content=b"{}").status_code == 404
    assert client.post("/api/pagamenti/webhook/paypal", json={}).status_code == 404


# ====================================================================== carta (Stripe)


def test_carta_checkout_importo_dal_server(client, gw, customer, owner_db):
    t, h = customer
    _billing(client, h)
    r = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "annuale", "metodo": "carta", "importo": "0.01",
                                           "totale": 1}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["redirect_url"] == "https://checkout.stripe.com/c/pay/cs_test_1"
    form = gw.stripe_sessions[0]["form"]
    assert form["line_items[0][price_data][unit_amount]"] == "29200"  # 290 + 2 di bollo, dal listino
    assert form["line_items[0][price_data][currency]"] == "eur" and form["mode"] == "payment"
    assert "payment_method_types[0]" not in form  # Google Pay e Apple Pay arrivano con il metodo «card» di Stripe
    assert form["customer_email"] == "amministrazione@rossi.it"
    assert form["success_url"].startswith("https://blubeauty.test/pagamento/esito?stato=ok")
    assert gw.stripe_sessions[0]["idem"] == f"checkout-{r.json()['pagamento']}"
    p = _payment(owner_db, r.json()["pagamento"])
    assert p.status == "in_attesa" and p.total == Decimal("292.00") and p.provider_ref == "cs_test_1"
    assert p.invoice_number is None and p.invoice_xml is None and not OUTBOX


def test_stripe_webhook_firma_conferma_e_idempotenza(client, gw, customer, owner_db):
    t, h = customer
    _billing(client, h)
    end_before = _subs(owner_db, t["id"])[-1].end_date
    pid = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "annuale", "metodo": "carta"}, headers=h).json()["pagamento"]
    ev = _stripe_event("cs_test_1", pid, 29200)

    # firma sbagliata, segreto sbagliato, firma vecchia (replay oltre 5 minuti), firma assente
    body = json.dumps(ev).encode()
    assert client.post("/api/pagamenti/webhook/stripe", content=body, headers={"Stripe-Signature": "t=1,v1=abc"}).status_code == 400
    assert _post_stripe(client, ev, secret="whsec_altro").status_code == 400
    assert _post_stripe(client, ev, ts=int(time.time()) - 301).status_code == 400
    assert client.post("/api/pagamenti/webhook/stripe", content=body).status_code == 400
    tampered = json.dumps({**ev, "id": "evt_x"}).encode()
    assert client.post("/api/pagamenti/webhook/stripe", content=tampered,
                       headers={"Stripe-Signature": pv.stripe_sign(body, WHSEC)}).status_code == 400
    assert _payment(owner_db, pid).status == "in_attesa" and not OUTBOX

    r = _post_stripe(client, ev)
    assert r.status_code == 200, r.text
    p = _payment(owner_db, pid)
    assert p.status == "pagato" and p.confirmed_by == "webhook Stripe" and p.provider_payment_ref == "pi_123"
    assert p.invoice_label == "1/BB" and p.invoice_year == today().year and p.invoice_format == "FPR12"
    subs = _subs(owner_db, t["id"])
    assert len(subs) == 2 and subs[-1].start_date == end_before + timedelta(days=1) and subs[-1].amount == Decimal("290.00")
    assert p.period_start == subs[-1].start_date and p.period_end == subs[-1].end_date
    # email: proforma al cliente, XML + PDF a BluCode
    assert len(OUTBOX) == 2
    cust, adm = OUTBOX
    assert cust["to"] == ["amministrazione@rossi.it"] and cust["subject"] == "Ricevuta di pagamento BluBeauty"
    assert [a[0] for a in cust["attachments"]] == [f"Proforma_1_BB_{today().year}.pdf"]
    assert adm["to"] == ["titolare@blubeauty.test"] and "1/BB" in adm["subject"]
    assert [a[2] for a in adm["attachments"]] == ["application/xml", "application/pdf"]
    assert adm["attachments"][0][0].startswith("IT05357210755_")

    # stesso evento rimandato (replay) e un secondo evento per la stessa sessione: nessun altro periodo né fattura
    assert _post_stripe(client, ev).status_code == 200
    assert _post_stripe(client, {**ev, "id": "evt_2"}).status_code == 200
    assert len(_subs(owner_db, t["id"])) == 2 and len(OUTBOX) == 2
    assert owner_db.execute(text("SELECT last_number FROM invoice_counters")).scalar_one() == 1

    # il cliente vede il pagamento e scarica la proforma
    st = client.get(f"{P}/{pid}", headers=h).json()
    assert st["stato"] == "pagato" and st["fattura"] == "1/BB"
    pdf = client.get(f"{P}/{pid}/pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_stripe_importo_diverso_non_conferma(client, gw, customer, owner_db):
    _, h = customer
    _billing(client, h)
    pid = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "carta"}, headers=h).json()["pagamento"]
    assert _post_stripe(client, _stripe_event("cs_test_1", pid, 100)).status_code == 200
    p = _payment(owner_db, pid)
    assert p.status == "in_attesa" and "diverso" in p.error and p.invoice_number is None and not OUTBOX
    # sessione scaduta → fallito
    assert _post_stripe(client, _stripe_event("cs_test_1", pid, 2900, evt="evt_9", kind="checkout.session.expired")).status_code == 200
    assert _payment(owner_db, pid).status == "fallito"


def test_stripe_evento_di_altra_sessione_ignorato(client, gw, customer, owner_db):
    _, h = customer
    _billing(client, h)
    pid = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "carta"}, headers=h).json()["pagamento"]
    assert _post_stripe(client, _stripe_event("cs_falsa", pid, 2900)).status_code == 200
    assert _payment(owner_db, pid).status == "in_attesa"


# ====================================================================== PayPal


def test_paypal_ordine_cattura_e_webhook(client, gw, customer, owner_db):
    t, h = customer
    _billing(client, h)
    r = client.post(f"{P}/checkout", json={"piano": "PLUS", "periodicita": "mensile", "metodo": "paypal"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["redirect_url"] == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1"
    pid = r.json()["pagamento"]
    unit = gw.paypal_orders[0]["body"]["purchase_units"][0]
    assert unit["amount"] == {"currency_code": "EUR", "value": "49.00"} and unit["custom_id"] == pid
    assert gw.paypal_orders[0]["body"]["intent"] == "CAPTURE"
    ctx = gw.paypal_orders[0]["body"]["payment_source"]["paypal"]["experience_context"]
    assert ctx["return_url"] == f"https://blubeauty.test/api/pagamenti/paypal/ritorno?id={pid}"

    # ritorno del cliente: cattura lato server, poi la pagina di esito attende il webhook
    r = client.get(f"/api/pagamenti/paypal/ritorno?id={pid}&token=ORDER1&PayerID=X", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"https://blubeauty.test/pagamento/esito?stato=ok&id={pid}"
    assert gw.captures == 1 and _payment(owner_db, pid).status == "in_attesa" and not OUTBOX
    # token di un altro ordine: nessuna cattura
    r = client.get(f"/api/pagamenti/paypal/ritorno?id={pid}&token=ALTRO", follow_redirects=False)
    assert "stato=errore" in r.headers["location"] and gw.captures == 1

    ev = _paypal_capture_event("ORDER1", pid, "49.00")
    gw.verify = "FAILURE"
    assert client.post("/api/pagamenti/webhook/paypal", json=ev, headers=PP_HEADERS).status_code == 400
    gw.verify = "SUCCESS"
    assert client.post("/api/pagamenti/webhook/paypal", json=ev).status_code == 400  # senza intestazioni di firma
    assert _payment(owner_db, pid).status == "in_attesa"
    r = client.post("/api/pagamenti/webhook/paypal", json=ev, headers=PP_HEADERS)
    assert r.status_code == 200, r.text
    p = _payment(owner_db, pid)
    assert p.status == "pagato" and p.confirmed_by == "webhook PayPal" and p.invoice_label == "1/BB"
    assert p.plan_code == "PLUS" and p.stamp == Decimal("0") and p.total == Decimal("49.00")
    _, x = _xml(owner_db, pid)
    assert x.findtext(".//DettaglioPagamento/ModalitaPagamento") == "MP08"
    assert len(OUTBOX) == 2
    # replay
    assert client.post("/api/pagamenti/webhook/paypal", json=ev, headers=PP_HEADERS).status_code == 200
    assert len(_subs(owner_db, t["id"])) == 2 and len(OUTBOX) == 2


# ====================================================================== bonifico


def test_bonifico_nulla_prima_della_conferma(client, gw, customer, owner_db, admin_headers):
    t, h = customer
    _billing(client, h)
    subs_before = _subs(owner_db, t["id"])
    r = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "annuale", "metodo": "bonifico"}, headers=h)
    assert r.status_code == 200, r.text
    b = r.json()["bonifico"]
    pid = r.json()["pagamento"]
    assert b["iban"] == "IT60X0542811101000000123456" and b["intestatario"] == "BluCode Informatica"
    assert b["importo"] == "292.00" and b["causale"] == f"BLUCODE BB {pid.replace('-', '')[:8].upper()}"
    # prima della conferma: niente email, numero, XML, PDF, periodo
    p = _payment(owner_db, pid)
    assert p.status == "in_attesa" and p.invoice_number is None and p.invoice_xml is None and p.invoice_pdf is None
    assert not OUTBOX and _subs(owner_db, t["id"]) == subs_before
    assert owner_db.execute(text("SELECT count(*) FROM invoice_counters")).scalar_one() == 0
    assert client.get(f"{P}/{pid}/pdf", headers=h).status_code == 404
    assert client.get(f"{A}/{pid}/xml", headers=admin_headers).status_code == 404
    assert client.post(f"{A}/{pid}/reinvia", headers=admin_headers).status_code == 409
    assert not OUTBOX
    # la pagina mostra il bonifico in attesa; ripetere la stessa scelta non crea un secondo pagamento
    assert client.get(f"{P}/opzioni", headers=h).json()["bonifico_in_attesa"]["id"] == pid
    again = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "annuale", "metodo": "bonifico"}, headers=h).json()
    assert again["pagamento"] == pid

    rows = client.get(A, params={"stato": "in_attesa"}, headers=admin_headers).json()
    assert [x["id"] for x in rows] == [pid] and rows[0]["azienda"] == "Ferramenta Rossi"

    r = client.post(f"{A}/{pid}/conferma-bonifico", headers=admin_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["stato"] == "pagato" and d["fattura"] == "1/BB" and d["confermato_da"] == "super admin admin@blubeauty.test"
    assert len(_subs(owner_db, t["id"])) == len(subs_before) + 1
    assert len(OUTBOX) == 2
    _, x = _xml(owner_db, pid)
    dp = x.find(".//DettaglioPagamento")
    assert dp.findtext("ModalitaPagamento") == "MP05" and dp.findtext("IBAN") == "IT60X0542811101000000123456"
    # di nuovo: idempotente
    assert client.post(f"{A}/{pid}/conferma-bonifico", headers=admin_headers).status_code == 200
    assert len(_subs(owner_db, t["id"])) == len(subs_before) + 1 and len(OUTBOX) == 2
    # pagato: non si annulla; download e reinvio
    assert client.post(f"{A}/{pid}/annulla", headers=admin_headers).status_code == 409
    xr = client.get(f"{A}/{pid}/xml", headers=admin_headers)
    assert xr.status_code == 200 and xb.validate(xr.content) == []
    assert client.get(f"{A}/{pid}/pdf", headers=admin_headers).content.startswith(b"%PDF")
    r = client.post(f"{A}/{pid}/reinvia", json={"cliente": True, "blucode": False}, headers=admin_headers)
    assert r.status_code == 200 and len(OUTBOX) == 3 and OUTBOX[-1]["subject"] == "Ricevuta di pagamento BluBeauty"
    assert client.get(f"{A}/export", headers=admin_headers).text.count("1/BB") == 1


def test_bonifico_annullato(client, gw, customer, owner_db, admin_headers):
    _, h = customer
    _billing(client, h)
    pid = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "bonifico"}, headers=h).json()["pagamento"]
    r = client.post(f"{A}/{pid}/annulla", headers=admin_headers)
    assert r.status_code == 200 and r.json()["stato"] == "annullato"
    assert client.post(f"{A}/{pid}/conferma-bonifico", headers=admin_headers).status_code == 409
    assert not OUTBOX and client.get(f"{P}/opzioni", headers=h).json()["bonifico_in_attesa"] is None
    # una nuova scelta diversa sostituisce il bonifico in attesa
    p1 = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "bonifico"}, headers=h).json()["pagamento"]
    p2 = client.post(f"{P}/checkout", json={"piano": "PLUS", "periodicita": "mensile", "metodo": "bonifico"}, headers=h).json()["pagamento"]
    assert p1 != p2 and _payment(owner_db, p1).status == "annullato" and _payment(owner_db, p2).status == "in_attesa"


def test_email_fallita_non_annulla_la_conferma(client, gw, customer, owner_db, monkeypatch):
    _, h = customer
    _billing(client, h)
    pid = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "carta"}, headers=h).json()["pagamento"]

    def boom(*a, **k):
        raise OSError("SMTP non raggiungibile")

    from app.pagamenti import service as svc
    monkeypatch.setattr(svc, "send_email", boom)
    assert _post_stripe(client, _stripe_event("cs_test_1", pid, 2900)).status_code == 200
    p = _payment(owner_db, pid)
    assert p.status == "pagato" and p.invoice_label == "1/BB" and "SMTP" in p.email_error and p.customer_email_at is None


def test_conferma_manuale_solo_bonifico(client, gw, customer, admin_headers):
    _, h = customer
    _billing(client, h)
    pid = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "carta"}, headers=h).json()["pagamento"]
    assert client.post(f"{A}/{pid}/conferma-bonifico", headers=admin_headers).status_code == 409
    r = client.post(f"{A}/{pid}/annulla", headers=admin_headers)
    assert r.status_code == 200 and gw.expired == ["cs_test_1"]


# ====================================================================== periodi nei vari stati


def _pay_transfer(client, h, admin_headers, period="annuale", plan="BASE"):
    pid = client.post(f"{P}/checkout", json={"piano": plan, "periodicita": period, "metodo": "bonifico"}, headers=h).json()["pagamento"]
    r = client.post(f"{A}/{pid}/conferma-bonifico", headers=admin_headers)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("case", ["attivo", "tolleranza", "sola_lettura", "sospeso", "sospeso_a_mano", "prova", "prova_scaduta"])
def test_nuovo_periodo_in_ogni_stato(client, gw, customer, owner_db, admin_headers, case):
    t, h = customer
    _billing(client, h)
    on = today()
    if case == "attivo":
        _period(owner_db, t["id"], on - timedelta(days=300), on + timedelta(days=20))
        expected = on + timedelta(days=21)
    elif case == "tolleranza":
        _period(owner_db, t["id"], on - timedelta(days=370), on - timedelta(days=5))
        expected = on
    elif case == "sola_lettura":
        _period(owner_db, t["id"], on - timedelta(days=400), on - timedelta(days=25))
        expected = on
    elif case == "sospeso":
        _period(owner_db, t["id"], on - timedelta(days=500), on - timedelta(days=80))
        expected = on
    elif case == "sospeso_a_mano":
        owner_db.execute(text("UPDATE tenants SET suspended = true WHERE id = :t"), {"t": t["id"]})
        owner_db.commit()
        _period(owner_db, t["id"], on - timedelta(days=300), on + timedelta(days=20))
        expected = on + timedelta(days=21)
    elif case == "prova":
        _period(owner_db, t["id"], on - timedelta(days=3), on + timedelta(days=3), is_trial=True)
        expected = on
    else:
        _period(owner_db, t["id"], on - timedelta(days=10), on - timedelta(days=4), is_trial=True)
        expected = on
    st = client.get("/api/app/status", headers=h).json()
    assert st["status"] == {"sospeso_a_mano": "sospeso", "attivo": "in_scadenza"}.get(case, case)
    # anche da sospesi o in sola lettura si vede la pagina e si paga
    assert client.get(f"{P}/opzioni", headers=h).status_code == 200
    d = _pay_transfer(client, h, admin_headers)
    assert d["periodo"]["dal"] == expected.isoformat()
    subs = _subs(owner_db, t["id"])
    new = subs[-1]
    assert new.start_date == expected and new.end_date == expected.replace(year=expected.year + 1) - timedelta(days=1)
    assert not new.is_trial and new.period == "annuale"
    if case == "prova":  # la prova si chiude a ieri e resta nello storico
        assert subs[0].is_trial and subs[0].end_date == on - timedelta(days=1)
    st = client.get("/api/app/status", headers=h).json()
    assert st["access"] == "full" and st["status"] == "attivo"
    assert owner_db.execute(text("SELECT suspended FROM tenants WHERE id = :t"), {"t": t["id"]}).scalar_one() is False


def test_bloccati_possono_pagare_ma_non_altro(client, gw, customer, owner_db):
    t, h = customer
    on = today()
    _period(owner_db, t["id"], on - timedelta(days=500), on - timedelta(days=80))
    assert client.get("/api/app/companies", headers=h).status_code == 402
    assert client.put(f"{P}/dati-fatturazione", json=AZIENDA, headers=h).status_code == 200
    r = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "carta"}, headers=h)
    assert r.status_code == 200 and r.json()["redirect_url"]


def test_mensile_e_pagamenti_isolati_tra_aziende(client, gw, customer, owner_db, admin_headers):
    t, h = customer
    _billing(client, h)
    d = _pay_transfer(client, h, admin_headers, period="mensile")
    other = make_tenant(client, admin_headers, "Altra", plan="BASE", email="altra@test.it")
    h2 = activate_and_login(client, other)
    assert client.get(f"{P}/{d['id']}", headers=h2).status_code == 404
    assert client.get(f"{P}/opzioni", headers=h2).json()["pagamenti"] == []
    sub = _subs(owner_db, t["id"])[-1]
    assert sub.period == "mensile" and sub.amount == Decimal("29.00")


def test_pagamento_non_in_impersonificazione(client, gw, customer, admin_headers):
    t, h = customer
    _billing(client, h)
    admin_user = next(u for u in client.get("/api/app/users", headers=h).json()["users"] if u["role"] == "amministratore")
    r = client.post(f"/api/admin/tenants/{t['id']}/impersonate/{admin_user['id']}", headers=admin_headers)
    assert r.status_code == 200, r.text
    hi = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get(f"{P}/opzioni", headers=hi).status_code == 200  # l'assistenza vede la pagina
    r = client.post(f"{P}/checkout", json={"piano": "BASE", "periodicita": "mensile", "metodo": "bonifico"}, headers=hi)
    assert r.status_code == 403


# ====================================================================== numerazione


def test_numerazione_annuale_senza_buchi():
    db = new_session()
    try:
        assert [inv.next_number(db, "BB", 2026) for _ in range(3)] == [1, 2, 3]
        assert inv.next_number(db, "BB", 2027) == 1  # ogni anno riparte da 1
        assert inv.next_number(db, "BM", 2026) == 1  # un sezionale per software
        db.commit()
        assert inv.next_number(db, "BB", 2026) == 4
        db.rollback()  # conferma fallita: il numero non si consuma
        assert inv.next_number(db, "BB", 2026) == 4
        db.commit()
    finally:
        db.close()


def test_numeri_consecutivi_e_cambio_anno(client, gw, customer, admin_headers, owner_db, monkeypatch):
    _, h = customer
    _billing(client, h)
    labels = [_pay_transfer(client, h, admin_headers, period="mensile")["fattura"] for _ in range(3)]
    assert labels == ["1/BB", "2/BB", "3/BB"]
    from app.pagamenti import service as svc
    from datetime import date
    monkeypatch.setattr(svc, "today", lambda: date(today().year + 1, 1, 2))
    d = _pay_transfer(client, h, admin_headers, period="mensile")
    assert d["fattura"] == "1/BB" and d["fattura_data"] == f"{today().year + 1}-01-02"


# ====================================================================== XML e PDF


def _confirmed(client, h, admin_headers, owner_db, data, plan="BASE", period="annuale"):
    _billing(client, h, data)
    d = _pay_transfer(client, h, admin_headers, period=period, plan=plan)
    return _xml(owner_db, d["id"])


def test_xml_forfettario_con_bollo_valido(client, gw, customer, admin_headers, owner_db):
    _, h = customer
    p, x = _confirmed(client, h, admin_headers, owner_db, AZIENDA)
    assert xb.validate(p.invoice_xml) == [] and p.invoice_errors == []
    assert x.get("versione") == "FPR12"
    assert x.findtext(".//DatiTrasmissione/IdTrasmittente/IdCodice") == "05357210755"  # invio manuale: trasmittente BluCode
    assert x.findtext(".//DatiTrasmissione/CodiceDestinatario") == "KRRH6B9"
    assert x.findtext(".//CedentePrestatore//RegimeFiscale") == "RF19"
    assert x.findtext(".//CedentePrestatore//IdCodice") == "05357210755"
    assert x.findtext(".//CedentePrestatore/Sede/Comune") == "Muro Leccese"
    assert x.findtext(".//CessionarioCommittente//Denominazione") == "Ferramenta Rossi Srl"
    dg = x.find(".//DatiGeneraliDocumento")
    assert dg.findtext("TipoDocumento") == "TD01" and dg.findtext("Numero") == "1/BB"
    assert dg.findtext("DatiBollo/BolloVirtuale") == "SI" and dg.findtext("DatiBollo/ImportoBollo") == "2.00"
    assert dg.findtext("ImportoTotaleDocumento") == "292.00"
    assert "regime forfettario" in "".join(c.text for c in dg.findall("Causale"))
    lines = x.findall(".//DettaglioLinee")
    assert [ln.findtext("Descrizione")[:22] for ln in lines] == ["Abbonamento BluBeauty ", "Rimborso imposta di bo"]
    assert [ln.findtext("PrezzoTotale") for ln in lines] == ["290.00", "2.00"]
    assert all(ln.findtext("AliquotaIVA") == "0.00" and ln.findtext("Natura") == "N2.2" for ln in lines)
    r = x.find(".//DatiRiepilogo")
    assert (r.findtext("Natura"), r.findtext("ImponibileImporto"), r.findtext("Imposta")) == ("N2.2", "292.00", "0.00")
    assert x.findtext(".//DettaglioPagamento/ImportoPagamento") == "292.00"


def test_xml_sotto_soglia_senza_bollo(client, gw, customer, admin_headers, owner_db):
    _, h = customer
    p, x = _confirmed(client, h, admin_headers, owner_db, AZIENDA, period="mensile")
    assert xb.validate(p.invoice_xml) == []
    assert x.find(".//DatiBollo") is None and len(x.findall(".//DettaglioLinee")) == 1
    assert x.findtext(".//ImportoTotaleDocumento") == "29.00"


def test_xml_bollo_a_carico_del_cedente(client, gw, customer, admin_headers, owner_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "bollo_a_carico", "cedente")
    _, h = customer
    p, x = _confirmed(client, h, admin_headers, owner_db, AZIENDA)
    assert xb.validate(p.invoice_xml) == []
    assert x.findtext(".//DatiBollo/ImportoBollo") == "2.00" and len(x.findall(".//DettaglioLinee")) == 1
    assert p.total == Decimal("290.00") and x.findtext(".//ImportoTotaleDocumento") == "290.00"


def test_xml_pa_e_privato(client, gw, customer, admin_headers, owner_db):
    _, h = customer
    p, x = _confirmed(client, h, admin_headers, owner_db, PA)
    assert xb.validate(p.invoice_xml) == [] and p.invoice_format == "FPA12"
    assert x.get("versione") == "FPA12" and x.findtext(".//CodiceDestinatario") == "UF1234"
    assert x.findtext(".//CessionarioCommittente//CodiceFiscale") == "80000000002"
    p, x = _confirmed(client, h, admin_headers, owner_db, {**PRIVATO, "pec": "mario@pec.it"})
    assert xb.validate(p.invoice_xml) == [] and x.get("versione") == "FPR12"
    assert x.findtext(".//CodiceDestinatario") == "0000000"
    assert x.findtext(".//CessionarioCommittente//Nome") == "Mario" and x.findtext(".//CessionarioCommittente//Cognome") == "Rossi"
    assert x.find(".//CessionarioCommittente//IdFiscaleIVA") is None


def test_pdf_proforma(client, gw, customer, admin_headers, owner_db):
    _, h = customer
    p, _ = _confirmed(client, h, admin_headers, owner_db, AZIENDA)
    from app.pagamenti.pdf import proforma_pdf

    raw = proforma_pdf(p)
    assert raw.startswith(b"%PDF") and p.invoice_pdf.startswith(b"%PDF")
    import io

    import pypdf
    text_ = " ".join(page.extract_text() for page in pypdf.PdfReader(io.BytesIO(raw)).pages)
    for needle in ("Proforma", "1/BB", "Documento non valido ai fini fiscali", "Rimborso imposta di bollo", "N2.2",
                   "05357210755", "Ferramenta Rossi Srl", "regime forfettario"):
        assert needle in text_, needle


def test_senza_dati_del_cedente_niente_xml_poi_reinvia(client, gw, customer, admin_headers, owner_db, monkeypatch):
    monkeypatch.setattr(get_settings(), "cedente_piva", "")
    _, h = customer
    _billing(client, h)
    d = _pay_transfer(client, h, admin_headers)
    p = _payment(owner_db, d["id"])
    assert p.invoice_label == "1/BB" and p.invoice_xml is None and "CEDENTE_PIVA mancante o non valida" in p.invoice_errors
    assert "non è stato generato" in OUTBOX[-1]["html"] and [a[2] for a in OUTBOX[-1]["attachments"]] == ["application/pdf"]
    monkeypatch.setattr(get_settings(), "cedente_piva", "05357210755")
    r = client.post(f"{A}/{d['id']}/reinvia", headers=admin_headers)
    assert r.status_code == 200 and r.json()["fattura"] == "1/BB" and r.json()["errori_fattura"] == []
    p = _payment(owner_db, d["id"])
    assert xb.validate(p.invoice_xml) == [] and OUTBOX[-1]["attachments"][0][2] == "application/xml"


# ====================================================================== invio SDI (spento di default)


def test_invio_sdi_tramite_aruba(client, gw, customer, admin_headers, owner_db, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "fatture_invio", "sdi")
    monkeypatch.setattr(s, "aruba_username", "PREMIUM")
    monkeypatch.setattr(s, "aruba_password", "pw")
    uploads = []

    def aruba(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth/signin":
            return httpx.Response(200, json={"access_token": "tok1", "refresh_token": "r", "expires_in": 1800})
        if request.url.path == "/services/invoice/upload":
            uploads.append(json.loads(request.content))
            return httpx.Response(200, json={"errorCode": "0000", "uploadFileName": "IT05357210755_abc.xml.p7m"})
        return httpx.Response(404)

    monkeypatch.setattr(sdi_service, "_transport", httpx.MockTransport(aruba))
    from app.fatturapa import aruba as aruba_mod
    monkeypatch.setattr(aruba_mod, "_store", aruba_mod._MemoryStore())
    _, h = customer
    p, x = _confirmed(client, h, admin_headers, owner_db, AZIENDA)
    assert x.findtext(".//IdTrasmittente/IdCodice") == xb.ARUBA_CF and xb.validate(p.invoice_xml) == []
    assert len(uploads) == 1 and uploads[0]["dryRun"] is False
    assert p.sdi_status == "presa_in_carico" and p.sdi_filename == "IT05357210755_abc.xml.p7m"
    assert "inviato allo SDI" in OUTBOX[-1]["html"]


def test_invio_manuale_predefinito():
    assert get_settings().fatture_invio == "manuale" and get_settings().fatture_sezionale == "BB"


def test_firma_stripe_unitaria():
    body = b'{"id":"evt"}'
    now = 1_800_000_000
    hdr = pv.stripe_sign(body, "s", now)
    assert pv.stripe_verify(body, hdr, "s", now=now + 299)["id"] == "evt"
    with pytest.raises(pv.ProviderError):
        pv.stripe_verify(body, hdr, "s", now=now + 301)
    with pytest.raises(pv.ProviderError):
        pv.stripe_verify(body + b" ", hdr, "s", now=now)
    # più firme v1 (rotazione del segreto): basta che una sia giusta
    assert pv.stripe_verify(body, hdr + ",v1=deadbeef", "s", now=now)["id"] == "evt"


# ====================================================================== console, banner, impostazioni


def test_console_incassato_dai_pagamenti(client, gw, customer, admin_headers, owner_db):
    t, h = customer
    db = new_session()
    try:
        before = build_summary(db)["ricavi"]["incassato_mese_corrente"]
    finally:
        db.close()
    _billing(client, h)
    _pay_transfer(client, h, admin_headers, period="annuale")  # periodo nuovo che inizia tra un anno
    # pagamento in attesa: non conta
    client.post(f"{P}/checkout", json={"piano": "PRO", "periodicita": "annuale", "metodo": "bonifico"}, headers=h)
    db = new_session()
    try:
        s = build_summary(db)
    finally:
        db.close()
    # +290 (canone, senza il rimborso del bollo) alla data del pagamento, non alla data di inizio del periodo
    assert s["ricavi"]["incassato_mese_corrente"] == before + 290.0
    assert s["andamento_12_mesi"][-1]["incassato"] == before + 290.0
    assert s["ricavi"]["incassato_anno_corrente"] >= 290.0


def test_banner_rinnova_e_email_con_link_pagamento(client, gw, customer, owner_db):
    t, h = customer
    on = today()
    _period(owner_db, t["id"], on - timedelta(days=360), on + timedelta(days=5))
    st = client.get("/api/app/status", headers=h).json()
    assert st["banner"]["renew"] is True
    assert client.get("/api/app/abbonamento", headers=h).json()["online_payments"] is True
    from app.saas.reminders import run_reminders
    db = new_session()
    try:
        run_reminders(db, on)
        db.commit()
    finally:
        db.close()
    mail = next(m for m in OUTBOX if "scade" in m["subject"])
    assert "https://blubeauty.test/pagamento" in mail["html"] and "Rinnova ora" in mail["html"]


def test_impostazioni_pannello(client, gw, admin_headers, customer):
    _, h = customer
    r = client.get(f"{A}/impostazioni", headers=admin_headers).json()
    assert r["methods"]["carta"]["active"] and r["sezionale"] == "BB" and r["invio"] == "manuale"
    assert r["webhooks"]["stripe"] == "https://blubeauty.test/api/pagamenti/webhook/stripe"
    assert r["cedente_problems"] == [] and "sk_test" not in json.dumps(r) and WHSEC not in json.dumps(r)
    r = client.put(f"{A}/impostazioni", json={"metodi": ["bonifico"], "iban": "it60 x054 2811 1010 0000 0123 456"},
                   headers=admin_headers).json()
    assert r["iban"] == "IT60X0542811101000000123456" and not r["methods"]["carta"]["active"]
    assert [m["code"] for m in client.get(f"{P}/opzioni", headers=h).json()["metodi"]] == ["bonifico"]
    assert client.get(f"{A}/impostazioni").status_code == 401


    assert r["iban"] == "IT60X0542811101000000123456" and not r["methods"]["carta"]["active"]
    assert [m["code"] for m in client.get(f"{P}/opzioni", headers=h).json()["metodi"]] == ["bonifico"]
    assert client.get(f"{A}/impostazioni").status_code == 401


# ====================================================================== acquisto dal sito


def _buy(extra=None, **over):
    body = {"plan_code": "BASE", "method": "carta", "name": "Mario Rossi", "email": "mario@rossi.it", "phone": "333 1",
            "billing": AZIENDA, "privacy": True, "terms": True, "terms_version": "1.0", "elapsed_ms": 20000,
            "return_url": "https://blucodeinformatica.it/acquisto/esito/"}
    body.update(over)
    return body


@pytest.fixture
def pdfs(monkeypatch):
    from app.auth import accounts
    monkeypatch.setattr(accounts, "fetch_pdf", lambda url: b"%PDF-1.4 finto")


def test_acquisto_info_solo_annuale(client, gw):
    r = client.get("/api/public/acquisto").json()
    assert r["enabled"] and r["periodicita"] == "annuale" and r["metodi"] == ["carta", "paypal", "bonifico"]
    assert all(set(p["prezzi"]) == {"annuale"} for p in r["piani"])


def test_acquisto_carta_fattura_subito_con_documenti(client, gw, pdfs, owner_db):
    OUTBOX.clear()
    r = client.post("/api/public/acquisto", json=_buy())
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["redirect_url"].startswith("https://checkout.stripe.com/")
    form = gw.stripe_sessions[0]["form"]
    assert form["success_url"] == "https://blucodeinformatica.it/acquisto/esito/?stato=ok"
    assert form["line_items[0][price_data][unit_amount]"] == "29200"
    order = next(m for m in OUTBOX if m["subject"].startswith("Conferma d'ordine"))
    names = [a[0] for a in order["attachments"]]
    assert any(n.startswith("Contratto_") for n in names) and "informativa-privacy.pdf" in names
    assert any(n.startswith("termini-di-utilizzo") for n in names)
    assert "Manuale" in order["html"] and "Video tutorial" in order["html"]
    assert any(m["to"] == ["mario@rossi.it"] and "credenziali" in m["subject"].lower() or "accesso" in m["subject"].lower() for m in OUTBOX)
    p = _payment(owner_db, j["pagamento"])
    assert p.status == "in_attesa" and p.method == "carta" and p.period == "annuale" and p.invoice_number is None
    # il pagamento arriva dal gestore: fattura elettronica subito
    ev = _stripe_event(p.provider_ref, j["pagamento"], 29200)
    assert _post_stripe(client, ev).status_code == 200
    p = _payment(owner_db, j["pagamento"])
    assert p.status == "pagato" and p.invoice_number == 1 and p.invoice_xml
    # stessa email o stessa partita IVA: niente doppioni
    assert client.post("/api/public/acquisto", json=_buy()).json()["detail"]["code"] == "email_registrata"
    assert client.post("/api/public/acquisto", json=_buy(email="altro@rossi.it")).json()["detail"]["code"] == "azienda_registrata"


def test_acquisto_bonifico_nessuna_fattura_prima_della_conferma(client, gw, pdfs, owner_db, admin_headers):
    OUTBOX.clear()
    r = client.post("/api/public/acquisto", json=_buy(method="bonifico", email="lucia@verdi.it",
                                                      billing={**PRIVATO, "email": "lucia@verdi.it"}))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["bonifico"]["iban"] == "IT60X0542811101000000123456" and j["bonifico"]["importo"] == "292.00"
    order = next(m for m in OUTBOX if m["subject"].startswith("Conferma d'ordine"))
    assert "IT60X0542811101000000123456" in order["html"] and j["bonifico"]["causale"] in order["html"]
    p = _payment(owner_db, j["pagamento"])
    assert p.status == "in_attesa" and p.invoice_number is None and p.invoice_xml is None
    r = client.post(f"{A}/{j["pagamento"]}/conferma-bonifico", headers=admin_headers)
    assert r.status_code == 200, r.text
    p = _payment(owner_db, j["pagamento"])
    assert p.status == "pagato" and p.invoice_number == 1


def test_acquisto_dati_e_consensi_controllati(client, gw, pdfs):
    assert client.post("/api/public/acquisto", json=_buy(privacy=False)).status_code == 422
    assert client.post("/api/public/acquisto", json=_buy(terms_version="0.1")).status_code == 422
    bad = {**AZIENDA, "partita_iva": "12345678901"}
    assert client.post("/api/public/acquisto", json=_buy(billing=bad)).json()["detail"]["code"] == "dati_fatturazione"
    assert client.post("/api/public/acquisto", json=_buy(plan_code="NONESISTE")).status_code == 404
    assert client.post("/api/public/acquisto", json=_buy(method="satispay")).status_code == 422
    assert client.post("/api/public/acquisto", json=_buy(website="x")).json() == {"ok": True, "robot": True}


def test_acquisto_paypal_torna_al_sito_e_fattura_subito(client, gw, pdfs, owner_db):
    from urllib.parse import parse_qs as qs, urlsplit
    OUTBOX.clear()
    r = client.post("/api/public/acquisto", json=_buy(method="paypal"))
    assert r.status_code == 201, r.text
    j = r.json()
    assert j["redirect_url"] == "https://www.sandbox.paypal.com/checkoutnow?token=ORDER1" and j["bonifico"] is None
    pid = j["pagamento"]
    p = _payment(owner_db, pid)
    assert p.status == "in_attesa" and p.method == "paypal" and p.period == "annuale" and p.invoice_number is None
    assert gw.paypal_orders[0]["body"]["purchase_units"][0]["amount"] == {"currency_code": "EUR", "value": "292.00"}
    ctx = gw.paypal_orders[0]["body"]["payment_source"]["paypal"]["experience_context"]
    assert ctx["cancel_url"] == "https://blucodeinformatica.it/acquisto/esito/?stato=annullato"
    ret = urlsplit(ctx["return_url"])
    assert f"{ret.scheme}://{ret.netloc}{ret.path}" == "https://blubeauty.test/api/pagamenti/paypal/ritorno"
    q = {k: v[0] for k, v in qs(ret.query).items()}
    assert q == {"id": pid, "r": "https://blucodeinformatica.it/acquisto/esito/?stato=ok"}
    # email al cliente e a BluCode: «PayPal», mai carta o bonifico, e nessuna istruzione di bonifico
    order = next(m for m in OUTBOX if m["subject"].startswith("Conferma d'ordine"))
    assert "pagamento con PayPal" in order["html"] and "IBAN" not in order["html"] and "carta" not in order["html"]
    notice = next(m for m in OUTBOX if m["subject"].startswith("Nuovo ordine dal sito"))
    assert "annuale, PayPal," in notice["html"] and "Bonifico" not in notice["html"]

    # ritorno da PayPal (PayPal aggiunge token e PayerID): cattura lato server e torna alla pagina del sito
    r = client.get(ctx["return_url"] + "&token=ORDER1&PayerID=X", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "https://blucodeinformatica.it/acquisto/esito/?stato=ok"
    assert gw.captures == 1 and _payment(owner_db, pid).status == "in_attesa"
    # la conferma vera è il webhook: fattura subito, MP08
    ev = _paypal_capture_event("ORDER1", pid, "292.00")
    assert client.post("/api/pagamenti/webhook/paypal", json=ev, headers=PP_HEADERS).status_code == 200
    p = _payment(owner_db, pid)
    assert p.status == "pagato" and p.invoice_number == 1 and p.invoice_xml
    _, x = _xml(owner_db, pid)
    assert x.findtext(".//DettaglioPagamento/ModalitaPagamento") == "MP08"


def test_acquisto_paypal_ritorno_solo_verso_il_sito(client, gw, pdfs):
    from urllib.parse import quote
    pid = client.post("/api/public/acquisto", json=_buy(method="paypal")).json()["pagamento"]
    base = f"/api/pagamenti/paypal/ritorno?id={pid}&token=ORDER1&r="
    app_ok = f"https://blubeauty.test/pagamento/esito?stato=ok&id={pid}"
    for bad in ("https://evil.example/x?stato=ok", "https://blucodeinformatica.it.evil.example/?stato=ok",
                "//evil.example/", "javascript:alert(1)"):
        r = client.get(base + quote(bad, safe=""), follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == app_ok, bad
    # token sbagliato con r valido: si torna al sito con stato=errore, senza catturare
    site = quote("https://blucodeinformatica.it/acquisto/esito/?stato=ok", safe="")
    r = client.get(f"/api/pagamenti/paypal/ritorno?id={pid}&token=ALTRO&r={site}", follow_redirects=False)
    assert r.headers["location"] == "https://blucodeinformatica.it/acquisto/esito/?stato=errore"


def test_acquisto_paypal_cattura_fallita(client, gw, pdfs, owner_db):
    from urllib.parse import quote
    pid = client.post("/api/public/acquisto", json=_buy(method="paypal")).json()["pagamento"]
    gw.capture_fails = True
    site = quote("https://blucodeinformatica.it/acquisto/esito/?stato=ok", safe="")
    r = client.get(f"/api/pagamenti/paypal/ritorno?id={pid}&token=ORDER1&r={site}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "https://blucodeinformatica.it/acquisto/esito/?stato=errore"
    # r non valido: pagina di esito dell'app come prima
    r = client.get(f"/api/pagamenti/paypal/ritorno?id={pid}&token=ORDER1&r=https%3A%2F%2Fevil.example%2F", follow_redirects=False)
    assert r.headers["location"] == f"https://blubeauty.test/pagamento/esito?stato=errore&id={pid}"
    assert _payment(owner_db, pid).status == "in_attesa"


def test_acquisto_paypal_senza_return_url_usa_l_app(client, gw, pdfs):
    pid = client.post("/api/public/acquisto", json=_buy(method="paypal", return_url="https://altro.example/esito")).json()["pagamento"]
    ctx = gw.paypal_orders[0]["body"]["payment_source"]["paypal"]["experience_context"]
    assert ctx["return_url"] == f"https://blubeauty.test/api/pagamenti/paypal/ritorno?id={pid}"
    assert ctx["cancel_url"] == f"https://blubeauty.test/pagamento/esito?stato=annullato&id={pid}"


def test_acquisto_paypal_senza_chiavi(client, gw, pdfs, monkeypatch):
    monkeypatch.setattr(get_settings(), "paypal_secret", "")
    assert client.get("/api/public/acquisto").json()["metodi"] == ["carta", "bonifico"]
    assert client.post("/api/public/acquisto", json=_buy(method="paypal")).status_code == 404
