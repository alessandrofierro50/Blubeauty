"""Lettura delle fatture elettroniche ricevute (FatturaPA): XML, XML firmato .p7m (anche in base64) e archivi .zip.

Il parser ignora i namespace, così funziona con le versioni FPR12/FPA12 e con i file prodotti da gestionali diversi."""

import base64
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from lxml import etree

from fastapi import HTTPException, status


def fail(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)


@dataclass
class XmlLine:
    number: int
    codes: list[tuple[str, str]]  # (CodiceTipo, CodiceValore)
    description: str
    quantity: Decimal
    unit: str | None
    unit_price: Decimal
    discounts: list[Decimal]  # percentuali (positive = sconto)
    total: Decimal
    vat_rate: Decimal
    nature: str | None
    ddt_numbers: list[str] = field(default_factory=list)


@dataclass
class XmlInvoice:
    file_name: str
    supplier: dict
    customer_vat: str | None
    doc_type: str  # TD01, TD04...
    number: str
    date: date
    currency: str
    total: Decimal | None
    lines: list[XmlLine]
    payments: list[dict]
    ddt: list[dict]
    summary: list[dict]
    stamp_duty: Decimal
    raw: bytes


def _strip_ns(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _t(el, path: str, default=None):
    if el is None:
        return default
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else default


def _d(v, default=Decimal(0)) -> Decimal:
    if v in (None, ""):
        return default
    try:
        return Decimal(str(v).strip())
    except InvalidOperation:
        return default


def extract_xml(name: str, data: bytes) -> bytes:
    """Restituisce l'XML in chiaro da .xml o .p7m (DER o base64)."""
    if name.lower().endswith(".p7m") or not data.lstrip().startswith(b"<"):
        raw = data
        if not raw[:1] == b"\x30":  # non è DER: forse base64
            try:
                raw = base64.b64decode(re.sub(rb"\s+", b"", data), validate=False)
            except Exception:
                raise fail(f"{name}: file firmato non leggibile") from None
        try:
            from asn1crypto import cms
            content = cms.ContentInfo.load(raw)["content"]["encap_content_info"]["content"]
            xml = content.native if content.native is not None else b""
        except Exception:
            # ultimo tentativo: l'XML è contenuto in chiaro nei byte
            m = re.search(rb"<\?xml.*?</(?:\w+:)?FatturaElettronica>", raw, re.S)
            if not m:
                raise fail(f"{name}: impossibile estrarre la fattura dal file firmato") from None
            xml = m.group(0)
        return xml
    return data


def parse_xml(name: str, xml: bytes) -> list[XmlInvoice]:
    try:
        root = _strip_ns(etree.fromstring(xml, parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=True)))
    except etree.XMLSyntaxError:
        raise fail(f"{name}: XML non valido") from None
    if root is None or root.tag != "FatturaElettronica":
        raise fail(f"{name}: non è una fattura elettronica")
    h = root.find("FatturaElettronicaHeader")
    ced = h.find("CedentePrestatore")
    da = ced.find("DatiAnagrafici")
    an = da.find("Anagrafica")
    name_ = _t(an, "Denominazione") or " ".join(x for x in (_t(an, "Cognome"), _t(an, "Nome")) if x)
    sede = ced.find("Sede")
    supplier = {
        "name": name_,
        "vat_country": _t(da, "IdFiscaleIVA/IdPaese", "IT"),
        "vat_number": _t(da, "IdFiscaleIVA/IdCodice"),
        "tax_code": _t(da, "CodiceFiscale"),
        "address": " ".join(x for x in (_t(sede, "Indirizzo"), _t(sede, "NumeroCivico")) if x) or None,
        "zip_code": _t(sede, "CAP"), "city": _t(sede, "Comune"), "province": _t(sede, "Provincia"),
        "country": _t(sede, "Nazione", "IT"),
        "email": _t(ced, "Contatti/Email"), "phone": _t(ced, "Contatti/Telefono"),
        "regime": _t(da, "RegimeFiscale"),
    }
    customer_vat = _t(h, "CessionarioCommittente/DatiAnagrafici/IdFiscaleIVA/IdCodice")

    out = []
    for body in root.findall("FatturaElettronicaBody"):
        gen = body.find("DatiGenerali/DatiGeneraliDocumento")
        ddt = [{"number": _t(x, "NumeroDDT"), "date": _t(x, "DataDDT"),
                "lines": [int(l.text) for l in x.findall("RiferimentoNumeroLinea") if l.text]} for x in body.findall("DatiGenerali/DatiDDT")]
        lines = []
        for dl in body.findall("DatiBeniServizi/DettaglioLinee"):
            discounts = []
            for sm in dl.findall("ScontoMaggiorazione"):
                pct = _d(_t(sm, "Percentuale"), None)
                if pct is not None:
                    discounts.append(pct if _t(sm, "Tipo") == "SC" else -pct)
            qty = _d(_t(dl, "Quantita"), Decimal(1))
            total = _d(_t(dl, "PrezzoTotale"))
            price = _d(_t(dl, "PrezzoUnitario"))
            if not discounts and qty and price and abs(price * qty - total) > Decimal("0.02"):
                # sconto espresso solo come importo: riportato a percentuale per non perdere il netto
                discounts = [((1 - total / (price * qty)) * 100).quantize(Decimal("0.0001"))]
            num = int(_t(dl, "NumeroLinea", "0") or 0)
            lines.append(XmlLine(
                number=num,
                codes=[(_t(c, "CodiceTipo", ""), _t(c, "CodiceValore", "")) for c in dl.findall("CodiceArticolo")],
                description=_t(dl, "Descrizione", ""), quantity=qty, unit=_t(dl, "UnitaMisura"), unit_price=price,
                discounts=discounts, total=total, vat_rate=_d(_t(dl, "AliquotaIVA")), nature=_t(dl, "Natura"),
                ddt_numbers=[d["number"] for d in ddt if num in d["lines"] or (not d["lines"] and len(ddt) == 1)],
            ))
        payments = []
        for dp in body.findall("DatiPagamento/DettaglioPagamento"):
            payments.append({"method": _t(dp, "ModalitaPagamento"), "due_date": _t(dp, "DataScadenzaPagamento"),
                             "amount": str(_d(_t(dp, "ImportoPagamento"))), "iban": _t(dp, "IBAN")})
        summary = [{"rate": str(_d(_t(r, "AliquotaIVA"))), "nature": _t(r, "Natura"), "taxable": str(_d(_t(r, "ImponibileImporto"))),
                    "vat": str(_d(_t(r, "Imposta")))} for r in body.findall("DatiBeniServizi/DatiRiepilogo")]
        try:
            doc_date = date.fromisoformat(_t(gen, "Data", "")[:10])
        except ValueError:
            raise fail(f"{name}: data documento non valida") from None
        out.append(XmlInvoice(
            file_name=name, supplier=supplier, customer_vat=customer_vat, doc_type=_t(gen, "TipoDocumento", "TD01"),
            number=_t(gen, "Numero", ""), date=doc_date, currency=_t(gen, "Divisa", "EUR"),
            total=_d(_t(gen, "ImportoTotaleDocumento"), None), lines=lines, payments=payments, ddt=ddt, summary=summary,
            stamp_duty=_d(_t(gen, "DatiBollo/ImportoBollo")), raw=xml,
        ))
    return out


def read_files(files: list[tuple[str, bytes]]) -> tuple[list[XmlInvoice], list[str]]:
    """Accetta .xml, .p7m e .zip (anche con più fatture). Gli errori di un file non bloccano gli altri."""
    invoices, errors = [], []
    queue = list(files)
    while queue:
        name, data = queue.pop(0)
        low = name.lower()
        try:
            if low.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for zi in z.infolist():
                        if not zi.is_dir() and zi.filename.lower().endswith((".xml", ".p7m")) and zi.file_size < 20_000_000:
                            queue.append((zi.filename.rsplit("/", 1)[-1], z.read(zi)))
                continue
            if "_MT_" in name.upper() or "_RC_" in name.upper() or "_NS_" in name.upper():
                continue  # ricevute SDI, non fatture
            invoices += parse_xml(name, extract_xml(name, data))
        except HTTPException as exc:
            errors.append(exc.detail)
        except zipfile.BadZipFile:
            errors.append(f"{name}: archivio zip non valido")
    if not invoices and errors:
        raise fail("; ".join(errors))
    return invoices, errors
