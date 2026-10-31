"""Generazione dell'XML FatturaPA (v1.2.2) dalle fatture di vendita, controlli preventivi e validazione XSD.

Ordine degli elementi e vincoli seguono lo schema ufficiale (app/fatturapa/xsd). IdTrasmittente è sempre Aruba PEC
(01879020517), come richiesto dal controllo sincrono 0094 di Aruba."""

import os
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from lxml import etree
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Item, Party, VatRate
from app.anagrafiche.validators import valid_tax_code_it as valid_tax_code, valid_vat_it
from app.core.models import Company
from app.documenti.models import Document, DocumentLine, DocumentLink
from app.scadenzario.models import Installment

NS = "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"
DS = "http://www.w3.org/2000/09/xmldsig#"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ARUBA_CF = "01879020517"
TIPO = {"FTI": "TD01", "FTD": "TD24", "NC": "TD04"}
REGIMI = {"RF01", "RF02", "RF04", "RF05", "RF06", "RF07", "RF08", "RF09", "RF10", "RF11", "RF12", "RF13", "RF14", "RF15",
          "RF16", "RF17", "RF18", "RF19", "RF20"}
CENT = Decimal("0.01")

# caratteri ammessi: Basic Latin + Latin-1 Supplement. Sostituzioni comuni prima di scartare il resto.
_REPL = {"–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "€": "EUR", "…": "...", "•": "-", " ": " ",
         "×": "x", "\t": " ", "Ł": "L", "ł": "l", "Œ": "OE", "œ": "oe", "Đ": "D", "đ": "d"}


def clean(text: str | None, size: int) -> str:
    t = "".join(_REPL.get(ch, ch) for ch in (text or ""))
    out = []
    for ch in t:
        if ch == "\n" or ch == "\r":
            out.append(" ")
        elif ord(ch) < 32:
            continue
        elif ord(ch) <= 255:
            out.append(ch)
        else:  # lettere accentate fuori da Latin-1 → senza accento, il resto → spazio
            base = unicodedata.normalize("NFKD", ch).encode("ascii", "ignore").decode()
            out.append(base or " ")
    return re.sub(r" {2,}", " ", "".join(out)).strip()[:size]


def amount(v) -> str:
    return str(Decimal(v or 0).quantize(CENT, ROUND_HALF_UP))


def decimal_text(v, min_dec: int = 2, max_dec: int = 8) -> str:
    """Prezzi e quantità: da 2 a 8 decimali, senza zeri inutili."""
    d = Decimal(v or 0).quantize(Decimal(1).scaleb(-max_dec), ROUND_HALF_UP)
    s = format(d, "f")
    if "." in s:
        intp, dec = s.split(".")
        dec = dec.rstrip("0")
        dec = dec.ljust(min_dec, "0")
        return f"{intp}.{dec}"
    return s + "." + "0" * min_dec


def split_vat(vat: str | None, default_country: str = "IT") -> tuple[str, str] | None:
    if not vat:
        return None
    v = vat.replace(" ", "").upper()
    if len(v) > 2 and v[:2].isalpha():
        return v[:2], v[2:]
    return default_country or "IT", v


@dataclass
class Check:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def transmission_format(party: Party) -> str:
    code = (party.sdi_code or "").strip().upper()
    return "FPA12" if party.person_type == "pa" or len(code) == 6 else "FPR12"


def recipient_code(party: Party) -> str:
    code = (party.sdi_code or "").strip().upper()
    if (party.country or "IT") != "IT":
        return "XXXXXXX"
    if code:
        return code
    return "0000000"


