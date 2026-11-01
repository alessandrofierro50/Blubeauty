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


class FakeCustom:
    """Registratore Custom finto: risponde come il KUBE II-F (risposte XML di /xml/printer.htm)."""

    def __init__(self, vat=((1, 2200), (2, 1000), (3, 400), (4, 500)), refuse=None, lose=False, last_idcmd=None, fp_status="000"):
        self.sent, self.vat, self.refuse, self.lose = [], dict(vat), refuse, lose
        self.last_idcmd, self.fp_status = last_idcmd, fp_status

    def __call__(self, url, data, headers, timeout):
        x = data.decode()
        self.sent.append(x)
        assert url.endswith("/xml/printer.htm") and headers["Content-Type"].startswith("text/plain")
        m = re.search(r'getVatRate numVat="(\d+)"', x)
        if m:
            n = int(m.group(1))
            buf = f"{n:02d}{self.vat[n]:04d}  IVA {self.vat[n] / 100:g}%" if n in self.vat else f"{n:02d}0000"
            return f'<response success="true" status="0"><addInfo><responseBuf>{buf}</responseBuf></addInfo></response>'.encode()
        if "queryPrinterStatus" in x:
            return (f'<response success="true" status="0"><addInfo><lastIdCmd IdCmd="{self.last_idcmd or ""}"></lastIdCmd>'
                    f'<fpStatus>{self.fp_status}</fpStatus><printerStatus>00000</printerStatus><cpuRel>KUBE II-F</cpuRel></addInfo></response>').encode()
        if self.refuse and self.refuse in x:
            return b'<response success="false" status="28"></response>'
        if self.lose and "printerFiscalReceipt" in x:
            raise A.RtNoAnswer("Risposta non ricevuta (timeout)")
        return b'<response success="true" status="0"><addInfo><fiscalDoc>57</fiscalDoc><nClose>12</nClose></addInfo></response>'


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(A.CustomRT, "VERIFY_WAITS", (0, 0, 0))
    A.CustomRT._vat_cache.clear()


def test_custom_scontrino_come_bluorderscan():
    """Formato collaudato sul KUBE II-F reale in BluOrderScan: un solo XML, importo della riga, IdVat, messaggio quantità,
    subtotale, contante ricevuto per ultimo, IdCmd sull'ultimo nodo; aliquote lette dal registratore."""
    fake = FakeCustom()
    rt = A.CustomRT("192.168.1.51", {"serial": "STMTE500271"}, http=fake)
    res = rt.run("rt.receipt", {**SALE, "document": "SCO 12/2026"})
    assert (res["number"], res["z"]) == ("0057", "0012")
    x = fake.sent[-1]
    root = ET.fromstring(x.split("?>", 1)[1])
    assert [c.tag for c in root][0] == "beginFiscalReceipt" and [c.tag for c in root][-1] == "endFiscalReceiptCut"
    items = root.findall("printRecItem")
    # acqua 6 × 0,40 scontata a 2,16 e promo 0,80 sull'IVA 22% → 1,36; pane 4,38; frutta 2,15 (reparto della cassa 7)
    assert [(i.get("description"), i.get("unitPrice"), i.get("IdVat"), i.get("department")) for i in items] == [
        ("Acqua naturale 1,5 l", "136", "1", "1"), ("Pane casereccio", "438", "3", "1"), ("Frutta", "215", "3", "7")]
    msgs = [m.get("message") for m in root.findall("printRecMessage")]
    assert "6 x 0,40 EUR" in msgs and "1,25 x 3,50 EUR" in msgs and "Sconto 1,04 EUR" in msgs and msgs[-1] == "Rif. SCO 12/2026"
    assert root.find("printRecItemAdjustment") is None and root.find("printRecSubtotal") is not None
    assert [(t.get("description"), t.get("payment"), t.get("paymentType")) for t in root.findall("printRecTotal")] == [
        ("CARTA", "100", "2"), ("CONTANTI", "1000", "1")]
    assert root.find("setLotteryCode").get("code") == "ABCD1234"
    assert root.find("endFiscalReceiptCut").get("IdCmd") == "SCO122026E"
    # descrizioni senza accenti e al massimo 22 caratteri
    x = rt.receipt_xml({**SALE, "lines": [{**SALE["lines"][2], "description": "Piega più trattamento cheratina €"}], "adjustments": []})
    assert 'description="Piega piu trattamento "' in x or 'description="Piega piu trattamento"' in x
    # aliquota non programmata: nulla parte
    with pytest.raises(A.RtNotSent, match="non programmata"):
        A.CustomRT("192.168.1.52", {}, http=FakeCustom(vat=((1, 2200),))).run("rt.receipt", SALE)
    # indice IVA scritto a mano: non serve leggerlo
    fake2 = FakeCustom(vat=())
    A.CustomRT("192.168.1.51", {"vat_ids": {"22": 5, "4": 6}}, http=fake2).run("rt.receipt", SALE)
    assert 'IdVat="5"' in fake2.sent[-1] and not any("getVatRate" in s for s in fake2.sent)


