"""Manuale d'uso di BluBeauty in PDF: copertina, indice cliccabile (con numeri di pagina e segnalibri), capitoli con
schermate, suggerimenti e domande frequenti. Palette e caratteri BluCode."""
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, Image, KeepTogether, ListFlowable, ListItem, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)
from reportlab.platypus.tableofcontents import TableOfContents

SP = "/tmp/claude-0/-home-user/a3d1293f-40b5-5d44-9ac8-a23fb5328f2b/scratchpad"
SHOTS, FONTS = f"{SP}/shots", f"{SP}/manuale/fonts"
OUT = sys.argv[1] if len(sys.argv) > 1 else f"{SP}/manuale/BluBeauty-Manuale.pdf"
LOGO = "/home/user/blubeauty/frontend/public/brand/blubeauty-icon-512.png"
for n in ("Archivo-ExtraBold", "Archivo-Bold", "SourceSans3-Regular", "SourceSans3-SemiBold", "SourceSans3-Italic", "SourceSans3-Bold"):
    pdfmetrics.registerFont(TTFont(n, f"{FONTS}/{n}.ttf"))
pdfmetrics.registerFontFamily("SourceSans3", normal="SourceSans3-Regular", bold="SourceSans3-Bold", italic="SourceSans3-Italic",
                              boldItalic="SourceSans3-Bold")

DARK, BLUE, LIGHT, GOLD = colors.HexColor("#0b2147"), colors.HexColor("#2340a8"), colors.HexColor("#6ec1e4"), colors.HexColor("#f2b413")
INK, MUTED, PALE = colors.HexColor("#1d2433"), colors.HexColor("#5b6578"), colors.HexColor("#eef3fd")
PAGE_W, PAGE_H = A4
M = 20 * mm

base = ParagraphStyle("base", fontName="SourceSans3-Regular", fontSize=10.8, leading=15.5, textColor=INK, spaceAfter=6)
S = {
    "body": base,
    "h1": ParagraphStyle("h1", parent=base, fontName="Archivo-ExtraBold", fontSize=26, leading=31, textColor=DARK, spaceAfter=4),
    "kicker": ParagraphStyle("kicker", parent=base, fontName="SourceSans3-SemiBold", fontSize=10, textColor=BLUE, spaceAfter=2),
    "lead": ParagraphStyle("lead", parent=base, fontSize=12.5, leading=18, textColor=MUTED, spaceAfter=12),
    "h2": ParagraphStyle("h2", parent=base, fontName="Archivo-Bold", fontSize=15, leading=19, textColor=BLUE, spaceBefore=10, spaceAfter=5),
    "cap": ParagraphStyle("cap", parent=base, fontName="SourceSans3-Italic", fontSize=9, leading=12, textColor=MUTED, alignment=TA_CENTER, spaceAfter=10),
    "tip": ParagraphStyle("tip", parent=base, fontSize=10.3, leading=14.5, spaceAfter=0),
    "toc1": ParagraphStyle("toc1", parent=base, fontName="SourceSans3-SemiBold", fontSize=11.5, leading=15.5, spaceBefore=3, spaceAfter=0, textColor=DARK),
    "toc2": ParagraphStyle("toc2", parent=base, fontSize=10, leading=12.6, spaceAfter=0, leftIndent=14, textColor=INK),
    "title": ParagraphStyle("title", parent=base, fontName="Archivo-ExtraBold", fontSize=26, leading=31, textColor=DARK, spaceAfter=4),
}