def precheck(db: Session, d: Document) -> Check:
    c = Check()
    if d.direction != "vendita" or d.doc_type not in TIPO:
        c.errors.append("Si inviano a SDI solo fatture, fatture differite e note di credito")
        return c
    if d.status not in ("confermato", "evaso"):
        c.errors.append("Emetti la fattura prima di inviarla")
    co = db.get(Company, d.company_id)
    p = db.get(Party, d.party_id)
    # cedente (la tua azienda)
    if not co.vat_number:
        c.errors.append("Dati azienda: manca la partita IVA")
    elif not valid_vat_it(co.vat_number.replace("IT", "")):
        c.errors.append("Dati azienda: partita IVA non valida")
    for f, label in (("address", "l'indirizzo"), ("zip_code", "il CAP"), ("city", "il comune"), ("province", "la provincia")):
        if not getattr(co, f):
            c.errors.append(f"Dati azienda: manca {label}")
    if co.zip_code and not re.fullmatch(r"\d{5}", co.zip_code):
        c.errors.append("Dati azienda: il CAP deve avere 5 cifre")
    if (co.tax_regime or "RF01") not in REGIMI:
        c.errors.append(f"Dati azienda: regime fiscale «{co.tax_regime}» non valido (es. RF01 ordinario, RF19 forfettario)")
    if bool(co.rea_office) != bool(co.rea_number):
        c.errors.append("Dati azienda: per l'iscrizione REA servono sia l'ufficio (provincia) sia il numero")
    # cessionario (il cliente)
    foreign = (p.country or "IT") != "IT"
    if not p.vat_number and not p.tax_code:
        c.errors.append(f"Cliente {p.name}: serve la partita IVA o il codice fiscale")
    if p.vat_number and not foreign and not p.vat_number.upper().startswith(("IT",)) and not valid_vat_it(p.vat_number):
        c.errors.append(f"Cliente {p.name}: partita IVA non valida")
    if p.tax_code and not foreign and not valid_tax_code(p.tax_code):
        c.errors.append(f"Cliente {p.name}: codice fiscale non valido")
    if p.person_type == "privato" and not foreign and not p.tax_code:
        c.errors.append(f"Cliente {p.name}: per i privati serve il codice fiscale")
    for f, label in (("address", "l'indirizzo"), ("city", "il comune")):
        if not getattr(p, f):
            c.errors.append(f"Cliente {p.name}: manca {label}")
    if not foreign and not (p.zip_code and re.fullmatch(r"\d{5}", p.zip_code)):
        c.errors.append(f"Cliente {p.name}: manca il CAP o non ha 5 cifre")
    code = (p.sdi_code or "").strip().upper()
    if code and not re.fullmatch(r"[A-Z0-9]{6,7}", code):
        c.errors.append(f"Cliente {p.name}: codice destinatario non valido (7 caratteri, 6 per la PA)")
    if transmission_format(p) == "FPA12" and len(code) != 6:
        c.errors.append(f"Cliente {p.name}: per la Pubblica Amministrazione serve il codice univoco ufficio (6 caratteri)")
    if not foreign and not code and not p.pec and p.person_type != "privato":
        c.warnings.append(f"Cliente {p.name}: senza codice destinatario né PEC la fattura andrà nel suo cassetto fiscale "
                          "(consegnagli una copia)")
    # righe
    real = [ln for ln in d.lines if ln.quantity or ln.unit_price]
    if not real:
        c.errors.append("La fattura non ha righe con importi")
    for ln in real:
        if Decimal(ln.vat_rate or 0) == 0 and not ln.vat_nature:
            c.errors.append(f"Riga {ln.line_no}: aliquota 0% senza natura dell'esenzione (scegli un codice IVA N1…N7)")
        exact = Decimal(ln.unit_price or 0) * Decimal(ln.quantity or 0)
        for disc in (ln.discount1, ln.discount2, ln.discount3):
            if disc:
                exact = exact * (100 - Decimal(disc)) / 100
        if abs(exact - Decimal(ln.line_total or 0)) > CENT:
            c.errors.append(f"Riga {ln.line_no}: importo {ln.line_total} diverso da prezzo × quantità con sconti ({exact:.2f})")
    if d.doc_type == "FTD" and not _linked(db, d, "DDT"):
        c.errors.append("La fattura differita deve riferirsi ai DDT da cui nasce")
    if d.doc_type == "NC" and not _linked(db, d, ("FTI", "FTD")):
        c.warnings.append("La nota di credito non è collegata alla fattura che storna: indicala nelle note se serve")
    if p.split_payment and transmission_format(p) != "FPA12":
        c.warnings.append(f"Cliente {p.name}: split payment impostato ma non è una PA")
    return c


def _linked(db: Session, d: Document, types) -> list[Document]:
    types = (types,) if isinstance(types, str) else types
    ids = db.scalars(select(DocumentLink.from_id).where(DocumentLink.to_id == d.id)).all()
    if not ids:
        return []
    return list(db.scalars(select(Document).where(Document.id.in_(ids), Document.doc_type.in_(types), Document.status != "annullato")
                           .order_by(Document.doc_date, Document.number)))


