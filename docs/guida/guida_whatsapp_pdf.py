"""Guida «Collegare WhatsApp» per il salone: SIM, account Meta, numero, token, approvazione dei messaggi, costi e problemi.
Stessa grafica del manuale (manuale_pdf.py). Uso: python guida_whatsapp_pdf.py [uscita.pdf]"""
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
OUT = sys.argv[1] if len(sys.argv) > 1 else "/home/user/blubeauty/frontend/public/guide/BluBeauty-Guida-WhatsApp.pdf"
IMG = "/home/user/blubeauty/docs/guida/img"
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
    c.drawString(M, PAGE_H - 134 * mm, "Collegare WhatsApp")
    c.setFillColor(GOLD)
    c.rect(M, PAGE_H - 145 * mm, 30 * mm, 1.6 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#d7e3fb"))
    c.setFont("SourceSans3-Regular", 13)
    y = PAGE_H - 160 * mm
    for line in ["Conferme, promemoria, buoni e auguri inviati da soli", "dal numero WhatsApp del salone, con una SIM dedicata:",
                 "guida passo passo, approvazione dei messaggi e costi."]:
        c.drawString(M, y, line)
        y -= 7 * mm
    c.setFont("SourceSans3-SemiBold", 11)
    c.setFillColor(LIGHT)
    c.drawString(M, 28 * mm, "BluCode Informatica · blucodeinformatica.it")
    c.setFillColor(colors.HexColor("#b9c8ea"))
    c.setFont("SourceSans3-Regular", 10)
    c.drawString(M, 22 * mm, "Edizione novembre 2026 · i menu di Meta possono cambiare leggermente nel tempo")
    c.restoreState()


def on_page(c, d):
    c.saveState()
    c.setFillColor(BLUE)
    c.rect(0, PAGE_H - 9 * mm, PAGE_W, 9 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Archivo-Bold", 9)
    c.drawString(M, PAGE_H - 6 * mm, "BluBeauty · Guida WhatsApp")
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


def img(path, caption, width):
    from PIL import Image as PI
    w0, h0 = PI.open(path).size
    h = width * h0 / w0
    if h > 175 * mm:
        width, h = width * 175 * mm / h, 175 * mm
    frame = Table([[Image(path, width=width, height=h)]], style=TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#c9d5ee")),
                  ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0),
                  ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return KeepTogether([Spacer(1, 4), frame, Spacer(1, 4), P(caption, "cap")])


def table(rows, widths):
    t = Table([[P(c) for c in r] for r in rows], colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), PALE), ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d5ee")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


W = PAGE_W - 2 * M
story = [NextPageTemplate("normale"), PageBreak()]
toc = TableOfContents(levelStyles=[S["toc1"], S["toc2"]], dotsMinLevel=0)
story += [P("Indice", "title"), P("Tocca una voce per andare alla pagina.", "lead"), toc]

# 1 ------------------------------------------------------------------------------------------------------------
story += chapter(1, "Come funziona", "BluBeauty manda da solo conferme, promemoria, buoni regalo e auguri dal numero WhatsApp del salone. "
                 "Per farlo usa il servizio ufficiale di Meta (WhatsApp Business Platform): niente telefono acceso in negozio, "
                 "niente rischio di blocco del numero.")
story += [P("In breve, una volta sola:"), steps([
    "Compri una <b>SIM nuova</b> per il salone (serve solo a ricevere il codice di verifica).",
    "Crei l'<b>account Meta Business</b> del salone e colleghi il numero a WhatsApp.",
    "Copi in BluBeauty tre dati: <b>Phone number ID</b>, <b>token di accesso</b> e <b>ID dell'account WhatsApp Business</b>.",
    "In BluBeauty premi <b>Chiedi l'approvazione</b>: Meta controlla i testi dei messaggi (di solito pochi minuti o qualche ora).",
    "Aggiungi una <b>carta di pagamento</b> nell'account Meta: paghi solo i messaggi inviati."]),
    tip("Tempo necessario: 30–60 minuti con il computer, il telefono con la SIM nuova a portata di mano e i dati del salone "
        "(ragione sociale, indirizzo, sito o pagina Facebook/Instagram). Se preferisci, BluCode può farlo con te."),
    *h2("Cosa non fare"),
    warn("Non usare programmi che «comandano» WhatsApp sul telefono o su WhatsApp Web per mandare messaggi in automatico: sono contro le "
         "regole di WhatsApp e il numero viene bloccato, a volte per sempre, insieme alle chat."),
    *h2("Le risposte delle clienti"),
    P("Il numero collegato in questo modo non si usa più dall'app WhatsApp del telefono: le clienti ricevono i messaggi del salone, ma "
      "per ora le loro risposte non si leggono in BluBeauty. Per questo i messaggi contengono sempre il link per spostare o disdire "
      "l'appuntamento. Tieni il numero di telefono del salone ben visibile nel profilo WhatsApp (descrizione: «Per parlare con noi "
      "chiama il …»)."),
]

# 2 ------------------------------------------------------------------------------------------------------------
story += chapter(2, "Prima di iniziare", "Cosa preparare.")
story += [bullets([
    "<b>Una SIM nuova</b> (qualsiasi operatore, anche la più economica). Il numero <b>non deve essere già registrato su WhatsApp</b>. "
    "Puoi usare anche un numero fisso che riceve chiamate: il codice arriva con una telefonata.",
    "<b>Un profilo Facebook personale</b> del titolare: serve solo per accedere a Meta, non viene mostrato alle clienti.",
    "<b>Dati del salone</b>: nome commerciale, indirizzo, e-mail, sito o pagina Facebook/Instagram.",
    "<b>Logo quadrato</b> (immagine dell'account WhatsApp, almeno 640×640).",
    "<b>Carta di credito o debito</b> per pagare i messaggi a Meta.",
    "Utente <b>amministratore</b> in BluBeauty."]),
    tip("Vuoi usare il numero che hai già su WhatsApp? Dovresti prima eliminare l'account WhatsApp da quel numero (nell'app: "
        "Impostazioni › Account › Elimina account) e perderesti le chat. Per questo consigliamo una SIM nuova solo per i messaggi automatici.",
        "Numero già in uso"),
    *h2("Il nome che vedranno le clienti"),
    P("Meta controlla il <b>nome visualizzato</b>: deve essere il nome del salone, uguale (o molto simile) a insegna, sito o pagine social. "
      "Esempio corretto: «Aurora Hair &amp; Beauty». Da evitare: solo parole generiche come «Parrucchiere» o nomi di persona."),
]

# 3 ------------------------------------------------------------------------------------------------------------
story += chapter(3, "Creare l'account e collegare il numero", "Dal computer, su business.facebook.com e developers.facebook.com.")
story += [*h2("1. Account Meta Business del salone"), steps([
    "Vai su <b>business.facebook.com</b> e accedi con il tuo profilo Facebook.",
    "Premi <b>Crea un account</b> (portfolio aziendale): nome del salone, tuo nome, e-mail del salone.",
    "Completa i dati dell'azienda in <b>Impostazioni › Informazioni sull'azienda</b> (indirizzo, sito, telefono)."]),
    *h2("2. App per WhatsApp"), steps([
    "Vai su <b>developers.facebook.com</b> › <b>Le mie app</b> › <b>Crea app</b>.",
    "Come utilizzo scegli <b>Connettiti con i clienti tramite WhatsApp</b> (o tipo <b>Business</b>), nome dell'app per esempio "
    "«BluBeauty Salone Aurora», e collega l'account aziendale creato al passo 1.",
    "Nella pagina dell'app apri <b>WhatsApp › Configurazione API</b> (API Setup)."]),
    *h2("3. Aggiungere il numero della SIM"), steps([
    "In <b>Configurazione API</b> premi <b>Aggiungi numero di telefono</b>.",
    "Scrivi il <b>nome visualizzato</b> del salone, categoria <b>Bellezza, cosmetica e cura personale</b>, descrizione breve.",
    "Inserisci il numero della SIM (+39…) e scegli <b>SMS</b> (o <b>Chiamata</b> per un fisso).",
    "Inserisci il codice a 6 cifre ricevuto: il numero è collegato."]),
    *h2("4. Copiare i due numeri identificativi"),
    P("Sempre in <b>WhatsApp › Configurazione API</b>, scegli il numero appena aggiunto nel campo «Da» e copia:"),
    table([["Dato", "Dove si trova", "Esempio"],
           ["<b>Phone number ID</b>", "Sotto il numero scelto, «Identificativo numero di telefono»", "123456789012345"],
           ["<b>WABA ID</b>", "«Identificativo account WhatsApp Business», nella stessa pagina", "987654321098765"]],
          [W * 0.25, W * 0.5, W * 0.25]),
    Spacer(1, 6),
    warn("Il <b>token temporaneo</b> che vedi in questa pagina dura 24 ore: non usarlo in BluBeauty. Serve il token permanente del passo 5."),
]
story += [*h2("5. Token di accesso permanente"), steps([
    "Vai su <b>business.facebook.com › Impostazioni</b> (Impostazioni dell'azienda) › <b>Utenti › Utenti di sistema</b>.",
    "Premi <b>Aggiungi</b>: nome «BluBeauty», ruolo <b>Amministratore</b>.",
    "Sull'utente creato premi <b>Assegna risorse</b>: l'<b>app</b> del passo 2 (controllo completo) e l'<b>account WhatsApp</b> (controllo completo).",
    "Premi <b>Genera token</b>: scegli l'app, scadenza <b>Mai</b>, autorizzazioni <b>whatsapp_business_messaging</b> e "
    "<b>whatsapp_business_management</b>.",
    "Copia il token (inizia con «EAA…»): <b>si vede una volta sola</b>. Incollalo subito in BluBeauty (capitolo 4)."]),
    tip("Il token è come una password: non mandarlo per e-mail o WhatsApp. In BluBeauty si salva cifrato e non si rilegge più.", "Sicurezza"),
    *h2("6. Metodo di pagamento"), steps([
    "Apri <b>WhatsApp Manager</b> (da business.facebook.com › <b>Account WhatsApp</b>, oppure dal menu dell'app).",
    "In <b>Impostazioni account › Metodo di pagamento</b> aggiungi la carta del salone e i dati di fatturazione.",
    "Meta addebita i messaggi a fine periodo; senza carta i messaggi a pagamento non partono."]),
    *h2("7. Profilo WhatsApp del salone"),
    P("In <b>WhatsApp Manager › Numeri di telefono › Profilo</b> carica il logo, l'indirizzo, gli orari e una descrizione con il numero "
      "da chiamare. È quello che la cliente vede toccando il nome del salone."),
]

# 4 ------------------------------------------------------------------------------------------------------------
story += chapter(4, "Collegare BluBeauty", "Tre dati da incollare, una volta sola.")
story += [steps([
    "In BluBeauty apri <b>Impostazioni del salone</b> e scorri fino al riquadro <b>WhatsApp</b>.",
    "Scegli <b>WhatsApp Business</b>.",
    "Incolla <b>Phone number ID</b>, <b>Token di accesso</b> e <b>ID dell'account WhatsApp Business (WABA ID)</b>.",
    "Premi <b>Salva WhatsApp</b>."]),
    img(f"{IMG}/wa-impostazioni.png", "Impostazioni del salone › WhatsApp, con i tre dati di Meta.", 95 * mm),
]

# 5 ------------------------------------------------------------------------------------------------------------
story += chapter(5, "Far approvare i messaggi", "WhatsApp permette al salone di scrivere per primo solo con testi approvati da Meta (i «modelli»). "
                 "BluBeauty li prepara e li manda a Meta per te.")
story += [steps([
    "Apri <b>Messaggi e punti</b> (Marketing e WhatsApp).",
    "Nel riquadro verde premi <b>Chiedi l'approvazione</b>: partono a Meta tutti i messaggi automatici attivi.",
    "Dopo qualche minuto premi <b>Aggiorna stato</b> (BluBeauty lo controlla comunque da solo ogni ora).",
    "Quando un messaggio è <b>Approvato</b>, parte con il modello e arriva a tutte le clienti."]),
    img(f"{IMG}/wa-approvazione.png", "Lo stato di ogni messaggio: Approvato, In approvazione, Rifiutato, Da inviare a Meta.", 120 * mm),
]
story += [*h2("Cosa vuol dire ogni stato"), table([
    ["Stato", "Significato", "Cosa fare"],
    ["<b>Approvato</b>", "Il messaggio arriva a tutte le clienti.", "Niente."],
    ["<b>In approvazione</b>", "Meta lo sta controllando (minuti, a volte fino a 24 ore).", "Aspetta; intanto arriva solo a chi ha scritto al salone nelle ultime 24 ore."],
    ["<b>Rifiutato</b>", "Meta non l'ha accettato; accanto c'è il motivo.", "Correggi il testo (Testo) e premi <b>Invia a Meta</b>."],
    ["<b>Testo cambiato</b>", "Hai modificato un testo già approvato.", "Premi <b>Invia a Meta</b>: va approvato di nuovo."],
    ["<b>Da inviare a Meta</b>", "Mai mandato (o messaggio attivato dopo).", "Premi <b>Invia a Meta</b> o <b>Chiedi l'approvazione</b>."]],
    [W * 0.2, W * 0.4, W * 0.4]),
    *h2("Consigli per farli approvare al primo colpo"), bullets([
    "Conferme, promemoria, disdette, buoni e pacchetti sono messaggi di <b>servizio</b>: non metterci sconti o promozioni, "
    "altrimenti Meta li considera pubblicità (costano di più) o li rifiuta.",
    "Auguri, richiami, clienti persi e campagne sono <b>marketing</b>: partono solo alle clienti che hanno dato il consenso.",
    "Lascia i segnaposto tra graffe come sono (<b>{nome}</b>, <b>{ora}</b>, <b>{link}</b>…): BluBeauty li trasforma nel formato di Meta.",
    "Niente righe vuote ripetute, niente testo tutto in maiuscolo, niente link accorciati (bit.ly e simili).",
    "Se il testo finisce con un segnaposto, BluBeauty aggiunge «A presto!» alla fine: Meta non accetta un messaggio che finisce con una variabile."]),
    *h2("Le campagne"),
    P("Con WhatsApp Business anche ogni campagna va approvata: quando premi <b>Chiedi l'approvazione e poi invia</b> la campagna resta in "
      "<b>bozza</b>; appena è <b>Approvata</b> compare il pulsante <b>Invia</b> nell'elenco delle campagne. Prepara le campagne qualche ora prima."),
]

# 6 ------------------------------------------------------------------------------------------------------------
story += chapter(6, "Quanto costa", "Meta non chiede un canone: si paga ogni messaggio inviato con un modello, sulla carta del salone. "
                 "È un costo separato dall'abbonamento BluBeauty.")
story += [table([
    ["Tipo", "Messaggi di BluBeauty", "Costo circa (Italia)"],
    ["Servizio (utility)", "conferma, promemoria, disdetta, buono ricevuto, saldo del buono, pacchetto, seduta, scadenza", "0,025 € a messaggio"],
    ["Marketing", "grazie e recensione, richiamo, compleanno, premio, clienti persi, campagne", "0,066 € a messaggio"],
    ["Risposta entro 24 ore", "qualsiasi messaggio dopo che la cliente ha scritto al salone", "gratis"]],
    [W * 0.22, W * 0.5, W * 0.28]),
    Spacer(1, 8),
    P("<b>Esempio</b> per un salone con 300 appuntamenti al mese: conferma e promemoria = 600 messaggi × 0,025 € ≈ <b>15 €</b>; "
      "150 messaggi di marketing (auguri, richiami) × 0,066 € ≈ <b>10 €</b>. Totale <b>circa 25 € al mese</b>."),
    tip("Le tariffe sono di Meta (listino di ottobre 2026) e cambiano più volte l'anno: controlla quelle aggiornate in "
        "WhatsApp Manager › Panoramica › Prezzi. Per spendere meno puoi spegnere i messaggi che non ti servono con l'interruttore accanto a ciascuno.",
        "Prezzi"),
    *h2("Limiti di invio"),
    P("All'inizio Meta permette di scrivere ad almeno <b>250 clienti diverse al giorno</b>, più che sufficienti per un salone. Se il salone "
      "invia campagne grandi, la <b>verifica dell'azienda</b> (Impostazioni dell'azienda › Centro sicurezza, con visura camerale o fattura "
      "intestata) alza il limite a 1.000 e oltre."),
]

# 7 ------------------------------------------------------------------------------------------------------------
story += chapter(7, "Problemi frequenti", "Se qualcosa non va, in BluBeauty trovi lo stato di ogni messaggio in <b>Messaggi e punti › Ultimi messaggi</b> "
                 "e nella scheda della cliente.")
faq = [
    ("Il messaggio risulta «errore» e la cliente non l'ha ricevuto.", "Di solito il modello non è ancora approvato e la cliente non ha scritto al salone "
     "nelle ultime 24 ore. Controlla lo stato in Messaggi e punti e premi <b>Aggiorna stato</b>."),
    ("Errore sul token (scaduto o non valido).", "Hai incollato il token temporaneo o l'utente di sistema non ha l'account WhatsApp tra le risorse. "
     "Rigenera il token (capitolo 3, passo 5) e incollalo di nuovo in Impostazioni del salone."),
    ("«Manca l'ID dell'account WhatsApp Business».", "Copia il WABA ID da WhatsApp › Configurazione API e incollalo in Impostazioni del salone › WhatsApp."),
    ("Il numero risulta già registrato su WhatsApp.", "Elimina l'account WhatsApp da quel numero nell'app del telefono, aspetta qualche minuto e riprova; "
     "oppure usa una SIM nuova."),
    ("Meta rifiuta il nome visualizzato.", "Usa il nome esatto dell'insegna, uguale a quello del sito o della pagina Instagram/Facebook."),
    ("Un messaggio di servizio è diventato «marketing».", "Meta ha trovato nel testo una promozione: togli sconti e offerte dal testo e invialo di nuovo."),
    ("Non arrivano messaggi a una cliente.", "Controlla nella sua scheda che il cellulare sia giusto e che abbia WhatsApp; per auguri e campagne serve il consenso marketing."),
]
for q, a in faq:
    story += [KeepTogether([P(f"<b>{q}</b>"), P(a), Spacer(1, 4)])]
story += [Spacer(1, 10), tip("Per assistenza scrivi a <b>info@blucodeinformatica.it</b>: BluCode può fare con te tutta l'attivazione.", "Assistenza")]

doc = Doc(OUT, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=18 * mm, bottomMargin=20 * mm,
          title="BluBeauty · Collegare WhatsApp", author="BluCode Informatica", subject="Guida al collegamento di WhatsApp Business")
frame = Frame(M, 20 * mm, PAGE_W - 2 * M, PAGE_H - 38 * mm, id="f")
doc.addPageTemplates([PageTemplate("copertina", [Frame(0, 0, PAGE_W, PAGE_H)], onPage=on_cover),
                      PageTemplate("normale", [frame], onPage=on_page)])
doc.multiBuild(story)
print(OUT)
