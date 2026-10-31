"""Prove dell'agent senza hardware: protocolli Epson e Custom, ESC/POS, bilancia, simulatore, servizio locale.

    python -m pytest agent -q
"""

import json
import re
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer

import pytest

import blubeauty_agent as A

SALE = {
    "lines": [
        {"description": "Acqua naturale 1,5 l", "quantity": "6", "unit_price": "0.40", "full_amount": "2.40", "amount": "2.16", "vat_rate": "22.00", "department": None},
        {"description": "Pane casereccio", "quantity": "1.25", "unit_price": "3.50", "full_amount": "4.38", "amount": "4.38", "vat_rate": "4.00", "department": None},
        {"description": "Frutta", "quantity": "1", "unit_price": "2.15", "full_amount": "2.15", "amount": "2.15", "vat_rate": "4.00", "department": 7},
    ],
    "adjustments": [{"description": "Promo 3x2 · Acqua", "amount": "0.80", "vat_rate": "22.00", "department": None}],
    "payments": [{"method": "contanti", "amount": "10.00"}, {"method": "carta", "amount": "1.00"}],
    "lottery": "ABCD1234",
}


def body_of(xml: str) -> list[ET.Element]:
    root = ET.fromstring(xml)
    receipt = A.find(root, "printerFiscalReceipt")
    return list(receipt)


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setenv("BLUBEAUTY_AGENT_CONFIG", str(tmp_path / "config.json"))


def test_epson_scontrino():
    rt = A.EpsonRT("192.168.1.50", {"departments": {"22": 1, "4": 3}})
    els = body_of(rt.receipt_xml(SALE))
    tags = [A.child_tag(e) for e in els]
    assert tags == ["beginFiscalReceipt", "printRecItem", "printRecItemAdjustment", "printRecItem", "printRecItem", "printRecItemAdjustment",
                    "printRecLotteryID", "printRecTotal", "printRecTotal", "endFiscalReceipt"]
    acqua, sconto, pane, frutta, promo = els[1], els[2], els[3], els[4], els[5]
    assert (acqua.get("quantity"), acqua.get("unitPrice"), acqua.get("department")) == ("6", "0,40", "1")
    assert (sconto.get("adjustmentType"), sconto.get("amount"), sconto.get("department")) == ("3", "0,24", "1")
    assert (pane.get("quantity"), pane.get("unitPrice"), pane.get("department")) == ("1,25", "3,50", "3")
    assert (frutta.get("quantity"), frutta.get("unitPrice"), frutta.get("department")) == ("1", "2,15", "7")  # reparto della cassa
    assert promo.get("description").startswith("Promo 3x2") and promo.get("amount") == "0,80"
    assert els[6].get("code") == "ABCD1234"
    assert [(t.get("paymentType"), t.get("index"), t.get("payment")) for t in els[7:9]] == [("0", "0", "10,00"), ("2", "1", "1,00")]


def test_epson_reso_annullo_ed_esito():
    rt = A.EpsonRT("192.168.1.50", {"serial": "99MEY012345"})
    ref = {"z": "0012", "number": "0007", "date": "2026-10-28", "serial": "99MEY012345"}
    els = body_of(rt.refund_xml({"lines": SALE["lines"][:1], "payments": [{"method": "contanti", "amount": "2.16"}], "reference": ref}))
    assert els[0].get("message") == "REFUND 0012 0007 28102026 99MEY012345" and els[0].get("messageType") == "4"
    assert A.child_tag(els[2]) == "printRecRefund" and els[2].get("amount") == "2,16" and els[2].get("unitPrice") == "0,36"
    void = body_of(rt.refund_xml({"lines": SALE["lines"][:1], "payments": [], "reference": ref, "void": True}))
    assert void[0].get("message").startswith("VOID 0012 0007") and A.child_tag(void[2]) == "printRecVoid"
    nd = body_of(rt.refund_xml({"lines": SALE["lines"][:1], "payments": [], "reference": None}))
    assert nd[0].get("message").startswith("REFUND 0000 0000 ") and nd[0].get("message").endswith(" ND")

    sent = {}

    def fake_http(url, data, headers, timeout):
        sent.update(url=url, data=data.decode())
        return (b'<?xml version="1.0" encoding="utf-8"?><soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"><soapenv:Body>'
                b'<response success="true" code="" status="2"><addInfo><elementList>lastCommand,printerStatus,fiscalReceiptNumber</elementList>'
                b'<lastCommand>74</lastCommand><printerStatus>20110</printerStatus><fiscalReceiptNumber>7</fiscalReceiptNumber>'
                b'<fiscalReceiptAmount>8,73</fiscalReceiptAmount><fiscalReceiptDate>28/10/2026</fiscalReceiptDate><fiscalReceiptTime>18:40</fiscalReceiptTime>'
                b'<zRepNumber>12</zRepNumber></addInfo></response></soapenv:Body></soapenv:Envelope>')

    rt = A.EpsonRT("192.168.1.50", {"serial": "99MEY012345"}, http=fake_http)
    res = rt.run("rt.receipt", SALE)
    assert sent["url"].startswith("http://192.168.1.50/cgi-bin/fpmate.cgi?devid=local_printer") and "<s:Envelope" in sent["data"]
    assert res == {"number": "0007", "z": "0012", "date": "2026-10-28", "time": "18:40", "serial": "99MEY012345", "amount": "8,73"}

    def refused(url, data, headers, timeout):
        return b'<response success="false" code="EPTR_REC_EMPTY" status="2"></response>'

    with pytest.raises(A.DeviceError, match="carta finita"):
        A.EpsonRT("192.168.1.50", {}, http=refused).run("rt.receipt", SALE)


