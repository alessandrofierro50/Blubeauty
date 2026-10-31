"""Fattura di BluCode al cliente per l'abbonamento: numero dal sezionale, XML FatturaPA 1.2.2 e importi.

Regole fiscali (contratto comune pagamenti.md, confermate dal titolare il 2026-10-29):
- cedente BluCode in regime forfettario (REGIME_FISCALE=RF19): ogni riga AliquotaIVA 0.00 e Natura N2.2, con la dicitura
  di legge in Causale e il riferimento normativo nel riepilogo;
- bollo virtuale 2,00 € se l'imponibile supera 77,47 €; con BOLLO_A_CARICO=cliente si aggiunge la riga
  «Rimborso imposta di bollo» (anch'essa N2.2) e il cliente la paga;
- TD01, FPR12 per aziende e privati, FPA12 per la PA (codice univoco ufficio di 6 caratteri);
- ModalitaPagamento MP08 per carta e PayPal, MP05 per il bonifico (con l'IBAN di BluCode).

IdTrasmittente: con FATTURE_INVIO=manuale il file lo carica il titolare sul portale dell'Agenzia delle Entrate, quindi il
trasmittente è BluCode stessa (la sua partita IVA); con FATTURE_INVIO=sdi parte da Aruba, che richiede il proprio codice.

Si riusano gli strumenti di app/fatturapa/xml_builder.py (pulizia del testo, importi, sede, validazione XSD offline).
"""

from dataclasses import dataclass
from decimal import Decimal

from lxml import etree
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.anagrafiche.validators import valid_vat_it
from app.core.config import get_settings
from app.fatturapa import xml_builder as xb
from app.pagamenti.models import XML_METHOD, Payment

STAMP_THRESHOLD = Decimal("77.47")
STAMP_AMOUNT = Decimal("2.00")
NATURA = "N2.2"
FORFETTARIO_TEXT = ("Operazione effettuata ai sensi dell'art. 1, commi da 54 a 89, della Legge n. 190/2014 — regime forfettario. "
                    "Non soggetta a IVA né a ritenuta d'acconto")
FORFETTARIO_REF = "Art. 1, commi 54-89, L. 190/2014 - regime forfettario"
STAMP_TEXT = "Imposta di bollo assolta in modo virtuale ai sensi del D.M. 17/06/2014"
PROFORMA_NOTE = ("Documento non valido ai fini fiscali: la fattura elettronica sarà disponibile nella tua area riservata "
                 "dell'Agenzia delle Entrate")
PERIOD_LABEL = {"mensile": "mensile", "annuale": "annuale"}


# ---------------------------------------------------------------- importi


@dataclass
class Amounts:
    amount: Decimal  # canone
    stamp_duty: Decimal  # bollo in fattura (DatiBollo)
    stamp: Decimal  # rimborso del bollo addebitato al cliente
    total: Decimal  # da pagare


def amounts(price: Decimal, bollo_a_carico: str) -> Amounts:
    """Importi calcolati sempre dal server, dal listino: il browser non manda mai un prezzo."""
    price = Decimal(price).quantize(xb.CENT)
    duty = STAMP_AMOUNT if price > STAMP_THRESHOLD else Decimal("0.00")
    stamp = duty if bollo_a_carico == "cliente" else Decimal("0.00")
    return Amounts(amount=price, stamp_duty=duty, stamp=stamp, total=price + stamp)


# ---------------------------------------------------------------- numerazione


def next_number(db: Session, sezionale: str, year: int) -> int:
    """Prossimo numero del sezionale per l'anno solare: atomico e senza buchi.

    L'UPSERT blocca la riga del contatore fino alla fine della transazione: due conferme contemporanee si mettono in fila,
    e se la conferma fallisce (rollback) il numero non viene consumato. Ogni anno riparte da 1 (nuova riga)."""
    return db.execute(
        text("INSERT INTO invoice_counters (sezionale, year, last_number) VALUES (:s, :y, 1) "
             "ON CONFLICT (sezionale, year) DO UPDATE SET last_number = invoice_counters.last_number + 1 "
             "RETURNING last_number"),
        {"s": sezionale, "y": year},
    ).scalar_one()


