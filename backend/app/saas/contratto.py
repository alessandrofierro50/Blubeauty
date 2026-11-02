"""Documenti dell'acquisto dal sito: contratto di abbonamento (PDF compilato con i dati del cliente) e, per i privati
consumatori, il modulo tipo di recesso. Il testo è una BOZZA da far rivedere a un legale prima dell'uso (vedi docs)."""

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

from app.core.config import get_settings
from app.pagamenti import billing as bl
from app.pagamenti import invoice as inv
from app.pagamenti.pdf import BLU, INK, MUTED, _e, eur

CONTRACT_VERSION = "1.0"

METHOD_NAMES = {"carta": "carta", "paypal": "PayPal", "bonifico": "bonifico"}

CLAUSES = [
    ("Oggetto", "{cedente} (di seguito «BluCode») concede al Cliente il diritto di usare, in modalità online (SaaS), il software "
                "<b>{prodotto}</b>, pacchetto <b>{piano}</b>, e di ricevere l'assistenza prevista dal pacchetto. Il software resta di proprietà di BluCode: "
                "al Cliente spetta un diritto d'uso non esclusivo e non trasferibile, limitato alla durata del contratto e ai limiti del pacchetto."),
    ("Durata e rinnovo", "Il contratto dura dodici mesi dalla data di attivazione, indicata nella ricevuta di pagamento. Alla scadenza non si rinnova "
                         "da solo: BluCode avvisa il Cliente per email e il Cliente può rinnovare dall'area «Abbonamento». Se il rinnovo non arriva, "
                         "valgono il periodo di tolleranza e la sola lettura previsti dai termini di utilizzo, poi l'accesso viene sospeso."),
    ("Corrispettivo e pagamento", "Il canone annuale è di <b>{importo}</b>{bollo_txt}, per un totale di <b>{totale}</b>, pagato in anticipo con carta, PayPal o bonifico. "
                                  "BluCode opera in regime forfettario (art. 1, commi 54-89, L. 190/2014): fattura senza IVA e senza ritenuta d'acconto. "
                                  "La fattura elettronica è emessa subito se si paga con carta o PayPal; se si paga con bonifico, dopo l'accredito sul conto di BluCode. "
                                  "Il canone non è rimborsabile, salvo quanto previsto dalla legge."),
    ("Termini di utilizzo", "Fanno parte del contratto, e il Cliente dichiara di averli letti e accettati, i <b>termini di utilizzo</b> "
                            "(versione {termini}), che regolano accessi, dati, assistenza, sospensione, sola lettura, cancellazione dei dati e responsabilità."),
    ("Dati personali", "Per i dati dei suoi clienti e fornitori caricati nel software il Cliente è titolare del trattamento e BluCode ne è responsabile ai sensi "
                       "dell'art. 28 del Regolamento (UE) 2016/679: li tratta solo per fornire il servizio, con misure di sicurezza adeguate, "
                       "ne cancella o restituisce una copia alla fine del contratto su richiesta. Per i dati del Cliente stesso BluCode è titolare: "
                       "vale l'informativa sulla privacy allegata."),
    ("Assistenza", "L'assistenza è fornita per email, telefono e con il pulsante «Assistenza» del programma, nei giorni e orari lavorativi. "
                   "Il manuale e i video tutorial sono raggiungibili dai link nell'email di conferma."),
    ("Responsabilità", "BluCode risponde dei danni solo per dolo o colpa grave e, negli altri casi, fino all'importo del canone annuale pagato. "
                       "Il Cliente resta responsabile della correttezza dei dati inseriti e degli adempimenti fiscali: il programma è uno strumento di supporto."),
    ("Recesso", "{recesso}"),
    ("Legge e foro", "Il contratto è regolato dalla legge italiana. Per i Clienti professionisti il foro competente è quello di Lecce; "
                     "per i consumatori vale il foro di residenza o domicilio del consumatore."),
]

RECESSO_PRO = ("Il Cliente professionista può non rinnovare alla scadenza; non è previsto recesso anticipato con rimborso del canone.")
RECESSO_CONSUMATORE = ("Il Cliente consumatore ha diritto di recedere entro 14 giorni dalla conclusione del contratto, senza motivo (artt. 52 ss. D.Lgs. 206/2005), "
                       "inviando il modulo allegato o una dichiarazione esplicita a {email}. Se chiede di iniziare subito l'uso del servizio, "
                       "in caso di recesso paga la parte di servizio già fruita, in proporzione; se il servizio è stato eseguito per intero e il Cliente "
                       "ha dato il consenso espresso e ha riconosciuto di perdere il diritto di recesso, il recesso non è più possibile (art. 59 lett. a).")


