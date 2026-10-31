from datetime import date
"""Fatturazione elettronica con un Aruba simulato (httpx.MockTransport): niente chiamate esterne."""

import base64
import json
import re
from urllib.parse import parse_qs

import httpx
import pytest
from lxml import etree

from app.fatturapa import aruba, service as sdi
from app.fatturapa import xml_builder as xb
from tests.conftest import activate_and_login, make_tenant

V = "/api/vendite"
F = "/api/fatturapa"
COMPANY_VAT = "02345670984"

RECEIVED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica versione="FPR12" xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
 <FatturaElettronicaHeader>
  <CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>01114601006</IdCodice></IdFiscaleIVA>
   <Anagrafica><Denominazione>Fornitore SDI Srl</Denominazione></Anagrafica><RegimeFiscale>RF01</RegimeFiscale></DatiAnagrafici>
   <Sede><Indirizzo>Via Dante 1</Indirizzo><CAP>00100</CAP><Comune>Roma</Comune><Nazione>IT</Nazione></Sede></CedentePrestatore>
  <CessionarioCommittente><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>02345670984</IdCodice></IdFiscaleIVA>
   <Anagrafica><Denominazione>Noi</Denominazione></Anagrafica></DatiAnagrafici>
   <Sede><Indirizzo>Via X</Indirizzo><CAP>73100</CAP><Comune>Lecce</Comune><Nazione>IT</Nazione></Sede></CessionarioCommittente>
 </FatturaElettronicaHeader>
 <FatturaElettronicaBody>
  <DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa><Data>2026-10-20</Data>
   <Numero>A-55</Numero><ImportoTotaleDocumento>122.00</ImportoTotaleDocumento></DatiGeneraliDocumento></DatiGenerali>
  <DatiBeniServizi><DettaglioLinee><NumeroLinea>1</NumeroLinea><Descrizione>Consulenza</Descrizione><Quantita>1.00</Quantita>
   <PrezzoUnitario>100.00</PrezzoUnitario><PrezzoTotale>100.00</PrezzoTotale><AliquotaIVA>22.00</AliquotaIVA></DettaglioLinee>
   <DatiRiepilogo><AliquotaIVA>22.00</AliquotaIVA><ImponibileImporto>100.00</ImponibileImporto><Imposta>22.00</Imposta></DatiRiepilogo>
  </DatiBeniServizi>
 </FatturaElettronicaBody>
