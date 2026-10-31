"""Proforma PDF della fattura dell'abbonamento, allegata alla «Ricevuta di pagamento» mandata al cliente.

Non è la fattura: quella fiscale è l'XML (caricato sul portale o mandato allo SDI). Lo dice il riquadro in fondo,
con il testo del contratto comune. Colori del brand (comune/brand.md): blu #2340a8, inchiostro #0b2147."""

import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.config import get_settings
from app.pagamenti import billing as bl
from app.pagamenti import invoice as inv
from app.pagamenti.models import METHODS, Payment

BLU = colors.HexColor("#2340a8")
INK = colors.HexColor("#0b2147")
MUTED = colors.HexColor("#4a5b75")
LINE = colors.HexColor("#c8d6e6")
PAPER = colors.HexColor("#f4f7fa")
YELLOW = colors.HexColor("#ffc83d")


def eur(v) -> str:
    s = f"{Decimal(v or 0):,.2f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def _e(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def proforma_pdf(p: Payment) -> bytes:
    s = get_settings()
    c = inv.cedente()
    b = p.billing or {}
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=styles["Normal"], fontSize=9.5, leading=12.5, textColor=INK)
    small = ParagraphStyle("s", parent=normal, fontSize=8, leading=10, textColor=MUTED)
    right = ParagraphStyle("r", parent=normal, alignment=TA_RIGHT)
    h1 = ParagraphStyle("h1", parent=normal, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=BLU)
    label = ParagraphStyle("l", parent=small, fontName="Helvetica-Bold", textColor=MUTED)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Proforma {p.invoice_label}", author=c["denominazione"] or "BluCode Informatica")
    story = []

    seller = [Paragraph(f"<b>{_e(c['denominazione'])}</b>", ParagraphStyle("b", parent=normal, fontSize=12, textColor=BLU)),
              Paragraph(_e(f"{c['indirizzo']}, {c['cap']} {c['comune']} ({c['provincia']})"), small),
              Paragraph(_e(f"P.IVA {c['piva']}" + (f" · C.F. {c['cf']}" if c["cf"] else "")), small),
              Paragraph(_e(s.support_email + (f" · {s.support_phone}" if s.support_phone else "")), small)]
    title = [Paragraph("Proforma", h1),
             Paragraph(f"Fattura n. <b>{_e(p.invoice_label)}</b> del {p.invoice_date.strftime('%d/%m/%Y')}", right)]
    t = Table([[seller, title]], colWidths=[105 * mm, 73 * mm])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, 0), 2, BLU), ("BOTTOMPADDING", (0, 0), (-1, 0), 8)]))
    story += [t, Spacer(1, 8 * mm)]

    ids = []
    if b.get("partita_iva"):
        ids.append(f"P.IVA {b['partita_iva']}")
    if b.get("codice_fiscale"):
        ids.append(f"C.F. {b['codice_fiscale']}")
    where = f"{b.get('indirizzo', '')}, {b.get('cap', '')} {b.get('comune', '')}" + (f" ({b['provincia']})" if b.get("provincia") else "")
    sdi = b.get("codice_destinatario") or ""
    customer = [Paragraph("CLIENTE", label), Paragraph(f"<b>{_e(bl.display_name(b))}</b>", normal), Paragraph(_e(where), normal),
                Paragraph(_e(" · ".join(ids)), normal)]
    if sdi or b.get("pec"):
        customer.append(Paragraph(_e(" · ".join(x for x in (f"Codice destinatario {sdi}" if sdi else "",
                                                           f"PEC {b['pec']}" if b.get("pec") else "") if x)), small))
    paid = [Paragraph("PAGAMENTO", label), Paragraph(f"<b>{_e(METHODS.get(p.method, p.method))}</b>", normal),
            Paragraph(f"Pagato il {p.paid_at.strftime('%d/%m/%Y') if p.paid_at else ''}", normal),
            Paragraph(f"Riferimento {_e(p.causale)}", small)]
    box = Table([[customer, paid]], colWidths=[110 * mm, 68 * mm])
    box.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (-1, -1), PAPER),
                             ("BOX", (0, 0), (-1, -1), 0.5, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                             ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [box, Spacer(1, 7 * mm)]

    rows = [[Paragraph("<b>Descrizione</b>", normal), Paragraph("<b>Natura</b>", normal), Paragraph("<b>Importo</b>", right)],
            [Paragraph(_e(inv.line_description(p)), normal), Paragraph(inv.NATURA, normal), Paragraph(eur(p.amount), right)]]
    if Decimal(p.stamp or 0) > 0:
        rows.append([Paragraph("Rimborso imposta di bollo", normal), Paragraph(inv.NATURA, normal), Paragraph(eur(p.stamp), right)])
    lines = Table(rows, colWidths=[128 * mm, 20 * mm, 30 * mm], repeatRows=1)
    lines.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 1, BLU), ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [lines, Spacer(1, 4 * mm)]

    totals = [["Imponibile", eur(Decimal(p.amount) + Decimal(p.stamp or 0))], ["IVA", "0,00 €"]]
    if Decimal(p.stamp_duty or 0) > 0 and Decimal(p.stamp or 0) == 0:
        totals.append(["Bollo virtuale (a carico del cedente)", eur(p.stamp_duty)])
    totals.append(["Totale pagato", eur(p.total)])
    tt = Table(totals, colWidths=[60 * mm, 30 * mm], hAlign="RIGHT")
    tt.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                            ("TEXTCOLOR", (0, 0), (-1, -1), INK), ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                            ("LINEABOVE", (0, -1), (-1, -1), 1, BLU), ("FONTSIZE", (0, -1), (-1, -1), 11)]))
    story += [tt, Spacer(1, 8 * mm)]

    notes = []
    if c["regime"] == "RF19":
        notes.append(Paragraph(_e(inv.FORFETTARIO_TEXT) + ".", small))
    if Decimal(p.stamp_duty or 0) > 0:
        notes.append(Paragraph(_e(inv.STAMP_TEXT) + f" ({eur(p.stamp_duty)}).", small))
    story += notes + [Spacer(1, 6 * mm)]

    warn = Table([[Paragraph(f"<b>{_e(inv.PROFORMA_NOTE)}.</b>", normal)]], colWidths=[178 * mm])
    warn.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 1, YELLOW), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7df")),
                              ("LEFTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story += [warn, Spacer(1, 4 * mm), Paragraph(f"{_e(s.brand_name)} · BluCode Informatica", small)]
    doc.build(story)
    return buf.getvalue()