def _styles():
    base = getSampleStyleSheet()
    n = ParagraphStyle("n", parent=base["Normal"], fontSize=9.5, leading=13, textColor=INK)
    return n, ParagraphStyle("h1", parent=n, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=BLU), \
        ParagraphStyle("h2", parent=n, fontName="Helvetica-Bold", fontSize=10.5, leading=14, spaceBefore=8, textColor=BLU), \
        ParagraphStyle("s", parent=n, fontSize=8, leading=10.5, textColor=MUTED)


def contract_pdf(*, product: str, plan_name: str, amount, stamp, total, billing: dict, causale: str, method: str,
                 terms_version: str, accepted_at: date | None = None) -> bytes:
    s = get_settings()
    c = inv.cedente()
    n, h1, h2, small = _styles()
    consumer = (billing.get("tipo") == "privato")
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"Contratto di abbonamento {product}", author=c["denominazione"] or "BluCode Informatica")
    d = accepted_at or date.today()
    story = [Paragraph(f"Contratto di abbonamento {_e(product)}", h1),
             Paragraph(f"Versione {CONTRACT_VERSION} · stipulato online il {d.strftime('%d/%m/%Y')} · rif. {_e(causale)}", small), Spacer(1, 6 * mm)]
    story += [Paragraph("Le parti", h2),
              Paragraph(f"<b>Fornitore</b>: {_e(c['denominazione'])}, {_e(c['indirizzo'])}, {_e(c['cap'])} {_e(c['comune'])} ({_e(c['provincia'])}), "
                        f"P.IVA {_e(c['piva'])}, C.F. {_e(c['cf'])}, {_e(s.support_email)}.", n),
              Paragraph(f"<b>Cliente</b>: {_e(bl.display_name(billing))}, {_e(billing.get('indirizzo'))}, {_e(billing.get('cap'))} {_e(billing.get('comune'))}"
                        f"{' (' + _e(billing.get('provincia')) + ')' if billing.get('provincia') else ''}"
                        + (f", P.IVA {_e(billing.get('partita_iva'))}" if billing.get("partita_iva") else "")
                        + (f", C.F. {_e(billing.get('codice_fiscale'))}" if billing.get("codice_fiscale") else "")
                        + (f", codice destinatario {_e(billing.get('codice_destinatario'))}" if billing.get("codice_destinatario") else "")
                        + (f", PEC {_e(billing.get('pec'))}" if billing.get("pec") else "") + ".", n)]
    vals = {"cedente": _e(c["denominazione"]), "prodotto": _e(product), "piano": _e(plan_name), "importo": eur(amount),
            "bollo_txt": f" più {eur(stamp)} di rimborso dell'imposta di bollo" if stamp else "", "totale": eur(total),
            "termini": _e(terms_version),
            "recesso": (RECESSO_CONSUMATORE if consumer else RECESSO_PRO).format(email=_e(s.support_email))}
    for i, (title, text) in enumerate(CLAUSES, 1):
        story += [Paragraph(f"{i}. {title}", h2), Paragraph(text.format(**vals), n)]
    story += [Spacer(1, 6 * mm), Paragraph(
        f"Il Cliente ha accettato il contratto e i termini di utilizzo con il modulo di acquisto del sito (accettazione registrata con data, ora e indirizzo IP). "
        f"Metodo di pagamento scelto: {METHOD_NAMES.get(method, 'bonifico')}. "
        "Ai sensi degli artt. 1341 e 1342 c.c. il Cliente professionista approva specificamente le clausole 7 (Responsabilità) e 9 (Legge e foro).", small)]
    if consumer:
        story += [PageBreak(), Paragraph("Modulo tipo di recesso", h1),
                  Paragraph("(da compilare e restituire solo se si desidera recedere dal contratto)", small), Spacer(1, 6 * mm),
                  Paragraph(f"A: {_e(c['denominazione'])}, {_e(c['indirizzo'])}, {_e(c['cap'])} {_e(c['comune'])} - {_e(s.support_email)}", n), Spacer(1, 4 * mm),
                  Paragraph(f"Con la presente io sottoscritto/a notifico il recesso dal contratto di abbonamento {_e(product)} ({_e(causale)}).", n),
                  Spacer(1, 4 * mm), Paragraph("Ordinato il: ____________   Nome e cognome: ______________________________", n),
                  Spacer(1, 3 * mm), Paragraph("Indirizzo: ______________________________________________   Data: ____________", n),
                  Spacer(1, 3 * mm), Paragraph("Firma (solo se il modulo è inviato in versione cartacea): ______________________", n)]
    doc.build(story)
    return buf.getvalue()
