"""PDF dei documenti di vendita con la firma del cliente: si allega all'email o si apre dal link mandato su WhatsApp.

Impaginazione semplice e leggibile anche dal telefono: intestazione dell'azienda, cliente, righe, riepilogo IVA,
dati di trasporto per i DDT e riquadro della consegna firmata (chi ha ritirato, quando, dove)."""

import io
import os
from datetime import datetime
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.anagrafiche.models import Party, PartyAddress, PaymentTerm
from app.core import media
from app.core.models import Company
from app.documenti import service as docs
from app.documenti.models import Document
from app.tentata.service import doc_label

TITLE = {"DDT": "Documento di trasporto", "FTI": "Fattura", "ORC": "Conferma d'ordine", "NC": "Nota di credito",
         "FTD": "Fattura differita", "PRV": "Preventivo"}


def _eur(v) -> str:
    s = f"{Decimal(v or 0):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _num(v) -> str:
    d = Decimal(v or 0).normalize()
    s = f"{d:f}"
    return s.replace(".", ",")


def _esc(s) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _when(v) -> str:
    try:
        return datetime.fromisoformat(str(v)).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return _esc(v)


def document_pdf(db: Session, d: Document) -> bytes:
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8, leading=10)
    normal = ParagraphStyle("n", parent=styles["Normal"], fontSize=9, leading=11.5)
    right = ParagraphStyle("r", parent=normal, alignment=TA_RIGHT)
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=15, leading=18, spaceAfter=2)
    company = db.get(Company, d.company_id) or db.scalar(select(Company))
    party = db.get(Party, d.party_id)
    dest = db.get(PartyAddress, d.destination_id) if d.destination_id else None
    term = db.get(PaymentTerm, d.payment_term_id) if d.payment_term_id else None

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=doc_label(d), author=company.name if company else "BluBeauty")
    story = []

    # intestazione: azienda a sinistra (con logo), cliente a destra
    left = []
    if company and company.logo_file:
        path = os.path.join(media.media_dir(), f"{company.logo_file}.webp")
        if os.path.exists(path):
            try:
                from PIL import Image as PILImage
                im = PILImage.open(path)
                png = io.BytesIO()
                im.save(png, "PNG")
                png.seek(0)
                ratio = im.height / im.width
                left.append(Image(png, width=40 * mm, height=min(18 * mm, 40 * mm * ratio)))
            except OSError:
                pass
    if company:
        place = " ".join(y for y in (company.zip_code, company.city, f"({company.province})" if company.province else None) if y)
        addr = ", ".join(x for x in (company.address, place) if x)
        left.append(Paragraph(f"<b>{_esc(company.name)}</b><br/>{_esc(addr)}<br/>"
                              f"P.IVA {_esc(company.vat_number)}{' · ' + _esc(company.phone) if company.phone else ''}"
                              f"{'<br/>' + _esc(company.email) if company.email else ''}", small))
    cust = [f"<b>{_esc(party.name)}</b>" if party else ""]
    if party:
        street = " ".join(x for x in (party.address, party.street_number) if x)
        cust.append(_esc(street))
        cust.append(_esc(" ".join(x for x in (party.zip_code, party.city, f"({party.province})" if party.province else None) if x)))
        if party.vat_number:
            cust.append(f"P.IVA {_esc(party.vat_number)}")
        elif party.tax_code:
            cust.append(f"C.F. {_esc(party.tax_code)}")
    if dest:
        cust.append(f"<br/><b>Destinazione:</b> {_esc(dest.address)}, {_esc(dest.city)}")
    head = Table([[left, Paragraph("Spett.le<br/>" + "<br/>".join(c for c in cust if c), normal)]], colWidths=[95 * mm, 85 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOX", (1, 0), (1, 0), 0.5, colors.grey),
                              ("LEFTPADDING", (1, 0), (1, 0), 6)]))
    story += [head, Spacer(1, 6 * mm)]
    number = f"{d.number}/{d.series}" if d.series else str(d.number or "bozza")
    story.append(Paragraph(f"{TITLE.get(d.doc_type, d.doc_type)} n. {number} del {d.doc_date.strftime('%d/%m/%Y')}", h1))
    meta = []
    if term:
        meta.append(f"Pagamento: {_esc(term.description)}")
    if d.reference:
        meta.append(f"Rif.: {_esc(d.reference)}")
    if meta:
        story.append(Paragraph(" · ".join(meta), small))
    story.append(Spacer(1, 3 * mm))

    # righe
    data = [["Codice", "Descrizione", "Q.tà", "Prezzo", "Sc.%", "Importo", "IVA"]]
    from app.anagrafiche.models import Item
    for ln in d.lines:
        item = db.get(Item, ln.item_id) if ln.item_id else None
        desc = _esc(ln.description)
        if ln.lot_number:
            desc += f"<br/><font size=7>Lotto {_esc(ln.lot_number)}{' scad. ' + ln.expiry_date.strftime('%d/%m/%Y') if ln.expiry_date else ''}</font>"
        if ln.serials:
            desc += f"<br/><font size=7>Matricole {_esc(', '.join(ln.serials))}</font>"
        data.append([Paragraph(_esc(item.code if item else ""), small), Paragraph(desc, small),
                     Paragraph(f"{_num(ln.quantity)} {_esc(ln.unit or '')}", right) if ln.quantity else "",
                     Paragraph(_eur(ln.unit_price), right) if ln.quantity else "",
                     Paragraph(_num(ln.discount1), right) if ln.discount1 else "",
                     Paragraph(_eur(ln.line_total), right) if ln.quantity else "",
                     Paragraph(_num(ln.vat_rate) if not ln.vat_nature else ln.vat_nature, right)])
    t = Table(data, colWidths=[24 * mm, 70 * mm, 18 * mm, 20 * mm, 12 * mm, 24 * mm, 12 * mm], repeatRows=1)
    t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, 0), 8), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F8")),
                           ("ALIGN", (2, 0), (-1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#DDDDDD"))]))
    story += [t, Spacer(1, 4 * mm)]

    # riepilogo IVA e totali
    rows = [["Aliquota", "Imponibile", "Imposta"]]
    for s in docs.vat_summary(d):
        rows.append([s["nature"] or f"{_num(s['rate'])}%", _eur(s["taxable"]), _eur(s["vat"])])
    vat_t = Table(rows, colWidths=[22 * mm, 28 * mm, 24 * mm])
    vat_t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 8), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                               ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey)]))
    tot = Table([["Imponibile", _eur(d.taxable_total)], ["IVA", _eur(d.vat_total)], ["Totale", _eur(d.total)]], colWidths=[30 * mm, 32 * mm])
    tot.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                             ("FONTSIZE", (0, 2), (-1, 2), 11), ("LINEABOVE", (0, 2), (-1, 2), 0.75, colors.black)]))
    story.append(Table([[vat_t, tot]], colWidths=[110 * mm, 70 * mm], style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))

    if d.doc_type == "DDT" and d.transport:
        tr = d.transport
        bits = [f"Causale: {_esc(tr.get('causale'))}" if tr.get("causale") else None, f"Porto: {_esc(tr.get('porto'))}" if tr.get("porto") else None,
                f"Trasporto a cura del {_esc(tr.get('a_cura')).lower()}" if tr.get("a_cura") else None,
                f"Mezzo: {_esc(tr.get('vettore'))}" if tr.get("vettore") else None,
                f"Inizio trasporto: {_when(tr.get('inizio'))}" if tr.get("inizio") else None]
        story += [Spacer(1, 4 * mm), Paragraph(" · ".join(b for b in bits if b), small)]
    if d.notes:
        story += [Spacer(1, 3 * mm), Paragraph(f"<b>Note:</b> {_esc(d.notes)}", small)]

    # consegna firmata
    dl = d.delivery or {}
    if dl.get("signature_file") or dl.get("signer_name"):
        when = dl.get("signed_at")
        try:
            when = datetime.fromisoformat(str(when).replace("Z", "+00:00")).astimezone().strftime("%d/%m/%Y %H:%M") if when else ""
        except ValueError:
            when = str(when)
        info = [f"<b>{'Ricevuto da' if d.doc_type != 'NC' else 'Consegnato da'}:</b> {_esc(dl.get('signer_name'))}", f"<b>Data e ora:</b> {_esc(when)}"]
        if dl.get("lat") and dl.get("lon"):
            info.append(f"<b>Posizione:</b> {float(dl['lat']):.5f}, {float(dl['lon']):.5f}")
        sig = ""
        if dl.get("signature_file"):
            path = os.path.join(media.media_dir(), dl["signature_file"])
            if os.path.exists(path):
                sig = Image(path, width=60 * mm, height=22 * mm, kind="proportional")
        box = Table([[Paragraph("<br/>".join(info), small), sig]], colWidths=[100 * mm, 80 * mm])
        box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.grey), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
        story += [Spacer(1, 6 * mm), KeepTogether([Paragraph("<b>Firma del cliente</b>", small), Spacer(1, 1 * mm), box])]

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(15 * mm, 8 * mm, f"{doc_label(d)} · pagina {doc_.page}")
        canvas.drawRightString(195 * mm, 8 * mm, "Documento emesso con BluBeauty")
        canvas.restoreState()

    pdf.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


def file_name(d: Document) -> str:
    num = f"{d.number}-{d.series}" if d.series else str(d.number)
    return f"{TITLE.get(d.doc_type, d.doc_type).replace(' ', '_')}_{num}_{d.doc_date.isoformat()}.pdf"