def test_custom():
    rt = A.CustomRT("192.168.1.51", {"serial": "STMTE500271"})
    x = rt.receipt_xml(SALE)
    root = ET.fromstring(x.split("?>", 1)[1])
    items = root.findall("printRecItem")
    assert [(i.get("unitPrice"), i.get("quantity"), i.get("idVat")) for i in items] == [("40", "6000", "1"), ("350", "1250", "3"), ("215", "1000", "3")]
    assert [a.get("amount") for a in root.findall("printRecItemAdjustment")] == ["24", "80"]
    assert root.find("setLotteryCode").get("code") == "ABCD1234"
    assert [(t.get("payment"), t.get("paymentType")) for t in root.findall("printRecTotal")] == [("1000", "1"), ("100", "2")]
    ref = {"z": "12", "number": "7", "date": "2026-10-28", "serial": "STMTE500271"}
    r = ET.fromstring(rt.refund_xml({"lines": SALE["lines"][:1], "payments": [], "reference": ref}).split("?>", 1)[1])
    b = r.find("beginRtDocRefund")
    assert (b.get("docRefZ"), b.get("docRefNumber"), b.get("docDate"), b.get("fiscalSerial")) == ("0012", "0007", "281026", "STMTE500271")
    assert r.find("beginRtDocRefundSpecial") is None
    assert ET.fromstring(rt.refund_xml({"lines": [], "payments": [], "reference": None, "void": True}).split("?>", 1)[1]).find("beginRtDocAnnulmentSpecial") is not None


def test_escpos_e_bilancia():
    data = A.escpos({"lines": [{"text": "Totale", "right": "12,50 €", "bold": True}, {"type": "barcode", "data": "S260000012"}], "open_drawer": True})
    assert data.startswith(b"\x1b@") and b"\x1dV\x42\x00" in data and b"\x1bp\x00" in data
    assert "€".encode("cp858") in data and b"{BS260000012" in data
    assert A.parse_weight("ST,GS,+  0.350kg\r\n") == {"weight": "0.350", "unit": "kg", "stable": True}
    assert A.parse_weight("US,GS,+  1,205kg")["stable"] is False
    assert A.parse_weight("  1250 g", {"regex": r"(\d+)", "grams": True})["weight"] == "1.250"
    with pytest.raises(A.DeviceError):
        A.parse_weight("ERR")


def test_simulatore(tmp_path):
    rt = A.SimulatedRT("", {}, state_file=tmp_path / "rt.json")
    a = rt.run("rt.receipt", SALE)
    b = rt.run("rt.receipt", SALE)
    assert (a["number"], b["number"], a["z"]) == ("0001", "0002", "0001") and a["amount"] == "7.89"
    assert rt.run("rt.z", {})["z"] == "0001"
    assert rt.run("rt.receipt", SALE)["number"] == "0001" and rt.run("rt.receipt", SALE)["z"] == "0002"
    with pytest.raises(A.DeviceError, match="Carta finita"):
        A.SimulatedRT("", {"fail": "Carta finita"}).run("rt.receipt", SALE)


def test_servizio_locale(tmp_path):
    cfg = {"server": "http://127.0.0.1:9", "token": "x", "local_key": "chiave-locale", "allowed_origins": ["https://gestionale.test"],
           "devices": [{"id": "d1", "name": "Simulatore", "kind": "rt", "driver": "simulatore_rt", "options": {}}]}
    agent = A.Agent(cfg)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), A.make_local_handler(agent))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(path, body=None, headers=None, method=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, dict(r.headers), json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), json.loads(e.read() or b"{}")

    ok = {"Origin": "https://gestionale.test", "X-Agent-Key": "chiave-locale"}
    job = {"device_id": "d1", "kind": "rt.receipt", "payload": SALE}
    assert call("/lavoro", job)[0] == 403  # senza chiave
    assert call("/lavoro", job, {"Origin": "https://sito-qualsiasi.test", "X-Agent-Key": "chiave-locale"})[0] == 403
    code, hdr, res = call("/lavoro", job, ok)
    assert code == 200 and res["ok"] and res["result"]["number"] == "0001"
    assert hdr["Access-Control-Allow-Origin"] == "https://gestionale.test"
    code, hdr, _ = call("/lavoro", None, {"Origin": "https://gestionale.test"}, method="OPTIONS")
    assert code == 204 and hdr["Access-Control-Allow-Private-Network"] == "true"
    assert call("/stato", None, ok)[2]["devices"][0]["name"] == "Simulatore"
    assert call("/lavoro", {**job, "device_id": "zz"}, ok)[0] == 404
    httpd.shutdown()