class Doc(BaseDocTemplate):
    """Ogni titolo (h1, h2) diventa voce dell'indice cliccabile e segnalibro del PDF."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._n = 0

    def afterFlowable(self, f):
        if isinstance(f, Paragraph) and f.style.name in ("h1", "h2"):
            level = 0 if f.style.name == "h1" else 1
            text = f.getPlainText()
            import re
            key = "s" + re.sub(r"[^a-z0-9]+", "-", text.lower())  # stabile tra un passaggio e l'altro
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
            self.notify("TOCEntry", (level, text, self.page, key))


def on_cover(c, d):
    c.saveState()
    steps = 60
    for i in range(steps):  # sfumatura blu della copertina
        t = i / (steps - 1)
        col = colors.Color(DARK.red + (BLUE.red - DARK.red) * t, DARK.green + (BLUE.green - DARK.green) * t, DARK.blue + (BLUE.blue - DARK.blue) * t)
        c.setFillColor(col)
        c.rect(0, PAGE_H * (1 - (i + 1) / steps), PAGE_W, PAGE_H / steps + 1, stroke=0, fill=1)
    c.setStrokeColor(colors.Color(1, 1, 1, alpha=0.12))
    for i in range(7):
        c.circle(PAGE_W + 10 * mm, PAGE_H - 40 * mm, (60 + i * 14) * mm, stroke=1, fill=0)
    c.drawImage(LOGO, M, PAGE_H - 80 * mm, 34 * mm, 34 * mm, mask="auto")
    c.setFillColor(colors.white)
    c.setFont("Archivo-ExtraBold", 40)
    c.drawString(M, PAGE_H - 120 * mm, "BluBeauty")
    c.setFont("Archivo-Bold", 22)
    c.drawString(M, PAGE_H - 134 * mm, "Manuale d'uso")
    c.setFillColor(GOLD)
    c.rect(M, PAGE_H - 145 * mm, 30 * mm, 1.6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#d7e3fb"))
    c.setFont("SourceSans3-Regular", 13)
    y = PAGE_H - 160 * mm
    for line in ["Il gestionale per parrucchieri, barber e centri estetici:", "agenda, prenotazione online, cassa con registratore,",
                 "ricevute, turni, clienti, punti fedeltà e WhatsApp."]:
        c.drawString(M, y, line)
        y -= 7 * mm
    c.setFont("SourceSans3-SemiBold", 11)
    c.setFillColor(LIGHT)
    c.drawString(M, 28 * mm, "BluCode Informatica · blucodeinformatica.it")
    c.setFillColor(colors.HexColor("#b9c8ea"))
    c.setFont("SourceSans3-Regular", 10)
    c.drawString(M, 22 * mm, "Edizione novembre 2026 · le schermate usano i dati dimostrativi del salone «Aurora Hair & Beauty»")
    c.restoreState()


def on_page(c, d):
    c.saveState()
    c.setFillColor(BLUE)
    c.rect(0, PAGE_H - 9 * mm, PAGE_W, 9 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Archivo-Bold", 9)
    c.drawString(M, PAGE_H - 6 * mm, "BluBeauty · Manuale d'uso")
    c.setFont("SourceSans3-Regular", 9)
    c.drawRightString(PAGE_W - M, PAGE_H - 6 * mm, "BluCode Informatica")
    c.setFillColor(MUTED)
    c.drawRightString(PAGE_W - M, 10 * mm, f"{d.page}")
    c.setStrokeColor(colors.HexColor("#dbe3f3"))
    c.line(M, 14 * mm, PAGE_W - M, 14 * mm)
    c.restoreState()


def P(t, s="body"):
    return Paragraph(t, S[s])


def bullets(items):
    return ListFlowable([ListItem(P(i), leftIndent=12, value="•") for i in items], bulletType="bullet", start="•",
                        bulletFontName="SourceSans3-Bold", bulletColor=BLUE, leftIndent=12, spaceAfter=6)


def steps(items):
    return ListFlowable([ListItem(P(i), leftIndent=16) for i in items], bulletType="1", bulletFontName="Archivo-Bold",
                        bulletColor=BLUE, leftIndent=16, spaceAfter=6)


def shot(name, caption, width=None, phone=False):
    from PIL import Image as PI
    path = f"{SHOTS}/{name}.png"
    w0, h0 = PI.open(path).size
    width = width or ((62 * mm) if phone else (PAGE_W - 2 * M))
    h = width * h0 / w0
    maxh = 150 * mm if phone else 120 * mm
    if h > maxh:
        width, h = width * maxh / h, maxh
    img = Image(path, width=width, height=h)
    frame = Table([[img]], style=TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9d5ee")),
                                             ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                             ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return KeepTogether([Spacer(1, 4), frame, Spacer(1, 4), P(caption, "cap")])


def phones(pairs):
    """Due schermate del telefono affiancate."""
    from PIL import Image as PI
    cells, caps = [], []
    for name, cap in pairs:
        w0, h0 = PI.open(f"{SHOTS}/{name}.png").size
        w = 58 * mm
        cells.append(Image(f"{SHOTS}/{name}.png", width=w, height=w * h0 / w0))
        caps.append(P(cap, "cap"))
    t = Table([cells, caps], colWidths=[(PAGE_W - 2 * M) / len(pairs)] * len(pairs))
    t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return KeepTogether([t])


def tip(text, title="Suggerimento", color=BLUE, bg=PALE):
    t = Table([[P(f"<font name='SourceSans3-Bold' color='{color.hexval()}'>{title}.</font> {text}", "tip")]], colWidths=[PAGE_W - 2 * M])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, color),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return KeepTogether([Spacer(1, 3), t, Spacer(1, 8)])


def warn(text):
    return tip(text, "Attenzione", colors.HexColor("#c2410c"), colors.HexColor("#fff4e6"))


def chapter(n, title, lead):
    return [PageBreak(), P(f"CAPITOLO {n}", "kicker"), P(title, "h1"), P(lead, "lead")]


def h2(t):
    return [CondPageBreak(60 * mm), P(t, "h2")]


story = [NextPageTemplate("normale"), PageBreak()]
toc = TableOfContents(levelStyles=[S["toc1"], S["toc2"]], dotsMinLevel=0)
story += [P("Indice", "title"), P("Tocca una voce per andare alla pagina.", "lead"), toc]

# 1 ------------------------------------------------------------------------------------------------------------
story += chapter(1, "Primi passi", "BluBeauty si usa dal browser: sul computer del salone, sul tablet o sul telefono, senza installare nulla.")
story += h2("Entrare nel programma")
story += [P("Apri l'indirizzo del programma che ti abbiamo comunicato (per esempio <b>blubeauty.blucodeinformatica.it</b>), "
            "scrivi la tua email e la password e tocca <b>Accedi</b>. Al primo accesso il programma ti chiede di scegliere una password tua."),
          shot("01-accesso", "La pagina di accesso."),
          tip("Se hai dimenticato la password tocca «Password dimenticata?»: ricevi per email un link valido un'ora per sceglierne una nuova.")]
story += h2("La schermata «Oggi»")
story += [P("È la prima pagina che vedi. In alto ci sono i pulsanti per le cose di tutti i giorni; sotto, gli appuntamenti della giornata "
            "in ordine di orario, ciascuno con il colore dell'operatrice."),
          bullets(["<b>Nuovo appuntamento</b>: prenota in quattro passi (capitolo 2).",
                   "<b>Agenda</b>: la giornata con una colonna per operatrice.",
                   "<b>Cerca cliente</b>: trova una cliente per nome o telefono.",
                   "<b>Incassato oggi</b>: il totale della giornata."]),
          shot("02-oggi", "La schermata «Oggi» con gli appuntamenti della giornata."),
          P("Per ogni appuntamento bastano due tocchi: <b>È arrivata</b> quando la cliente si siede e <b>Incassa</b> quando ha finito. "
            "Con i tre puntini puoi spostarlo, disdirlo o segnare che la cliente non si è presentata.")]
story += h2("Menu semplice e menu completo")
story += [P("Il menu a sinistra è volutamente semplice: poche voci grandi. Se ti serve altro (magazzino, fatture, statistiche, utenti) "
            "attiva <b>Mostra tutte le funzioni</b> in fondo al menu; per tornare indietro attiva <b>Modalità semplice</b>. "
            "Il programma ricorda la scelta su ogni computer."),
          shot("03-menu-completo", "Il menu completo, con il tasto «Schermata principale» e la casella «Cerca funzione».")]
story += h2("Cerca funzione")
story += [P("Nel menu completo, la casella <b>Cerca funzione</b> mostra solo le voci che corrispondono a ciò che scrivi. Funziona anche con "
            "le parole di tutti i giorni e senza accenti: «ferie» trova <i>Turni e assenze</i>, «scontrino» la cassa, «whatsapp» i messaggi, "
            "«logo» le ricevute. <b>Invio</b> apre la prima voce, <b>Esc</b> svuota la casella."),
          shot("04-cerca-funzione", "Scrivendo «ferie» compare subito «Turni e assenze».", width=110 * mm),
          tip("Il tasto blu <b>Schermata principale</b>, in cima al menu, riporta sempre alla pagina iniziale.")]

# 2 ------------------------------------------------------------------------------------------------------------
story += chapter(2, "Gli appuntamenti", "Prendere, spostare e gestire gli appuntamenti, anche mentre sei al telefono.")
story += h2("Nuovo appuntamento in quattro passi")
story += [steps(["<b>Per chi?</b> Scrivi le prime lettere del nome o del telefono. Se la cliente è nuova tocca <b>È una cliente nuova</b> e inserisci nome e cellulare.",
                 "<b>Cosa?</b> Scegli il servizio: sono divisi per categoria, con durata e prezzo.",
                 "<b>Con chi?</b> Scegli l'operatrice oppure <b>La prima libera</b>.",
                 "<b>Quando?</b> Scegli il giorno e tocca uno degli orari liberi, poi <b>Conferma</b>."]),
          shot("05-nuovo-per-chi", "Passo 1: per chi?"),
          shot("06-nuovo-cosa", "Passo 2: il servizio."),
          shot("08-nuovo-quando", "Passo 4: giorno e orario. «Conferma» è anche in alto, accanto al pacchetto."),
          P("Gli orari proposti sono solo quelli davvero liberi: il programma tiene conto dei turni e delle assenze, delle cabine "
            "e del <b>tempo di posa</b>. Durante la posa del colore l'operatrice è libera per un'altra cliente, la poltrona no."),
          shot("09-nuovo-fatto", "Appuntamento confermato: la cliente riceve la conferma su WhatsApp.", width=120 * mm),
          tip("Se la cliente ha il cellulare, riceve subito la conferma su WhatsApp con il link per vedere o disdire, e il giorno prima il promemoria.")]
story += h2("L'agenda")
story += [P("L'agenda mostra la giornata con una colonna per ogni operatrice. Le parti a righe sono i tempi di posa, quelle in grigio le ore "
            "in cui l'operatrice non lavora. Usa le frecce o il calendario per cambiare giorno; tocca uno spazio vuoto per aggiungere un appuntamento lì."),
          shot("10-agenda", "L'agenda del giorno."),
          P("Toccando un appuntamento si apre la scheda: servizi, prezzi, messaggi WhatsApp inviati e i pulsanti <b>Cliente arrivato</b>, "
            "<b>Incassa</b>, <b>Non presentato</b>, <b>Sposta</b> e <b>Disdici</b>."),
          shot("11-appuntamento", "La scheda dell'appuntamento con la conversazione WhatsApp."),
          tip("«Come ha prenotato?» (Ha telefonato, Di persona in salone, Su WhatsApp) serve solo a sapere da dove arrivano le prenotazioni.")]

# 3 ------------------------------------------------------------------------------------------------------------
story += chapter(3, "La prenotazione online", "Le clienti prenotano da sole dal telefono, a qualsiasi ora, e possono disdire senza telefonare.")
story += h2("Come funziona per la cliente")
story += [P("Condividi il link del salone (lo trovi in <i>Impostazioni del salone</i>) su Instagram, Facebook, Google o nel profilo WhatsApp, "
            "oppure stampa il codice QR da tenere in cassa. La cliente:"),
          steps(["sceglie il servizio;", "sceglie l'operatrice, se vuole;", "sceglie giorno e orario tra quelli liberi;",
                 "scrive nome, cognome e cellulare e accetta la privacy (e, se vuole, le offerte)."]),
          phones([("31-prenota-servizi", "Scelta del servizio."), ("33-prenota-orari", "Giorno e orario.")]),
          phones([("34-prenota-dati", "I dati della cliente."), ("35-prenota-confermata", "Prenotazione confermata.")]),
          P("La prenotazione compare subito nella tua agenda e la cliente riceve la conferma su WhatsApp. Con il suo link personale può "
            "rivedere l'appuntamento e <b>disdirlo</b> fino al limite che hai scelto (per esempio 24 ore prima): l'orario torna libero."),
          tip("Nelle impostazioni scegli quanto prima si può prenotare, fino a quanti giorni avanti e fino a quando si può disdire.")]

# 4 ------------------------------------------------------------------------------------------------------------
story += chapter(4, "Incassare", "Scontrino, ricevuta non fiscale e fattura, dall'appuntamento o dalla cassa al banco.")
story += h2("Incassare un appuntamento")
story += [P("Tocca <b>Incassa</b> sull'appuntamento. Vedi servizi e totale; se la cliente ha raggiunto un premio fedeltà compare il pulsante "
            "<b>Usa «…»</b>. Poi tocca come paga: <b>Contanti</b>, <b>Carta</b> o <b>Bancomat</b>. Lo scontrino esce dal registratore telematico."),
          shot("12-incasso", "La finestra d'incasso con il premio fedeltà.", width=125 * mm),
          P("In <b>Altre opzioni</b> puoi aggiungere i prodotti venduti, uno sconto oppure scegliere <b>Vuole la fattura</b>.")]
story += h2("Ricevuta non fiscale al posto dello scontrino")
story += [P("Quando lo scontrino non è dovuto perché l'incasso è già stato certificato (per esempio la cliente usa un <b>buono regalo</b> o una seduta di un <b>pacchetto</b> già pagati con scontrino, oppure paga una <b>fattura già emessa</b>), "
            "scegli <b>Ricevuta non fiscale</b> invece di <i>Scontrino fiscale</i> e indica il motivo. La ricevuta esce sul registratore come "
            "documento non fiscale (o sulla stampante termica) e il motivo è stampato sulla ricevuta. L'incasso resta registrato nel gestionale."),
          shot("13-incasso-ricevuta-non-fiscale", "La scelta «Ricevuta non fiscale» con il motivo.", width=125 * mm),
          warn("Per legge ogni incasso va certificato con lo scontrino (documento commerciale) o con la fattura. Usa la ricevuta non fiscale "
               "solo quando lo scontrino non è dovuto. La <b>vendita</b> di un buono regalo per i servizi del salone di norma va con lo scontrino (buono «monouso»): la ricevuta non fiscale si usa quando il buono viene <b>utilizzato</b>. Nel dubbio chiedi al commercialista. Se non vuoi che i collaboratori la usino, disattivala nella cassa "
               "(<i>Casse e reparti › Consenti la ricevuta non fiscale al posto dello scontrino</i>)."),
          shot("14-incasso-fatto", "Dopo l'incasso: punti aggiornati e stampa della ricevuta per la cliente.", width=110 * mm)]
story += h2("La cassa al banco")
story += [P("Per vendere i prodotti c'è la cassa a tutto schermo (<i>Cassa e prodotti</i>): tasti rapidi, lettore di codici a barre, quantità, "
            "sconti, resi e scelta del cliente. <b>F12</b> apre l'incasso; anche qui puoi scegliere scontrino fiscale o ricevuta non fiscale."),
          shot("24-cassa-prodotti", "La cassa al banco con due prodotti."),
          shot("25-cassa-ricevuta-non-fiscale", "L'incasso con la scelta del documento."),
          P("Dopo ogni vendita, <b>Copia cortesia</b> (o il tasto <b>F1</b>) stampa sul registratore una copia non fiscale dell'ultimo scontrino. "
            "In <b>Scontrini</b> ritrovi le vendite della giornata e puoi ristamparle."),
          shot("26-cassa-dopo", "Dopo la vendita: «Copia di cortesia sul registratore».")]
story += h2("Ricevute: logo e intestazione")
story += [P("In <i>Impostazioni del salone › Ricevute: logo e intestazione</i> decidi come appaiono le ricevute (copia di cortesia e ricevuta non fiscale):"),
          bullets(["<b>Logo</b>: quello dell'azienda, uno caricato apposta per le ricevute oppure nessuno. Sulla stampante termica esce in bianco e nero, alla larghezza che scegli.",
                   "<b>Righe in alto</b>: se le lasci vuote il programma usa ragione sociale, indirizzo, partita IVA e telefono.",
                   "<b>Righe in fondo</b>: saluti, link di prenotazione, social.",
                   "<b>Stampa di prova</b> sulla stampante termica o sul registratore."]),
          shot("27-ricevute", "La pagina «Ricevute» con l'anteprima a destra."),
          shot("anteprima", "La ricevuta non fiscale sulla stampante termica da 80 mm e sui registratori Custom da 80 e 57 mm."),
          tip("Sul registratore il logo e l'intestazione li stampa il registratore stesso, perché sono programmati dal tecnico. "
              "Se vuoi stampare anche le tue righe attiva «Stampa queste righe anche sul registratore».")]

# 5 ------------------------------------------------------------------------------------------------------------
story += chapter(5, "Turni e assenze", "Ferie, malattia, permessi, orari diversi e chiusure del salone, con l'agenda che si adegua da sola.")
story += h2("La griglia dei turni")
story += [P("In <b>Turni e assenze</b> vedi due settimane: per ogni operatrice e giorno l'orario di lavoro. Le eccezioni hanno un colore: "
            "<b>ferie</b> verde, <b>malattia</b> rosso, <b>permesso</b> arancione, <b>orario diverso</b> viola, <b>salone chiuso</b> grigio."),
          shot("18-turni-dopo", "La griglia dei turni con un giorno di ferie.")]
story += h2("Segnare un'assenza o un cambio di turno")
story += [steps(["Tocca la casella dell'operatrice nel giorno che ti interessa (oppure <b>Segna un'assenza</b>).",
                 "Scegli <b>Ferie</b>, <b>Malattia</b>, <b>Permesso</b> (indichi le ore di assenza) o <b>Orario diverso</b> (indichi le ore di lavoro).",
                 "Imposta le date <b>Dal</b> e <b>Al</b>, una nota se vuoi, e tocca <b>Salva</b>."]),
          shot("16-turni-assenza", "La finestra per segnare un'assenza."),
          P("Per i festivi o le ferie estive di tutto il salone usa <b>Chiudi il salone</b>. Agenda e prenotazione online non propongono più "
            "quegli orari. Se c'erano già appuntamenti il programma li elenca, con <b>Avvisa</b> (messaggio WhatsApp già scritto) e <b>Apri</b>."),
          tip("Settimane alterne (per esempio un sabato sì e uno no): nella scheda dell'operatrice, in <i>Servizi e operatori</i>, attiva "
              "«Settimane alterne» e imposta l'orario della settimana B.")]

# 6 ------------------------------------------------------------------------------------------------------------
story += chapter(6, "Clienti, punti e WhatsApp", "Conoscere le clienti, premiarle e farle tornare.")
story += h2("Le clienti")
story += [P("In <b>Clienti</b> trovi l'elenco con telefono, consensi e punti. Nella scheda di ogni cliente: dati e consensi privacy e marketing, "
            "compleanno, <b>raccolta punti</b> con tessera e codice a barre, storico delle visite, <b>schede tecniche</b> (colori, formule, note) "
            "e la conversazione WhatsApp."),
          shot("19-clienti", "L'elenco delle clienti."),
          shot("20-scheda-cliente", "La scheda cliente con punti, tessera e messaggi.")]
story += h2("Raccolta punti e premi")
story += [bullets(["Punti per ogni euro pagato (la regola si cambia in <i>Messaggi e punti</i>).",
                   "Premi a soglia: sconto in euro, sconto in percentuale o servizio in omaggio; si usano in cassa con un tocco.",
                   "Tessera con numero e codice a barre, stampabile in formato carta di credito.",
                   "«Porta un'amica»: chi presenta una nuova cliente riceve punti alla sua prima visita pagata."])]
story += h2("Messaggi automatici e campagne")
story += [P("In <b>Messaggi e punti</b> attivi i messaggi automatici su WhatsApp: conferma, promemoria, disdetta, grazie con richiesta di "
            "recensione, richiamo del servizio (per esempio il colore dopo cinque settimane), auguri di compleanno e messaggio per chi non torna da un po'. "
            "Con le <b>campagne</b> scrivi a gruppi di clienti."),
          shot("21-marketing", "Messaggi automatici e link di prenotazione."),
          warn("Campagne e messaggi promozionali partono solo verso le clienti che hanno dato il <b>consenso marketing</b>.")]

# 7 ------------------------------------------------------------------------------------------------------------
story += chapter(7, "Impostazioni", "Orari, servizi, operatrici, periferiche e utenti.")
story += h2("Impostazioni del salone")
story += [P("Orari di apertura (anche con pausa pranzo), regole della prenotazione online, link e codice QR da condividere, collegamento "
            "con WhatsApp Business e cassa predefinita."),
          shot("28-impostazioni-salone", "Le impostazioni del salone.")]
story += h2("Servizi, operatrici e cabine")
story += [P("Inserisci il listino: per ogni servizio durata, eventuale tempo di posa, prezzo, IVA e chi lo esegue. Per ogni operatrice "
            "colore in agenda, orari personali (turni, giorno libero, settimane alterne) e se è prenotabile online. Le cabine servono per i "
            "servizi che richiedono uno spazio dedicato."),
          shot("29-servizi", "Servizi, operatori e cabine.")]
story += h2("Registratore e stampanti")
story += [P("In <b>Computer e periferiche</b> colleghi il registratore telematico (Epson o Custom) e la stampante termica tramite il programma "
            "<b>BluBeauty Agent</b>, da installare sul computer del salone: scaricalo dalla stessa pagina, abbinalo con il codice e avvialo."),
          shot("30-periferiche", "Il computer del salone con registratore e stampante."),
          bullets(["<b>Registratore Custom</b>: le aliquote IVA si leggono da sole dal registratore (pulsante <b>Prova</b>); scegli la carta da 57 o 80 mm.",
                   "<b>Stampante termica</b>: se gli accenti escono strani (per esempio «piΩ» invece di «più») cambia la <b>Tabella dei caratteri</b> in PC850.",
                   "Ogni lavoro di stampa è nella <b>Coda dei lavori</b>, con l'esito e il pulsante <b>Riprova</b>."])]
story += h2("Utenti e abbonamento")
story += [P("In <i>Utenti</i> (menu completo) crei gli accessi per le collaboratrici con il loro ruolo. In <i>Abbonamento</i> vedi pacchetto, "
            "scadenza e storico, e puoi rinnovare online con carta, PayPal o bonifico.")]

# FAQ ----------------------------------------------------------------------------------------------------------
story += [PageBreak(), P("APPENDICE", "kicker"), P("Domande frequenti", "h1"), Spacer(1, 6)]
faq = [
    ("Il registratore non stampa lo scontrino.", "Controlla che il computer con BluBeauty Agent sia acceso e collegato a internet, e che il registratore sia acceso. "
     "In <i>Computer e periferiche › Coda dei lavori</i> vedi l'errore del registratore (per esempio «carta finita») e puoi premere <b>Riprova</b>."),
    ("La risposta del registratore si è persa: rischio un doppio scontrino?", "No. Il programma chiede al registratore se lo scontrino è uscito e non lo ristampa mai alla cieca."),
    ("Gli accenti sulla stampante termica escono sbagliati.", "In <i>Computer e periferiche</i> modifica la stampante e scegli <b>Tabella dei caratteri: PC850</b>; fai la stampa di prova."),
    ("Una cliente vuole spostare l'appuntamento.", "Apri l'appuntamento in agenda e usa <b>Sposta</b>: riceve la nuova conferma su WhatsApp."),
    ("Un'operatrice è in malattia per qualche giorno.", "In <b>Turni e assenze</b> segna <b>Malattia</b> dal… al…: il programma ti elenca gli appuntamenti da spostare."),
    ("Non trovo una funzione.", "Attiva <b>Mostra tutte le funzioni</b> e scrivila nella casella <b>Cerca funzione</b>."),
    ("Serve la fattura alla cliente.", "Nell'incasso apri <b>Altre opzioni</b> e spunta <b>Vuole la fattura</b> (servono i dati di fatturazione della cliente)."),
]
for q, a in faq:
    story += [KeepTogether([P(f"<b>{q}</b>"), P(a), Spacer(1, 4)])]
story += [Spacer(1, 10), tip("Per assistenza scrivi a <b>info@blucodeinformatica.it</b> o chiama il <b>379 233 3492</b>.", "Assistenza")]

doc = Doc(OUT, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=18 * mm, bottomMargin=20 * mm,
          title="BluBeauty · Manuale d'uso", author="BluCode Informatica", subject="Manuale d'uso di BluBeauty")
frame = Frame(M, 20 * mm, PAGE_W - 2 * M, PAGE_H - 38 * mm, id="f")
doc.addPageTemplates([PageTemplate("copertina", [Frame(0, 0, PAGE_W, PAGE_H)], onPage=on_cover),
                      PageTemplate("normale", [frame], onPage=on_page)])
doc.multiBuild(story)
print(OUT)