def test_custom_rifiuto_risposta_persa_e_chiusura(monkeypatch):
    # rifiutato: resetPrinter e «non emesso» (si può riprovare)
    fake = FakeCustom(refuse="beginFiscalReceipt")
    with pytest.raises(A.RtNotSent, match="IVA NON PROGRAMMATA.*non emesso"):
        A.CustomRT("192.168.1.51", {}, http=fake).run("rt.receipt", SALE)
    assert "resetPrinter" in fake.sent[-1]
    # risposta persa ma il registratore l'ha emesso (lastIdCmd uguale): esito registrato, nessuna ristampa
    fake = FakeCustom(lose=True, last_idcmd="SCO132026E", fp_status="000")
    res = A.CustomRT("192.168.1.51", {}, http=fake).run("rt.receipt", {**SALE, "document": "SCO 13/2026"})
    assert res["verified"] and sum("beginFiscalReceipt" in s for s in fake.sent) == 1
    # risposta persa e documento non emesso: si può riprovare
    with pytest.raises(A.RtNotSent, match="NON emesso"):
        A.CustomRT("192.168.1.51", {}, http=FakeCustom(lose=True, last_idcmd="ALTRO", fp_status="000")).run("rt.receipt", SALE)
    # stato incerto (documento ancora aperto): chiede di controllare, non ristampa
    with pytest.raises(A.RtNoAnswer, match="Controlla sul registratore"):
        A.CustomRT("192.168.1.51", {}, http=FakeCustom(lose=True, last_idcmd="ALTRO", fp_status="010")).run("rt.receipt", SALE)
    # chiusura Z come il manuale (senza IdCmd), poi pausa e resetPrinter per la «VISITA TECNICA»
    pauses = []
    monkeypatch.setattr(A.time, "sleep", lambda s: pauses.append(s))
    fake = FakeCustom()
    z = A.CustomRT("192.168.1.51", {}, http=fake).run("rt.z", {})
    assert z["z"] == "12" and '<printZReport description=""></printZReport>' in fake.sent[0] and "IdCmd" not in fake.sent[0]
    assert pauses == [20] and "resetPrinter" in fake.sent[-1]
    # annullo nel formato di BluOrderScan
    fake = FakeCustom()
    ref = {"z": "12", "number": "7", "date": "2026-10-28", "serial": "STMTE500271"}
    A.CustomRT("192.168.1.51", {}, http=fake).run("rt.refund", {"lines": SALE["lines"][2:], "payments": [], "reference": ref,
                                                                 "void": True, "document": "RSO 3/2026"})
    r = ET.fromstring(fake.sent[-1].split("?>", 1)[1])
    b = r.find("beginRtDocAnnulment")
    assert (b.get("docRefZ"), b.get("docRefNumber"), b.get("docDate")) == ("12", "7", "281026")
    assert r.find("printRecTotal").get("description") == "ANNULLO" and r.find("printRecTotal").get("payment") == "215"
    assert r.find("endFiscalReceiptCut").get("IdCmd") == "RSO32026R"
    # reso (da collaudare) e annullo senza documento d'origine
    rt = A.CustomRT("192.168.1.51", {"serial": "STMTE500271"}, http=FakeCustom())
    r = ET.fromstring(rt.refund_xml({"lines": SALE["lines"][:1], "payments": [], "reference": ref}).split("?>", 1)[1])
    assert r.find("beginRtDocRefund").get("fiscalSerial") == "STMTE500271" and r.find("printRecRefund").get("unitPrice") == "216"
    assert ET.fromstring(rt.refund_xml({"lines": SALE["lines"][2:], "payments": [], "reference": None, "void": True})
                         .split("?>", 1)[1]).find("beginRtDocAnnulmentSpecial") is not None
    # prova del dispositivo: modello, problemi e aliquote lette
    st = A.CustomRT("192.168.1.51", {}, http=FakeCustom()).run("status", {})
    assert st["model"] == "KUBE II-F" and [v["rate"] for v in st["vat_table"]] == ["22", "10", "4", "5"]