def test_esito_al_server(monkeypatch):
    cfg = {"server": "http://gestionale.test", "token": "t", "devices": []}
    agent = A.Agent(cfg)
    posted = []
    monkeypatch.setattr(agent.server, "call", lambda method, path, body=None, timeout=30: posted.append((method, path, body)))
    agent.handle({"id": "j1", "kind": "rt.receipt", "payload": SALE, "device": {"id": "d", "name": "Sim", "driver": "simulatore_rt", "options": {}}})
    agent.handle({"id": "j2", "kind": "rt.receipt", "payload": SALE, "device": {"id": "e", "name": "Rotta", "driver": "epson_rt",
                                                                               "address": "127.0.0.1:1", "options": {}}})
    assert posted[0][1] == "/api/agent/lavori/j1/esito" and posted[0][2]["ok"] and posted[0][2]["result"]["number"]
    assert posted[1][2]["ok"] is False and "non raggiungibile" in posted[1][2]["error"]


def test_documento_non_fiscale_su_registratore(tmp_path):
    """Ricevuta NON fiscale sul registratore, come BluOrderScan e il gestionale macellerie (Custom 4001/4003/4004)."""
    ricevuta = {"lines": [{"text": "Salone Aurora", "align": "center", "bold": True, "rt_skip": True},
                          {"type": "line", "rt_skip": True}, {"text": "RICEVUTA NON FISCALE", "align": "center"},
                          {"text": "Colore + piega (Giulia)", "right": "65,00"}, {"type": "feed"},
                          {"text": "Già pagato con carta: 65,00 €"},
                          {"type": "barcode", "data": "BB000123", "label": "Tessera BB000123"},
                          {"type": "qr", "data": "https://x.it/prenota/aurora"},
                          {"text": "DOCUMENTO NON FISCALE", "rt_text": "NON VALIDO COME DOC. COMMERCIALE", "align": "center"},
                          {"type": "cut"}]}
    sent = []

    def ok(url, data, headers, timeout):
        sent.append(data.decode())
        return b'<response success="true" status="0"></response>'

    res = A.CustomRT("192.168.1.51", {}, http=ok).run("rt.nonfiscal", ricevuta)
    assert 'command="4001" data="10"' in sent[0] and 'command="4004" data=""' in sent[-1]
    rows = [re.search(r'data="1(\d\d)(.*)"', x).groups() for x in sent[1:-1]]
    assert all(int(n) == len(t) and len(t) <= 32 for n, t in rows)  # «1» + lunghezza + testo, 32 caratteri
    texts = [t for _, t in rows]
    assert "Salone Aurora" not in " ".join(texts)  # l'intestazione la stampa il registratore
    assert texts[-1].strip() == "NON VALIDO COME DOC. COMMERCIALE" and "Gia pagato con carta: 65,00 EUR" in texts
    assert any(t.startswith("Colore + piega (Giulia)") and t.endswith("65,00") for t in texts)
    assert "Tessera BB000123" in texts and not any("https" in t for t in texts) and res["rows"] == len(texts)
    # comando rifiutato: si annulla il documento aperto e si segnala l'errore
    calls = []

    def ko(url, data, headers, timeout):
        calls.append(data.decode())
        if "4003" in calls[-1]:
            return b'<response success="false" status="18"></response>'
        return b'<response success="true" status="0"></response>'

    with pytest.raises(A.DeviceError, match="Stampa non fiscale rifiutata"):
        A.CustomRT("192.168.1.51", {}, http=ko).run("rt.nonfiscal", ricevuta)
    assert "resetPrinter" in calls[-1]
    # Epson e simulatore usano le stesse righe
    res = A.EpsonRT("192.168.1.50", {}, http=ok).run("rt.nonfiscal", ricevuta)
    assert "<beginNonFiscal" in sent[-1] and "65,00" in sent[-1]
    sim = A.SimulatedRT("", {}, state_file=tmp_path / "rt.json").run("rt.nonfiscal", ricevuta)
    assert sim["simulated"] and sim["rows"] == len(texts)