def _el(parent, tag: str, text=None):
    e = etree.SubElement(parent, tag)
    if text is not None:
        e.text = str(text)
    return e


def doc_number(d: Document, db: Session | None = None) -> str:
    if db is not None:
        from app.documenti import numerazioni
        return numerazioni.display_number(db, d) or ""
    return f"{d.number}" + (f"/{d.series}" if d.series else "")


def build(db: Session, d: Document, progressive: str) -> bytes:
    co = db.get(Company, d.company_id)
    p = db.get(Party, d.party_id)
    fmt = transmission_format(p)
    root = etree.Element(f"{{{NS}}}FatturaElettronica", nsmap={"p": NS, "ds": DS, "xsi": XSI})
    root.set("versione", fmt)
    root.set(f"{{{XSI}}}schemaLocation", f"{NS} http://www.fatturapa.gov.it/export/fatturazione/sdi/fatturapa/v1.2/Schema_del_file_xml_FatturaPA_versione_1.2.xsd")

    head = _el(root, "FatturaElettronicaHeader")
    tr = _el(head, "DatiTrasmissione")
    idt = _el(tr, "IdTrasmittente")
    _el(idt, "IdPaese", "IT")
    _el(idt, "IdCodice", ARUBA_CF)
    _el(tr, "ProgressivoInvio", progressive)
    _el(tr, "FormatoTrasmissione", fmt)
    code = recipient_code(p)
    _el(tr, "CodiceDestinatario", code)
    if code == "0000000" and p.pec and fmt == "FPR12":
        _el(tr, "PECDestinatario", clean(p.pec, 256))

    # cedente / prestatore
    ced = _el(head, "CedentePrestatore")
    da = _el(ced, "DatiAnagrafici")
    country, vat = split_vat(co.vat_number)
    fi = _el(da, "IdFiscaleIVA")
    _el(fi, "IdPaese", country)
    _el(fi, "IdCodice", vat)
    if co.tax_code:
        _el(da, "CodiceFiscale", co.tax_code.upper())
    an = _el(da, "Anagrafica")
    _el(an, "Denominazione", clean(co.name, 80))
    _el(da, "RegimeFiscale", co.tax_regime or "RF01")
    _sede(ced, co.address, None, co.zip_code, co.city, co.province, "IT")
    if co.rea_office and co.rea_number:
        rea = _el(ced, "IscrizioneREA")
        _el(rea, "Ufficio", co.rea_office.upper())
        _el(rea, "NumeroREA", clean(co.rea_number, 20))
        if co.share_capital:
            _el(rea, "CapitaleSociale", amount(co.share_capital))
        if co.sole_shareholder in ("SU", "SM"):
            _el(rea, "SocioUnico", co.sole_shareholder)
        _el(rea, "StatoLiquidazione", "LS" if co.in_liquidation else "LN")
    if co.phone or co.email:
        ct = _el(ced, "Contatti")
        if co.phone:
            _el(ct, "Telefono", clean(re.sub(r"[^\d+ ]", "", co.phone), 12))
        if co.email:
            _el(ct, "Email", clean(co.email, 256))

    # cessionario / committente
    ces = _el(head, "CessionarioCommittente")
    da = _el(ces, "DatiAnagrafici")
    foreign = (p.country or "IT") != "IT"
    sv = split_vat(p.vat_number, p.country or "IT")
    if sv:
        fi = _el(da, "IdFiscaleIVA")
        _el(fi, "IdPaese", sv[0])
        _el(fi, "IdCodice", sv[1][:28])
    if p.tax_code and not foreign:
        _el(da, "CodiceFiscale", p.tax_code.upper())
    an = _el(da, "Anagrafica")
    if p.person_type == "privato" and p.first_name and p.last_name:
        _el(an, "Nome", clean(p.first_name, 60))
        _el(an, "Cognome", clean(p.last_name, 60))
    else:
        _el(an, "Denominazione", clean(p.name, 80))
    _sede(ces, p.address, p.street_number, "00000" if foreign else p.zip_code, p.city, None if foreign else p.province,
          p.country or "IT")

    # corpo
    body = _el(root, "FatturaElettronicaBody")
    gen = _el(body, "DatiGenerali")
    dg = _el(gen, "DatiGeneraliDocumento")
    _el(dg, "TipoDocumento", TIPO[d.doc_type])
    _el(dg, "Divisa", d.currency or "EUR")
    _el(dg, "Data", d.doc_date.isoformat())
    _el(dg, "Numero", doc_number(d, db))
    if stamp_duty(db, d) > 0:
        bo = _el(dg, "DatiBollo")
        _el(bo, "BolloVirtuale", "SI")
        _el(bo, "ImportoBollo", amount(stamp_duty(db, d)))
    _el(dg, "ImportoTotaleDocumento", amount(d.total))
    causale = clean(d.notes, 1000)
    for i in range(0, min(len(causale), 1000), 200):
        _el(dg, "Causale", causale[i:i + 200])

    if d.doc_type == "NC":
        for orig in _linked(db, d, ("FTI", "FTD")):
            fc = _el(gen, "DatiFattureCollegate")
            _el(fc, "IdDocumento", doc_number(orig, db))
            _el(fc, "Data", orig.doc_date.isoformat())
    lines = list(d.lines)
    if d.doc_type == "FTD":
        origin_doc = {}
        for ln in lines:
            if ln.origin_line_id:
                origin_doc[ln.id] = db.scalar(select(DocumentLine.document_id).where(DocumentLine.id == ln.origin_line_id))
        for ddt in _linked(db, d, "DDT"):
            dd = _el(gen, "DatiDDT")
            _el(dd, "NumeroDDT", clean(doc_number(ddt, db), 20))
            _el(dd, "DataDDT", ddt.doc_date.isoformat())
            for n, ln in enumerate(lines, start=1):
                if origin_doc.get(ln.id) == ddt.id:
                    _el(dd, "RiferimentoNumeroLinea", n)

    # righe
    bs = _el(body, "DatiBeniServizi")
    first_real = next((ln for ln in lines if ln.quantity or ln.unit_price), None)
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_({ln.item_id for ln in lines if ln.item_id})))} if lines else {}
    for n, ln in enumerate(lines, start=1):
        dl = _el(bs, "DettaglioLinee")
        _el(dl, "NumeroLinea", n)
        it = items.get(ln.item_id)
        if it:
            ca = _el(dl, "CodiceArticolo")
            _el(ca, "CodiceTipo", "INTERNO")
            _el(ca, "CodiceValore", clean(it.code, 35))
        _el(dl, "Descrizione", clean(ln.description, 1000) or "-")
        descriptive = not ln.quantity and not ln.unit_price
        if not descriptive:
            _el(dl, "Quantita", decimal_text(ln.quantity))
            if ln.unit:
                _el(dl, "UnitaMisura", clean(ln.unit, 10))
        _el(dl, "PrezzoUnitario", decimal_text(ln.unit_price))
        if not descriptive:
            for disc in (ln.discount1, ln.discount2, ln.discount3):
                if disc and Decimal(disc) != 0:
                    sm = _el(dl, "ScontoMaggiorazione")
                    _el(sm, "Tipo", "SC" if Decimal(disc) > 0 else "MG")
                    _el(sm, "Percentuale", amount(abs(Decimal(disc))))
        _el(dl, "PrezzoTotale", decimal_text(ln.line_total))
        ref = ln if not descriptive or not first_real else first_real  # le righe di testo prendono l'aliquota della prima riga
        _el(dl, "AliquotaIVA", amount(ref.vat_rate))
        if Decimal(ref.vat_rate or 0) == 0 and ref.vat_nature:
            _el(dl, "Natura", ref.vat_nature)

    # riepilogo IVA
    refs = {}
    for v in db.scalars(select(VatRate)):
        refs[(Decimal(v.rate).quantize(CENT), v.nature)] = v.legal_reference
    groups: dict = {}
    for ln in lines:
        if not ln.quantity and not ln.unit_price:
            continue
        key = (Decimal(ln.vat_rate or 0).quantize(CENT), ln.vat_nature if Decimal(ln.vat_rate or 0) == 0 else None)
        groups[key] = groups.get(key, Decimal(0)) + Decimal(ln.line_total or 0)
    split = bool(p.split_payment)
    for (rate, nature), taxable in sorted(groups.items(), key=lambda x: (-x[0][0], x[0][1] or "")):
        r = _el(bs, "DatiRiepilogo")
        _el(r, "AliquotaIVA", amount(rate))
        if nature:
            _el(r, "Natura", nature)
        _el(r, "ImponibileImporto", amount(taxable))
        _el(r, "Imposta", amount((taxable * rate / 100).quantize(CENT, ROUND_HALF_UP)))
        if not nature:
            _el(r, "EsigibilitaIVA", "S" if split else "I")
        if nature and refs.get((rate, nature)):
            _el(r, "RiferimentoNormativo", clean(refs[(rate, nature)], 100))

    # pagamento: dalle rate dello scadenzario
    if d.doc_type != "NC":
        rates = list(db.scalars(select(Installment).where(Installment.document_id == d.id).order_by(Installment.seq)))
        if rates:
            pg = _el(body, "DatiPagamento")
            _el(pg, "CondizioniPagamento", "TP01" if len(rates) > 1 else "TP02")
            for i in rates:
                dp = _el(pg, "DettaglioPagamento")
                method = i.method or "MP05"
                _el(dp, "ModalitaPagamento", method)
                _el(dp, "DataScadenzaPagamento", i.due_date.isoformat())
                _el(dp, "ImportoPagamento", amount(i.amount))
                if method == "MP05" and co.iban:
                    if co.bank_name:
                        _el(dp, "IstitutoFinanziario", clean(co.bank_name, 80))
                    _el(dp, "IBAN", co.iban.replace(" ", "").upper())
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _sede(parent, address, number, zip_code, city, province, country):
    s = _el(parent, "Sede")
    _el(s, "Indirizzo", clean(address, 60))
    if number:
        _el(s, "NumeroCivico", clean(number, 8))
    _el(s, "CAP", (zip_code or "00000")[:5])
    _el(s, "Comune", clean(city, 60))
    if province:
        _el(s, "Provincia", province.upper()[:2])
    _el(s, "Nazione", (country or "IT").upper())