def progressive(p: Payment) -> str:
    """ProgressivoInvio e parte finale del nome del file: 5 caratteri alfanumerici, unico per anno e numero."""
    return xb.progressive_code((p.invoice_year - 2000) * 100000 + p.invoice_number)


# ---------------------------------------------------------------- cedente


def cedente() -> dict:
    s = get_settings()
    return {"denominazione": s.cedente_denominazione, "piva": s.cedente_piva.replace(" ", "").upper().removeprefix("IT"),
            "cf": s.cedente_cf.replace(" ", "").upper(), "indirizzo": s.cedente_indirizzo, "cap": s.cedente_cap,
            "comune": s.cedente_comune, "provincia": s.cedente_provincia.upper(), "regime": s.regime_fiscale or "RF19"}


def cedente_problems() -> list[str]:
    c = cedente()
    errs = []
    if not c["denominazione"]:
        errs.append("CEDENTE_DENOMINAZIONE non impostata")
    if not valid_vat_it(c["piva"]):
        errs.append("CEDENTE_PIVA mancante o non valida")
    for k in ("indirizzo", "cap", "comune", "provincia"):
        if not c[k]:
            errs.append(f"CEDENTE_{k.upper()} non impostato")
    if c["regime"] not in xb.REGIMI:
        errs.append(f"REGIME_FISCALE «{c['regime']}» non valido")
    return errs


def xml_filename(p: Payment) -> str:
    return f"IT{cedente()['piva']}_{progressive(p)}.xml"


def transmission_format(billing: dict) -> str:
    return "FPA12" if billing.get("tipo") == "pa" else "FPR12"


def line_description(p: Payment) -> str:
    s = get_settings()
    dal = p.period_start.strftime("%d/%m/%Y") if p.period_start else ""
    al = p.period_end.strftime("%d/%m/%Y") if p.period_end else ""
    plan = p.plan_name if p.plan_name.lower().startswith(s.brand_name.lower()) else f"{s.brand_name} {p.plan_name}"
    return f"Abbonamento {plan} - {PERIOD_LABEL.get(p.period, p.period)} dal {dal} al {al}"


# ---------------------------------------------------------------- XML