</p:FatturaElettronica>"""


class FakeAruba:
    def __init__(self):
        self.signins = 0
        self.uploads: list[dict] = []
        self.status: dict[str, str] = {}
        self.notifications: dict[str, list] = {}
        self.received = [{"filename": "IT01114601006_aaaaa.xml", "id": "77", "idSdi": "990"}]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/auth/signin":
            form = parse_qs(request.content.decode())
            if form.get("password", [""])[0] == "sbagliata":
                return httpx.Response(400, json={"error": "invalid_grant", "error_description": "The user name or password is incorrect."})
            self.signins += 1
            return httpx.Response(200, json={"access_token": f"tok{self.signins}", "refresh_token": "r", "expires_in": 1800})
        if not request.headers.get("Authorization", "").startswith("Bearer tok"):
            return httpx.Response(401)
        if path == "/auth/userInfo":
            return httpx.Response(200, json={"username": "PREMIUM", "userDescription": "BluCode", "vatCode": "01879020517",
                                             "accountStatus": {"expired": False, "expirationDate": "2027-12-31"}})
        if path == "/services/invoice/upload":
            body = json.loads(request.content)
            xml = base64.b64decode(body["dataFile"])
            assert not xb.validate(xml), xb.validate(xml)
            if body.get("dryRun"):
                return httpx.Response(200, json={"errorCode": "0000", "errorDescription": "Operazione effettuata"})
            name = f"IT01879020517_{len(self.uploads) + 1:05d}.xml.p7m"
            self.uploads.append({"filename": name, "xml": xml})
            self.status[name] = "Presa in carico"
            return httpx.Response(200, json={"errorCode": "0000", "errorDescription": "Operazione effettuata - abc", "uploadFileName": name})
        if path == "/api/v2/invoices-out/detail":
            fn = request.url.params["filename"]
            return httpx.Response(200, json={"id": "1", "idSdi": "123456", "filename": fn, "sdiErrors": [],
                                             "invoices": [{"status": self.status.get(fn, "Inviata"), "statusDescription": ""}]})
        if path == "/api/v2/invoices-out/notifications":
            return httpx.Response(200, json={"count": 0, "notifications": self.notifications.get(request.url.params["filename"], [])})
        if path == "/api/v2/invoices-in":
            return httpx.Response(200, json={"content": [{"filename": r["filename"]} for r in self.received], "last": True, "totalPages": 1})
        if path == "/api/v2/invoices-in/detail":
            r = next(x for x in self.received if x["filename"] == request.url.params["filename"])
            return httpx.Response(200, json={**r, "file": base64.b64encode(RECEIVED_XML.encode()).decode()})
        return httpx.Response(404)


@pytest.fixture
def fake(monkeypatch):
    f = FakeAruba()
    monkeypatch.setattr(sdi, "_transport", httpx.MockTransport(f))
    monkeypatch.setattr(aruba, "_store", aruba._MemoryStore())
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "aruba_username", "PREMIUM")
    monkeypatch.setattr(s, "aruba_password", "segreta")
    monkeypatch.setattr(s, "aruba_callback_key", "chiave-callback")
    return f


def setup(client, admin_headers, name="Fattura Elettronica Srl"):
    t = make_tenant(client, admin_headers, name, plan="BASE", sector="Ferramenta", vat_number=COMPANY_VAT)
    client.patch(f"/api/admin/tenants/{t['id']}", headers=admin_headers, json={"extra_modules": ["fatturapa"]})
    h = activate_and_login(client, t)
    c = client.get("/api/app/intestazione", headers=h).json()
    c.update({"address": "Viale Leopardi 88", "zip_code": "73100", "city": "Lecce", "province": "LE", "iban": "IT60X0542811101000000123456",
              "rea_office": "LE", "rea_number": "123456", "sole_shareholder": "SU", "share_capital": "10000"})
    assert client.put(f"/api/app/azienda/{c['id']}", headers=h, json=c).status_code == 200
    cust = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Cliente – Società “Uno” Srl", "is_customer": True, "vat_number": "07123450012", "sdi_code": "M5UXCR1",
        "address": "Via Roma", "street_number": "1", "zip_code": "73024", "city": "Maglie", "province": "LE"}).json()
    return t, h, cust


def invoice(client, h, cust, **extra):
    d = client.post(f"{V}/documenti", headers=h, json={"doc_type": "FTI", "party_id": cust["id"], "lines": [
        {"description": "Consulenza € ottobre", "quantity": "2", "unit_price": "50", "discount1": "10"},
        {"description": "Nota: riga di testo", "quantity": "0", "unit_price": "0"}], **extra}).json()
    r = client.post(f"{V}/documenti/{d['id']}/conferma", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def test_xml_valido_e_invio(client, admin_headers, fake):
    _, h, cust = setup(client, admin_headers)
    f = invoice(client, h, cust)
    st = client.get(f"{F}/documenti/{f['id']}", headers=h).json()
    assert st["check"]["errors"] == [] and st["can_send"] is True
    x = client.get(f"{F}/documenti/{f['id']}/xml", headers=h)
    assert x.status_code == 200 and not xb.validate(x.content)
    root = etree.fromstring(x.content)
    t = lambda p: root.findtext(p)  # noqa: E731
    assert t(".//DatiTrasmissione/IdTrasmittente/IdCodice") == "01879020517"
    assert t(".//DatiTrasmissione/CodiceDestinatario") == "M5UXCR1"
    assert t(".//CessionarioCommittente//Denominazione") == 'Cliente - Società "Uno" Srl'  # caratteri ammessi da SDI
    assert t(".//IscrizioneREA/NumeroREA") == "123456" and t(".//IscrizioneREA/StatoLiquidazione") == "LN"
    assert t(".//DettaglioLinee/PrezzoTotale") == "90.00" and t(".//ScontoMaggiorazione/Percentuale") == "10.00"
    assert t(".//DatiRiepilogo/Imposta") == "19.80" and t(".//ImportoTotaleDocumento") == "109.80"
    assert t(".//DettaglioPagamento/IBAN") == "IT60X0542811101000000123456"
    # verifica con Aruba senza invio, poi invio vero
    v = client.post(f"{F}/documenti/{f['id']}/verifica", headers=h).json()
    assert v["ok"] is True and v["aruba"] == "ok" and fake.uploads == []
    e = client.post(f"{F}/documenti/{f['id']}/invia", headers=h).json()
    assert e["status"] == "presa_in_carico" and e["filename"] == "IT01879020517_00001.xml.p7m"
    assert client.post(f"{F}/documenti/{f['id']}/invia", headers=h).status_code == 422  # niente doppio invio
    assert fake.signins == 1  # token riusato
    # stato aggiornato da Aruba: consegnata
    fake.status[e["filename"]] = "Consegnata"
    r = client.post(f"{F}/documenti/{f['id']}/aggiorna", headers=h).json()
    assert r["status"] == "consegnata" and r["sdi_id"] == "123456"
    lst = client.get(f"{V}/documenti?tipo=FTI", headers=h).json()["rows"]
    assert lst[0]["sdi_status"] == "consegnata"
    # esportazione: la fattura inviata esce col file trasmesso, una seconda non ancora inviata con quello generato ora
    g = invoice(client, h, cust)
    x = client.get(f"{F}/documenti/{f['id']}/xml", headers=h)
    assert 'filename="IT01879020517_00001.xml"' in x.headers["content-disposition"]
    import io
    import zipfile
    today = date.today().isoformat()
    z = client.get(f"{F}/esporta?dal={today}&al={today}", headers=h)
    assert z.status_code == 200 and z.headers["x-esportate"] == "2" and z.headers["x-errori"] == "0"
    names = sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist())
    assert names == ["FT-" + str(g["number"]) + "-" + str(g["year"]) + ".xml", "IT01879020517_00001.xml"]
    assert client.get(f"{F}/esporta?dal=2000-01-01&al=2000-01-31", headers=h).status_code == 404


def test_scarto_errori_e_reinvio(client, admin_headers, fake):
    _, h, cust = setup(client, admin_headers, "Scarti Srl")
    f = invoice(client, h, cust)
    e = client.post(f"{F}/documenti/{f['id']}/invia", headers=h).json()
    # callback di Aruba con notifica di scarto (NS) e lista errori
    ns = base64.b64encode(b"""<?xml version="1.0"?><ns:NotificaScarto xmlns:ns="http://www.fatturapa.gov.it/sdi/messaggi/v1.0">
      <IdentificativoSdI>123456</IdentificativoSdI><NomeFile>%s</NomeFile><ListaErrori><Errore><Codice>00305</Codice>
      <Descrizione>1.4.1.1.2 IdCodice non valido</Descrizione></Errore></ListaErrori></ns:NotificaScarto>""" % e["filename"].encode()).decode()
    payload = {"username": "PREMIUM", "countryCode": "IT", "vatCode": COMPANY_VAT, "fiscalCode": COMPANY_VAT, "inOut": "OUT",
               "notifyType": "NS", "sdiIdentification": "123456", "notifyFileName": "IT01879020517_00001_NS_001.xml",
               "notifyXmlBase64": ns, "notificationDate": "2026-10-28T10:00:00+01:00"}
    assert client.post(f"{F}/callback/createNotification", json=payload).status_code == 401
    r = client.post(f"{F}/callback/createNotification", json=payload, headers={"Authorization": "chiave-callback"})
    assert r.status_code == 200 and r.json()["result"] == "ok"
    st = client.get(f"{F}/documenti/{f['id']}", headers=h).json()["current"]
    assert st["status"] == "scartata" and st["errors"][0]["code"] == "00305" and st["can_resend"] is True
    # correzione dell'anagrafica e reinvio con lo stesso numero
    e2 = client.post(f"{F}/documenti/{f['id']}/invia", headers=h).json()
    assert e2["attempt"] == 2 and e2["status"] == "presa_in_carico"
    assert b"<Numero>1</Numero>" in fake.uploads[1]["xml"] and fake.uploads[1]["xml"].count(b"ProgressivoInvio") == 2


def test_controlli_preventivi_e_rifiuto_sincrono(client, admin_headers, fake):
    _, h, cust = setup(client, admin_headers, "Controlli Srl")
    p = client.get(f"/api/anagrafiche/soggetti/{cust['id']}", headers=h).json()
    p.update({"zip_code": "", "sdi_code": None})
    client.put(f"/api/anagrafiche/soggetti/{cust['id']}", headers=h, json=p)
    f = invoice(client, h, cust)
    st = client.get(f"{F}/documenti/{f['id']}", headers=h).json()
    assert any("CAP" in x for x in st["check"]["errors"]) and any("cassetto fiscale" in x for x in st["check"]["warnings"])
    r = client.post(f"{F}/documenti/{f['id']}/invia", headers=h)
    assert r.status_code == 422 and "CAP" in r.json()["detail"]


def test_ricevute_callback_sincronizzazione_e_registrazione(client, admin_headers, fake):
    _, h, _ = setup(client, admin_headers, "Ricevute Srl")
    client.put(f"{F}/impostazioni", headers=h, json={"mode": "piattaforma", "auto_send": False})  # registra l'instradamento
    r = client.post(f"{F}/ricevute/sincronizza", headers=h).json()
    assert r["received"] == 1
    assert client.post(f"{F}/ricevute/sincronizza", headers=h).json()["received"] == 0  # niente doppioni
    inbox = client.get(f"{F}/ricevute", headers=h).json()["rows"]
    assert inbox[0]["supplier_name"] == "Fornitore SDI Srl" and inbox[0]["number"] == "A-55" and inbox[0]["total"] == "122.00"
    # stessa fattura arrivata anche via callback: ignorata
    cb = {"username": "PREMIUM", "countryCode": "IT", "vatCode": COMPANY_VAT, "fiscalCode": COMPANY_VAT, "sdiIdentification": "990",
          "sdiInvoiceFileName": "IT01114601006_aaaaa.xml", "invoiceXmlBase64": base64.b64encode(RECEIVED_XML.encode()).decode()}
    client.post(f"{F}/callback/createInvoice", json=cb, headers={"Authorization": "chiave-callback"})
    assert len(client.get(f"{F}/ricevute", headers=h).json()["rows"]) == 1
    # registrazione negli acquisti con il flusso dell'import XML
    pv = client.post("/api/acquisti/import-xml/anteprima-sdi", headers=h, json={"inbox_ids": [inbox[0]["id"]]}).json()
    inv = pv["invoices"][0]
    body = {"file_ref": inv["file_ref"], "index": 0, "supplier_id": None, "moves_stock": False,
            "lines": [{"number": 1, "action": "ignora"}]}
    d = client.post("/api/acquisti/import-xml/conferma", headers=h, json=body)
    assert d.status_code == 201, d.text
    reg = client.get(f"{F}/ricevute?stato=registrata", headers=h).json()["rows"]
    assert reg[0]["document_id"] == d.json()["id"]


def test_invio_automatico_e_credenziali(client, admin_headers, fake):
    _, h, cust = setup(client, admin_headers, "Automatico Srl")
    client.put(f"{F}/impostazioni", headers=h, json={"mode": "piattaforma", "auto_send": True})
    f = invoice(client, h, cust)
    assert client.get(f"{V}/documenti/{f['id']}", headers=h).json()["sdi_status"] == "presa_in_carico"
    # credenziali proprie: la password non torna mai indietro, ed è cifrata
    s = client.put(f"{F}/impostazioni", headers=h, json={"mode": "proprio", "username": "MIO", "password": "sbagliata", "auto_send": False}).json()
    assert s["has_password"] is True and "password" not in s
    r = client.post(f"{F}/impostazioni/prova", headers=h)
    assert r.status_code == 422 and "Accesso ad Aruba non riuscito" in r.json()["detail"]
    client.put(f"{F}/impostazioni", headers=h, json={"mode": "proprio", "username": "MIO", "password": "giusta"})
    assert client.post(f"{F}/impostazioni/prova", headers=h).json()["user"] == "BluCode"


def test_modulo_extra_bloccato_senza_attivazione(client, admin_headers):
    t = make_tenant(client, admin_headers, "Senza Fe Srl", plan="PRO")
    h = activate_and_login(client, t)
    r = client.get(f"{F}/impostazioni", headers=h)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "modulo_non_incluso"


def test_pulizia_testo_e_numeri():
    assert xb.clean("Viti 4×40 – “zincate” €", 80) == 'Viti 4x40 - "zincate" EUR'
    assert xb.clean("ŁÓDŹ", 80) == "LÓDZ"  # Ó è Latin-1 (ammessa), Ł e Ź no
    assert xb.decimal_text("2") == "2.00" and xb.decimal_text("1.23456789") == "1.23456789" and xb.decimal_text("4.5600") == "4.56"
    assert xb.progressive_code(1) == "00001" and xb.progressive_code(36) == "00010"
    assert re.fullmatch(r"[0-9A-Z]{5,10}", xb.progressive_code(10**9))


def test_bollo_virtuale_nell_xml(client, admin_headers, fake):
    _, h, cust = setup(client, admin_headers)
    vats = {v["code"]: v["id"] for v in client.get("/api/anagrafiche/tabelle/aliquote-iva", headers=h).json()}
    d = client.post(f"{V}/documenti", headers=h, json={"doc_type": "FTI", "party_id": cust["id"], "moves_stock": False, "lines": [
        {"description": "Software gestionale", "quantity": "1", "unit_price": "400", "vat_rate_id": vats["N2.2"]}]}).json()
    assert client.post(f"{V}/documenti/{d['id']}/conferma", headers=h, json={}).status_code == 200
    x = client.get(f"{F}/documenti/{d['id']}/xml", headers=h)
    assert x.status_code == 200 and not xb.validate(x.content)
    root = etree.fromstring(x.content)
    assert root.findtext(".//DatiBollo/BolloVirtuale") == "SI" and root.findtext(".//DatiBollo/ImportoBollo") == "2.00"
    assert root.findtext(".//ImportoTotaleDocumento") == "402.00"


def test_formato_numero_e_progressivo_dell_esportazione(client, admin_headers, fake):
    _, h, cust = setup(client, admin_headers)
    r = client.put(f"{V}/impostazioni", headers=h, json={"bollo_mode": "cliente", "series": {}, "formats": {"FT": {"": "FPR {n}/{aa}"}}})
    assert r.status_code == 200 and r.json()["formats"]["FT"] == {"": "FPR {n}/{aa}"}
    assert client.put(f"{V}/impostazioni", headers=h, json={"bollo_mode": "cliente", "formats": {"FT": {"": "FPR"}}}).status_code == 422
    f1, f2 = invoice(client, h, cust), invoice(client, h, cust)
    yy = f"{date.today().year % 100:02d}"
    assert f1["number_label"] == f"FPR 1/{yy}"
    progs = []
    for f in (f1, f2):
        root = etree.fromstring(client.get(f"{F}/documenti/{f['id']}/xml", headers=h).content)
        progs.append(root.findtext(".//DatiTrasmissione/ProgressivoInvio"))
        assert root.findtext(".//DatiGeneraliDocumento/Numero") == f"FPR {f['number']}/{yy}"
    assert progs == [f"E{yy}0001", f"E{yy}0002"]