@lru_cache(maxsize=1)
def _schema() -> etree.XMLSchema:
    path = os.path.join(os.path.dirname(__file__), "xsd", "FatturaPA_v1.2.2.xsd")
    parser = etree.XMLParser(no_network=True, load_dtd=False, resolve_entities=True)
    return etree.XMLSchema(etree.parse(path, parser))


def validate(xml: bytes) -> list[str]:
    schema = _schema()
    doc = etree.fromstring(xml, etree.XMLParser(no_network=True, resolve_entities=False))
    if schema.validate(doc):
        return []
    return [f"riga {e.line}: {e.message}" for e in schema.error_log][:20]


def stamp_duty(db, d) -> Decimal:
    """Bollo virtuale: quello del documento; per le fatture emesse prima del calcolo automatico si ricava dalle righe
    (a carico dell'azienda: il totale già emesso non cambia)."""
    if Decimal(d.stamp_duty or 0) > 0 or d.direction != "vendita":
        return Decimal(d.stamp_duty or 0)
    from app.documenti import service as docs
    if d.doc_type in docs.STAMP_DOC_TYPES and docs.stamp_mode(db, d.tenant_id) != "no" and docs.stamp_base(d) > docs.STAMP_THRESHOLD:
        return docs.STAMP_AMOUNT
    return Decimal(0)


def export_progressive(d) -> str:
    """ProgressivoInvio per l'XML esportato di una fattura non ancora trasmessa da BluBeauty: sempre lo stesso per la stessa
    fattura e diverso tra fatture (E + anno + sezionale + numero), distinto dai progressivi degli invii (00001, 00002…)."""
    code = f"E{d.year % 100:02d}{re.sub(r'[^A-Z0-9]', '', (d.series or '').upper())}{d.number or 0:04d}"
    if len(code) > 10:  # sezionale lungo: si tiene la parte finale, univoca per numero
        code = "E" + code[-9:]
    return code


def progressive_code(n: int) -> str:
    """ProgressivoInvio: alfanumerico, max 10 caratteri."""
    digits = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if n == 0:
            break
    return out.rjust(5, "0")
