"""Dati iniziali: pacchetti, regole di avviso e modelli email (tutti modificabili dal pannello)."""

from decimal import Decimal

from app.saas.logic import PLAN_MODULES

# Prezzi PROVVISORI, da modificare dal pannello super amministratore.
DEFAULT_PLANS = [
    {
        "code": "AGENDA",
        "name": "BluBeauty Agenda",
        "price_month": Decimal("19.00"),
        "price_year": Decimal("190.00"),
        "max_users": 3,
        "max_companies": 1,
        "max_warehouses": 1,
        "max_pos": 0,
        "sort_order": 1,
    },
    {
        "code": "SALONE",
        "name": "BluBeauty Salone",
        "price_month": Decimal("39.00"),
        "price_year": Decimal("390.00"),
        "max_users": 8,
        "max_companies": 1,
        "max_warehouses": 2,
        "max_pos": 2,
        "sort_order": 2,
    },
]
for p in DEFAULT_PLANS:
    p["modules"] = PLAN_MODULES[p["code"]]

# Standard comune (abbonamenti.md §4): 30, 15, 7, 3, 1 giorni prima e il giorno della scadenza. Modificabili dal pannello.
DEFAULT_REMINDER_DAYS = [30, 15, 7, 3, 1, 0]

_STYLE = (
    "font-family:Arial,sans-serif;color:#1b2b45;max-width:560px;margin:auto;"
    "border-top:4px solid #2340a8;padding:24px"
)