def test_custom_digest_su_http_vero():
    """Trasporto reale (http.client) con autenticazione Digest, come il ponte di BluOrderScan."""
    import hashlib
    from http.server import BaseHTTPRequestHandler
    seen = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"])).decode()
            auth = self.headers.get("Authorization") or ""
            if not auth.startswith("Digest"):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Digest realm="KUBE", nonce="abc", qop="auth"')
                self.end_headers()
                return
            f = dict(re.findall(r'(\w+)="?([^",]*)"?', auth))
            md5 = lambda s: hashlib.md5(s.encode()).hexdigest()  # noqa: E731
            ok = f["response"] == md5(f"{md5('admin:KUBE:segreta')}:abc:{f['nc']}:{f['cnonce']}:auth:{md5('POST:/xml/printer.htm')}")
            seen.append((self.headers["Content-Type"], ok, body))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'<response success="true" status="0"></response>')

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        rt = A.CustomRT(f"127.0.0.1:{srv.server_port}", {"username": "admin", "password": "segreta"})
        rt.send(rt.command("queryPrinterStatus"))
        assert seen and seen[0][0].startswith("text/plain") and seen[0][1]
    finally:
        srv.shutdown()


def test_escpos_tabelle_caratteri():
    """Accenti sulla termica da 80 mm (esperienza di BluOrderScan): PC858 con €, PC850/PC437 per le compatibili che al
    numero 19 hanno un'altra tabella (es. greca, «più» → «piΩ»), ASCII con l'apostrofo."""
    riga = {"lines": [{"text": "Piega più colore – €"}]}
    d = A.escpos(riga, 48, "pc858")
    assert d.startswith(b"\x1b@\x1bt\x13") and "Piega più colore - €".encode("cp858") in d
    d = A.escpos(riga, 48, "pc850")
    assert d.startswith(b"\x1b@\x1bt\x02") and "Piega più colore - EUR".encode("cp850") in d
    d = A.escpos(riga, 48, "pc437")
    assert d.startswith(b"\x1b@\x1bt\x00") and "più".encode("cp437") in d and b"EUR" in d
    d = A.escpos(riga, 48, "ascii")
    assert b"Piega piu' colore - EUR" in d and all(b < 128 for b in d.split(b"Piega")[1].split(b"\n")[0])
    # colonne allineate anche con € → EUR (la lunghezza si conta sul testo già convertito)
    d = A.escpos({"lines": [{"text": "Totale", "right": "12,50 €"}]}, 32, "pc850")
    assert b"Totale" + b" " * (32 - 6 - 9) + b"12,50 EUR\n" in d
    # tabella sconosciuta → PC858; la stampante usa l'opzione «charset»
    assert A.escpos(riga, 48, "boh").startswith(b"\x1b@\x1bt\x13")


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


def test_logo_sulla_termica_e_non_sul_registratore():
    import base64
    raster = base64.b64encode(bytes([0xFF, 0x00] * 3)).decode()  # 16 punti × 3 righe
    p = {"lines": [{"type": "image", "raster": raster, "width_bytes": 2, "height": 3, "align": "center", "rt_skip": True},
                   {"text": "Salone Aurora", "align": "center", "rt_skip": True}, {"text": "RICEVUTA NON FISCALE", "align": "center"},
                   {"text": "Piega", "right": " 22%      22,00"}, {"type": "cut"}]}
    data = A.escpos(p, 48)
    assert b"\x1dv0\x00\x02\x00\x03\x00" + bytes([0xFF, 0x00] * 3) in data
    rows = A.text_rows(p, 32, rt=True)
    assert rows[0].strip() == "RICEVUTA NON FISCALE" and len(rows) == 2 and rows[1].endswith("22,00")


def test_descrizioni_lunghe_sul_registratore_da_57mm():
    p = {"lines": [{"text": "Trattamento ristrutturante alla cheratina", "right": " 22%      45,00"}]}
    rows = A.text_rows(p, 32, rt=True)
    assert all(len(r) <= 32 for r in rows) and rows[-1].endswith("45,00")
    assert "Trattamento ristrutturante alla cheratina" == " ".join(r.replace("22%", "").replace("45,00", "").strip() for r in rows).strip()
