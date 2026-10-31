import base64
import io
import zipfile
from decimal import Decimal

from tests.conftest import activate_and_login, make_tenant
from tests.test_magazzino import stock

A = "/api/acquisti"

SUPPLIER_VAT = "01114601006"


def setup(client, admin_headers):
    t = make_tenant(client, admin_headers, "Acquisti Srl", plan="PRO", sector="Ferramenta", vat_number="02345670984")
    h = activate_and_login(client, t)
    sup = client.post("/api/anagrafiche/soggetti", headers=h, json={
        "name": "Grossista Srl", "is_customer": False, "is_supplier": True, "vat_number": "07123450012"}).json()
    vite = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "VITE", "description": "Vite", "min_stock": "100",
                       "reorder_qty": "500", "preferred_supplier_id": sup["id"],
                       "suppliers": [{"supplier_id": sup["id"], "supplier_code": "GR-VITE"}]}).json()
    farina = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "FAR", "description": "Farina", "lot_managed": True}).json()
    return h, sup, vite, farina


def doc(client, h, body):
    r = client.post(f"{A}/documenti", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def confirm(client, h, d):
    r = client.post(f"{A}/documenti/{d['id']}/conferma", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def onhand(client, h, item):
    w = stock(client, h, item["id"])["warehouses"]
    return Decimal(w[0]["on_hand"]) if w else Decimal(0)


def test_ordine_evasione_parziale(client, admin_headers):
    h, sup, vite, _ = setup(client, admin_headers)
    o = confirm(client, h, doc(client, h, {"doc_type": "ORF", "party_id": sup["id"],
                                          "lines": [{"item_id": vite["id"], "quantity": "1000", "unit_price": "0.05"}]}))
    assert o["number"] == 1 and o["status"] == "confermato"
    assert Decimal(stock(client, h, vite["id"])["warehouses"][0]["ordered"]) == 1000
    line = o["lines"][0]["id"]
    r = client.post(f"{A}/documenti/{o['id']}/trasforma", headers=h, json={"to": "DDTF", "external_number": "D-1", "quantities": {line: "600"}})
    assert r.status_code == 201, r.text
    ddt = confirm(client, h, r.json())
    assert onhand(client, h, vite) == 600
    w = stock(client, h, vite["id"])["warehouses"][0]
    assert Decimal(w["ordered"]) == 400
    o = client.get(f"{A}/documenti/{o['id']}", headers=h).json()
    assert o["status"] == "confermato" and Decimal(o["lines"][0]["residual"]) == 400
    ddt2 = confirm(client, h, client.post(f"{A}/documenti/{o['id']}/trasforma", headers=h, json={"to": "DDTF", "external_number": "D-2"}).json())
    o = client.get(f"{A}/documenti/{o['id']}", headers=h).json()
    assert o["status"] == "evaso" and Decimal(stock(client, h, vite["id"])["warehouses"][0]["ordered"]) == 0
    assert {r["label"] for r in o["related"]} == {"DDT fornitore"}
    # fattura differita da due DDT: il magazzino non si muove di nuovo
    f = client.post(f"{A}/fattura-da-ddt", headers=h, json={"ddt_ids": [ddt["id"], ddt2["id"]], "external_number": "FT-9"}).json()
    assert f["moves_stock"] is False and Decimal(f["taxable_total"]) == Decimal("50.00")
    confirm(client, h, f)
    assert onhand(client, h, vite) == 1000
    assert client.get(f"{A}/documenti/{ddt['id']}", headers=h).json()["status"] == "evaso"
    assert client.get(f"{A}/documenti?da_fatturare=true", headers=h).json()["total"] == 0


def test_fattura_immediata_iva_e_annullamento(client, admin_headers):
    h, sup, vite, farina = setup(client, admin_headers)
    vats = {v["code"]: v["id"] for v in client.get("/api/anagrafiche/tabelle/aliquote-iva", headers=h).json()}
    f = doc(client, h, {"doc_type": "FTF", "party_id": sup["id"], "external_number": "A/12", "lines": [
        {"item_id": vite["id"], "quantity": "100", "unit_price": "0.20", "discount1": "10"},
        {"item_id": farina["id"], "quantity": "10", "unit_price": "1.00", "vat_rate_id": vats["4"], "lot_number": "l1"},
        {"description": "Spese di trasporto", "quantity": "1", "unit_price": "10"}]})
    assert Decimal(f["taxable_total"]) == Decimal("38.00")  # 18 + 10 + 10
    vs = {x["rate"]: Decimal(x["vat"]) for x in f["vat_summary"]}
    assert vs["22.00"] == Decimal("6.16") and vs["4.00"] == Decimal("0.40")
    assert Decimal(f["total"]) == Decimal("44.56")
    confirm(client, h, f)
    assert onhand(client, h, vite) == 100
    assert Decimal(stock(client, h, vite["id"])["item"]["avg_cost"]) == Decimal("0.18")  # netto sconto
    # stessa fattura una seconda volta: bloccata
    r = client.post(f"{A}/documenti", headers=h, json={"doc_type": "FTF", "party_id": sup["id"], "external_number": "A/12", "lines": []})
    assert r.status_code == 409
    # annullamento: storna il magazzino
    assert client.post(f"{A}/documenti/{f['id']}/annulla", headers=h).json()["status"] == "annullato"
    assert onhand(client, h, vite) == 0
    assert client.put(f"{A}/documenti/{f['id']}", headers=h, json={"doc_type": "FTF", "party_id": sup["id"], "external_number": "X"}).status_code == 409


def test_proposta_riordino(client, admin_headers):
    h, sup, vite, _ = setup(client, admin_headers)
    groups = client.get(f"{A}/proposta-riordino", headers=h).json()
    g = next(x for x in groups if x["supplier_id"] == sup["id"])
    assert g["items"][0]["code"] == "VITE" and Decimal(g["items"][0]["proposed_qty"]) == 500
    confirm(client, h, doc(client, h, {"doc_type": "ORF", "party_id": sup["id"], "lines": [{"item_id": vite["id"], "quantity": "500"}]}))
    assert all(x["supplier_id"] != sup["id"] for x in client.get(f"{A}/proposta-riordino", headers=h).json())  # già ordinato


XML = """<?xml version="1.0" encoding="UTF-8"?>
<p:FatturaElettronica versione="FPR12" xmlns:p="http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2">
 <FatturaElettronicaHeader>
  <CedentePrestatore><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>{vat}</IdCodice></IdFiscaleIVA>
   <Anagrafica><Denominazione>Molino Nuovo Spa</Denominazione></Anagrafica><RegimeFiscale>RF01</RegimeFiscale></DatiAnagrafici>
   <Sede><Indirizzo>Via del Grano</Indirizzo><NumeroCivico>3</NumeroCivico><CAP>71121</CAP><Comune>Foggia</Comune><Provincia>FG</Provincia><Nazione>IT</Nazione></Sede>
  </CedentePrestatore>
  <CessionarioCommittente><DatiAnagrafici><IdFiscaleIVA><IdPaese>IT</IdPaese><IdCodice>02345670984</IdCodice></IdFiscaleIVA></DatiAnagrafici></CessionarioCommittente>
 </FatturaElettronicaHeader>
 <FatturaElettronicaBody>
  <DatiGenerali><DatiGeneraliDocumento><TipoDocumento>TD01</TipoDocumento><Divisa>EUR</Divisa><Data>2026-10-20</Data><Numero>{num}</Numero>
   <ImportoTotaleDocumento>72.46</ImportoTotaleDocumento></DatiGeneraliDocumento></DatiGenerali>
  <DatiBeniServizi>
   <DettaglioLinee><NumeroLinea>1</NumeroLinea><CodiceArticolo><CodiceTipo>INTERNO</CodiceTipo><CodiceValore>SEM-25</CodiceValore></CodiceArticolo>
    <Descrizione>Semola rimacinata sacco 25 kg</Descrizione><Quantita>50.00</Quantita><UnitaMisura>KG</UnitaMisura><PrezzoUnitario>1.00000000</PrezzoUnitario>
    <ScontoMaggiorazione><Tipo>SC</Tipo><Percentuale>10.00</Percentuale></ScontoMaggiorazione><PrezzoTotale>45.00</PrezzoTotale><AliquotaIVA>4.00</AliquotaIVA></DettaglioLinee>
   <DettaglioLinee><NumeroLinea>2</NumeroLinea><Descrizione>Lievito di birra 500 g</Descrizione><Quantita>10.00</Quantita><PrezzoUnitario>2.00</PrezzoUnitario>
    <PrezzoTotale>20.00</PrezzoTotale><AliquotaIVA>10.00</AliquotaIVA></DettaglioLinee>
   <DettaglioLinee><NumeroLinea>3</NumeroLinea><Descrizione>Contributo trasporto</Descrizione><Quantita>1.00</Quantita><PrezzoUnitario>3.00</PrezzoUnitario>
    <PrezzoTotale>3.00</PrezzoTotale><AliquotaIVA>22.00</AliquotaIVA></DettaglioLinee>
   <DatiRiepilogo><AliquotaIVA>4.00</AliquotaIVA><ImponibileImporto>45.00</ImponibileImporto><Imposta>1.80</Imposta></DatiRiepilogo>
   <DatiRiepilogo><AliquotaIVA>10.00</AliquotaIVA><ImponibileImporto>20.00</ImponibileImporto><Imposta>2.00</Imposta></DatiRiepilogo>
   <DatiRiepilogo><AliquotaIVA>22.00</AliquotaIVA><ImponibileImporto>3.00</ImponibileImporto><Imposta>0.66</Imposta></DatiRiepilogo>
  </DatiBeniServizi>
  <DatiPagamento><CondizioniPagamento>TP02</CondizioniPagamento><DettaglioPagamento><ModalitaPagamento>MP05</ModalitaPagamento>
   <DataScadenzaPagamento>2026-11-30</DataScadenzaPagamento><ImportoPagamento>72.46</ImportoPagamento></DettaglioPagamento></DatiPagamento>
 </FatturaElettronicaBody>
</p:FatturaElettronica>"""


def _p7m(xml: bytes) -> bytes:
    from asn1crypto import cms
    return cms.ContentInfo({"content_type": "signed_data", "content": cms.SignedData({
        "version": "v1", "digest_algorithms": [], "encap_content_info": {"content_type": "data", "content": xml},
        "signer_infos": []})}).dump()


def test_import_fattura_elettronica(client, admin_headers, tmp_path, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "media_dir", str(tmp_path))
    h, sup, vite, farina = setup(client, admin_headers)
    sem = client.post("/api/anagrafiche/articoli", headers=h, json={"code": "SEMOLA", "description": "Semola", "unit": "KG", "lot_managed": True}).json()
    xml = XML.format(vat=SUPPLIER_VAT, num="FE-100").encode()
    r = client.post(f"{A}/import-xml/anteprima", headers=h, files=[("files", ("IT01114601006_00001.xml", xml, "text/xml"))])
    assert r.status_code == 200, r.text
    inv = r.json()["invoices"][0]
    assert inv["supplier_id"] is None and inv["supplier_name"] == "Molino Nuovo Spa" and inv["number"] == "FE-100"
    assert [l["action"] for l in inv["lines"]] == ["nuovo", "nuovo", "nuovo"] and inv["warnings"] == []
    body = {"file_ref": inv["file_ref"], "index": 0, "moves_stock": True, "lines": [
        {"number": 1, "action": "abbina", "item_id": sem["id"], "lot_number": "LS1", "expiry_date": "2027-06-30"},
        {"number": 2, "action": "nuovo"}, {"number": 3, "action": "ignora"}]}
    r = client.post(f"{A}/import-xml/conferma", headers=h, json=body)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "confermato" and d["source"] == "xml" and d["warnings"] == [] and Decimal(d["total"]) == Decimal("72.46")
    assert d["payment_schedule"][0]["due_date"] == "2026-11-30"
    assert onhand(client, h, sem) == 50 and Decimal(stock(client, h, sem["id"])["item"]["avg_cost"]) == Decimal("0.90")
    assert client.get(f"{A}/documenti/{d['id']}", headers=h).json()["xml_url"]
    lievito = client.get("/api/anagrafiche/articoli?q=Lievito", headers=h).json()["rows"][0]
    assert Decimal(lievito["last_cost"]) == 2
    # seconda fattura dello stesso fornitore (firmata .p7m, in un .zip): fornitore e righe abbinati in automatico
    xml2 = XML.format(vat=SUPPLIER_VAT, num="FE-101").encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("IT01114601006_00002.xml.p7m", _p7m(xml2))
        z.writestr("IT01114601006_00002_MT_001.xml", b"<ricevuta/>")
    r = client.post(f"{A}/import-xml/anteprima", headers=h, files=[("files", ("fatture.zip", buf.getvalue(), "application/zip"))])
    inv2 = r.json()["invoices"][0]
    assert inv2["supplier_id"] and [l["action"] for l in inv2["lines"]] == ["abbina", "abbina", "nuovo"]
    assert inv2["lines"][0]["match"] == "codice fornitore" and inv2["lines"][1]["match"] == "abbinamento precedente"
    # la stessa fattura già registrata viene segnalata
    r = client.post(f"{A}/import-xml/anteprima", headers=h, files=[("files", ("x.p7m", base64.b64encode(_p7m(xml)), "application/pkcs7"))])
    assert r.json()["invoices"][0]["duplicate"] is True
    bad = client.post(f"{A}/import-xml/anteprima", headers=h, files=[("files", ("x.xml", b"<html></html>", "text/xml"))])
    assert bad.status_code == 422