DEFAULT_TEMPLATES = [
    {
        "code": "scadenza_avviso",
        "description": "Avviso di scadenza imminente (30, 15, 7, 3, 1 giorni prima)",
        "subject": "Il tuo abbonamento {piano} scade tra {giorni} giorni",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Gentile {{azienda}},</h2>
<p>ti ricordiamo che il tuo abbonamento <b>{{piano}}</b> scade il <b>{{scadenza}}</b>, tra {{giorni}} giorni.</p>
<p>Per continuare a usare {{prodotto}} senza interruzioni rinnova ora: carta, PayPal o bonifico, dalla pagina «Abbonamento».</p>
<p><a href="{{link_rinnovo}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Rinnova ora</a> &nbsp; <a href="{{link_accesso}}" style="color:#2340a8">Accedi a BluBeauty</a></p>
<p style="color:#4a5b75;font-size:13px">Per rinnovare o cambiare piano: {{contatti}}<br>Il team {{prodotto}} · BluCode Informatica</p></div>""",
    },
    {
        "code": "scadenza_oggi",
        "description": "Avviso il giorno della scadenza",
        "subject": "Il tuo abbonamento {piano} scade oggi",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Gentile {{azienda}},</h2>
<p>il tuo abbonamento <b>{{piano}}</b> scade <b>oggi, {{scadenza}}</b>.</p>
<p>Hai ancora {{giorni_tolleranza}} giorni di tolleranza con accesso completo; poi il gestionale
passerà in sola lettura. I tuoi dati restano al sicuro.</p>
<p><a href="{{link_rinnovo}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Rinnova ora</a> &nbsp; <a href="{{link_accesso}}" style="color:#2340a8">Accedi a BluBeauty</a></p>
<p style="color:#4a5b75;font-size:13px">Per rinnovare o cambiare piano: {{contatti}}<br>Il team {{prodotto}} · BluCode Informatica</p></div>""",
    },
    {
        "code": "fine_tolleranza",
        "description": "Ultimo giorno di tolleranza: da domani sola lettura",
        "subject": "Da domani {prodotto} sarà in sola lettura",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Gentile {{azienda}},</h2>
<p>oggi è l'ultimo giorno di tolleranza del tuo abbonamento <b>{{piano}}</b>, scaduto il {{scadenza}}.
Da domani {{prodotto}} sarà in <b>sola lettura</b>: potrai consultare ed esportare i tuoi dati,
ma non emettere nuovi documenti. Dopo {{giorni_sola_lettura}} giorni l'accesso verrà sospeso.</p>
<p><a href="{{link_rinnovo}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Rinnova ora</a> &nbsp; <a href="{{link_accesso}}" style="color:#2340a8">Accedi a BluBeauty</a></p>
<p style="color:#4a5b75;font-size:13px">Per rinnovare o cambiare piano: {{contatti}}<br>Il team {{prodotto}} · BluCode Informatica</p></div>""",
    },
    {
        "code": "sospensione",
        "description": "Sospensione dopo la sola lettura",
        "subject": "Il tuo accesso a {prodotto} è sospeso",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Gentile {{azienda}},</h2>
<p>il tuo abbonamento <b>{{piano}}</b> è scaduto il {{scadenza}} e il periodo di sola lettura è terminato:
l'accesso a {{prodotto}} è <b>sospeso</b>. I tuoi dati restano conservati: rinnova per riprendere da dove eri rimasto.</p>
<p><a href="{{link_rinnovo}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Rinnova ora</a> &nbsp; <a href="{{link_accesso}}" style="color:#2340a8">Vedi il tuo abbonamento</a></p>
<p style="color:#4a5b75;font-size:13px">Per rinnovare o cambiare piano: {{contatti}}<br>Il team {{prodotto}} · BluCode Informatica</p></div>""",
    },
    {
        "code": "prova_avviso",
        "description": "Prova gratuita: avviso 3 e 1 giorno prima della fine",
        "subject": "La tua prova di {prodotto} finisce tra {giorni} giorni",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Gentile {{azienda}},</h2>
<p>la tua prova gratuita di <b>{{prodotto}} {{piano}}</b> finisce il <b>{{scadenza}}</b>, tra {{giorni}} giorni.</p>
<p>Per continuare senza perdere i dati che hai inserito, attiva l'abbonamento con «Rinnova ora» (carta, PayPal o bonifico).</p>
<p><a href="{{link_rinnovo}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Rinnova ora</a> &nbsp; <a href="{{link_accesso}}" style="color:#2340a8">Accedi a BluBeauty</a></p>
<p style="color:#4a5b75;font-size:13px">Per rinnovare o cambiare piano: {{contatti}}<br>Il team {{prodotto}} · BluCode Informatica</p></div>""",
    },
    {
        "code": "prova_oggi",
        "description": "Prova gratuita: ultimo giorno",
        "subject": "Oggi è l'ultimo giorno della tua prova di {prodotto}",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Gentile {{azienda}},</h2>
<p>oggi, {{scadenza}}, è l'ultimo giorno della tua prova gratuita di <b>{{prodotto}} {{piano}}</b>.</p>
<p>Da domani l'accesso sarà sospeso. I dati restano conservati per 30 giorni: attiva l'abbonamento per ritrovarli.</p>
<p><a href="{{link_rinnovo}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Rinnova ora</a> &nbsp; <a href="{{link_accesso}}" style="color:#2340a8">Accedi a BluBeauty</a></p>
<p style="color:#4a5b75;font-size:13px">Per rinnovare o cambiare piano: {{contatti}}<br>Il team {{prodotto}} · BluCode Informatica</p></div>""",
    },
    {
        "code": "prova_scaduta",
        "description": "Prova gratuita terminata: accesso sospeso",
        "subject": "La tua prova di {prodotto} è terminata",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Gentile {{azienda}},</h2>
<p>la tua prova gratuita di <b>{{prodotto}} {{piano}}</b> è terminata il {{scadenza}} e l'accesso è sospeso.</p>
<p>I tuoi dati restano conservati per 30 giorni: se attivi l'abbonamento riparti esattamente da dove eri.</p>
<p><a href="{{link_rinnovo}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Rinnova ora</a> &nbsp; <a href="{{link_accesso}}" style="color:#2340a8">Vedi il tuo abbonamento</a></p>
<p style="color:#4a5b75;font-size:13px">Per rinnovare o cambiare piano: {{contatti}}<br>Il team {{prodotto}} · BluCode Informatica</p></div>""",
    },
    {
        "code": "attivazione_utente",
        "description": "Invito al primo accesso per un nuovo utente",
        "subject": "Benvenuto in BluBeauty - attiva il tuo account",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Benvenuto, {{nome}}!</h2>
<p>È stato creato il tuo account BluBeauty per <b>{{ragione_sociale}}</b>.</p>
<p><a href="{{link_attivazione}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Scegli la tua password</a></p>
<p style="color:#4a5b75;font-size:13px">Il team BluBeauty</p></div>""",
    },
    {
        "code": "credenziali_accesso",
        "description": "Credenziali di accesso con password provvisoria (nuova azienda, prova gratuita, password rigenerata)",
        "subject": "Le tue credenziali per BluBeauty",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Benvenuto, {{nome}}!</h2>
<p>Il tuo accesso a BluBeauty per <b>{{ragione_sociale}}</b> è pronto.</p>
<table style="margin:12px 0;border-collapse:collapse">
<tr><td style="padding:4px 12px 4px 0;color:#4a5b75">Indirizzo</td><td><a href="{{link_accesso}}">{{link_accesso}}</a></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#4a5b75">Nome utente</td><td><b>{{email}}</b></td></tr>
<tr><td style="padding:4px 12px 4px 0;color:#4a5b75">Password provvisoria</td><td><b style="font-family:monospace;font-size:16px">{{password}}</b></td></tr>
</table>
<p>{{periodo}}</p>
{{termini}}
<p>Al primo accesso ti chiederemo di scegliere una password tua.</p>
<p><a href="{{link_accesso}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Accedi a BluBeauty</a></p>
<p style="color:#4a5b75;font-size:13px">Se non hai richiesto tu questo accesso, ignora questa email. Il team BluBeauty</p></div>""",
    },
    {
        "code": "recupero_password",
        "description": "Link per reimpostare la password dimenticata",
        "subject": "Reimposta la password di BluBeauty",
        "body": f"""<div style="{_STYLE}">
<h2 style="color:#2340a8">Ciao {{nome}},</h2>
<p>abbiamo ricevuto una richiesta per reimpostare la password di BluBeauty.</p>
<p><a href="{{link_reimposta}}" style="background:#2340a8;color:#fff;padding:10px 18px;
border-radius:6px;text-decoration:none">Scegli una nuova password</a></p>
<p>Il link vale {{minuti}} minuti e si può usare una sola volta.</p>
<p style="color:#4a5b75;font-size:13px">Se non sei stato tu, ignora questa email: la password attuale resta valida.</p></div>""",
    },
]