def build_xml(p: Payment, iban: str = "") -> bytes:
    """XML FatturaPA della fattura `p` (già numerata). `iban` di BluCode per i bonifici (MP05)."""
    s = get_settings()
    c = cedente()
    b = p.billing or {}
    fmt = transmission_format(b)
    el = xb._el
    root = etree.Element(f"{{{xb.NS}}}FatturaElettronica", nsmap={"p": xb.NS, "ds": xb.DS, "xsi": xb.XSI})
    root.set("versione", fmt)

    head = el(root, "FatturaElettronicaHeader")
    tr = el(head, "DatiTrasmissione")
    idt = el(tr, "IdTrasmittente")
    el(idt, "IdPaese", "IT")
    el(idt, "IdCodice", xb.ARUBA_CF if s.fatture_invio == "sdi" else c["piva"])
    el(tr, "ProgressivoInvio", progressive(p))
    el(tr, "FormatoTrasmissione", fmt)
    foreign = (b.get("nazione") or "IT") != "IT"
    code = "XXXXXXX" if foreign else (b.get("codice_destinatario") or "0000000")
    el(tr, "CodiceDestinatario", code)
    if code == "0000000" and b.get("pec") and fmt == "FPR12":
        el(tr, "PECDestinatario", xb.clean(b["pec"], 256))

    ced = el(head, "CedentePrestatore")
    da = el(ced, "DatiAnagrafici")
    fi = el(da, "IdFiscaleIVA")
    el(fi, "IdPaese", "IT")
    el(fi, "IdCodice", c["piva"])
    if c["cf"]:
        el(da, "CodiceFiscale", c["cf"])
    an = el(da, "Anagrafica")
    el(an, "Denominazione", xb.clean(c["denominazione"], 80))
    el(da, "RegimeFiscale", c["regime"])
    xb._sede(ced, c["indirizzo"], None, c["cap"], c["comune"], c["provincia"], "IT")

    ces = el(head, "CessionarioCommittente")
    da = el(ces, "DatiAnagrafici")
    if b.get("partita_iva"):
        fi = el(da, "IdFiscaleIVA")
        el(fi, "IdPaese", (b.get("nazione") or "IT").upper())
        el(fi, "IdCodice", b["partita_iva"][:28])
    if b.get("codice_fiscale") and not foreign:
        el(da, "CodiceFiscale", b["codice_fiscale"])
    an = el(da, "Anagrafica")
    if b.get("tipo") == "privato":
        el(an, "Nome", xb.clean(b.get("nome"), 60))
        el(an, "Cognome", xb.clean(b.get("cognome"), 60))
    else:
        el(an, "Denominazione", xb.clean(b.get("denominazione"), 80))
    xb._sede(ces, b.get("indirizzo"), None, "00000" if foreign else b.get("cap"), b.get("comune"),
             None if foreign else b.get("provincia"), b.get("nazione") or "IT")

    body = el(root, "FatturaElettronicaBody")
    dg = el(el(body, "DatiGenerali"), "DatiGeneraliDocumento")
    el(dg, "TipoDocumento", "TD01")
    el(dg, "Divisa", "EUR")
    el(dg, "Data", p.invoice_date.isoformat())
    el(dg, "Numero", p.invoice_label)
    if Decimal(p.stamp_duty or 0) > 0:
        bo = el(dg, "DatiBollo")
        el(bo, "BolloVirtuale", "SI")
        el(bo, "ImportoBollo", xb.amount(p.stamp_duty))
    el(dg, "ImportoTotaleDocumento", xb.amount(p.total))
    causale = xb.clean(FORFETTARIO_TEXT if c["regime"] == "RF19" else "", 1000)
    for i in range(0, len(causale), 200):
        el(dg, "Causale", causale[i:i + 200])

    bs = el(body, "DatiBeniServizi")
    lines = [(line_description(p), Decimal(p.amount))]
    if Decimal(p.stamp or 0) > 0:
        lines.append(("Rimborso imposta di bollo", Decimal(p.stamp)))
    for n, (desc, value) in enumerate(lines, start=1):
        dl = el(bs, "DettaglioLinee")
        el(dl, "NumeroLinea", n)
        el(dl, "Descrizione", xb.clean(desc, 1000))
        el(dl, "Quantita", "1.00")
        el(dl, "PrezzoUnitario", xb.decimal_text(value))
        el(dl, "PrezzoTotale", xb.decimal_text(value))
        el(dl, "AliquotaIVA", "0.00")
        el(dl, "Natura", NATURA)
    r = el(bs, "DatiRiepilogo")
    el(r, "AliquotaIVA", "0.00")
    el(r, "Natura", NATURA)
    el(r, "ImponibileImporto", xb.amount(sum((v for _, v in lines), Decimal(0))))
    el(r, "Imposta", "0.00")
    el(r, "RiferimentoNormativo", xb.clean(FORFETTARIO_REF, 100))

    pg = el(body, "DatiPagamento")
    el(pg, "CondizioniPagamento", "TP02")
    dp = el(pg, "DettaglioPagamento")
    el(dp, "ModalitaPagamento", XML_METHOD[p.method])
    el(dp, "DataScadenzaPagamento", p.invoice_date.isoformat())
    el(dp, "ImportoPagamento", xb.amount(p.total))
    if p.method == "bonifico" and iban:
        el(dp, "IBAN", iban.replace(" ", "").upper())
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def make_xml(p: Payment, iban: str = "") -> tuple[bytes | None, list[str]]:
    """XML validato sull'XSD ufficiale. Senza i dati del cedente nel .env non si genera (errori da correggere, poi «Reinvia»)."""
    errs = cedente_problems()
    if errs:
        return None, errs
    xml = build_xml(p, iban)
    return xml, [f"Schema: {e}" for e in xb.validate(xml)]

