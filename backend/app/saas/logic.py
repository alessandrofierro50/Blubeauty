"""Regole di business degli abbonamenti, separate dal database per poterle testare facilmente."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

# Moduli del gestionale e pacchetto minimo che li include.
MODULES: dict[str, str] = {
    "agenda": "Agenda, prenotazioni online da smartphone e schede clienti",
    "anagrafiche": "Anagrafiche clienti, fornitori e articoli",
    "magazzino": "Magazzino, lotti e matricole",
    "acquisti": "Acquisti e carico merce",
    "vendite": "Preventivi, ordini, DDT e fatture",
    "scadenzario": "Scadenzario, solleciti e liquidità",
    "fatturapa": "Fatturazione elettronica (invio e ricezione tramite SDI)",
    "statistiche_base": "Statistiche di base",
    "pos": "Vendita al banco",
    "periferiche": "Registratore telematico ed etichette",
    "statistiche_avanzate": "Statistiche avanzate e report personalizzabili",
    "contabilita": "Contabilità generale e bilancio",
    "marketing": "Marketing: fidelity card, SMS, WhatsApp ed email",
    "ecommerce": "Negozio online (e-commerce)",
    "tentata_vendita": "Tentata vendita: agenti con furgone, firma del cliente sul tablet",
}

# BluBeauty (parrucchieri, barber, centri estetici) vende due pacchetti — prezzi PROVVISORI del 2026-10-31,
# da confermare dal titolare (vedi progetto_blucode_informatica/blubeauty/STATO.md):
# - AGENDA (19 €/mese): agenda con tempi di posa, prenotazione online da smartphone con disdetta autonoma,
#   conferme WhatsApp, schede clienti;
# - SALONE (39 €/mese): + cassa con registratore telematico e stampante termica, prodotti e magazzino, acquisti,
#   fatture, scadenzario, marketing WhatsApp (messaggi automatici e campagne).
AGENDA_MODULES = ["agenda", "anagrafiche", "statistiche_base"]
SALONE_MODULES = AGENDA_MODULES + ["marketing", "pos", "periferiche", "magazzino", "acquisti", "vendite", "scadenzario"]

PLAN_MODULES: dict[str, list[str]] = {
    "AGENDA": AGENDA_MODULES,
    "SALONE": SALONE_MODULES,
}

# Moduli venduti a parte: in nessun pacchetto, si attivano per azienda dal pannello super amministratore.
EXTRA_MODULES = ["fatturapa"]

# Moduli a catalogo di BluBeauty (menu del cliente, pannello). Gli altri moduli ereditati da BluGest
# (statistiche avanzate, tentata vendita, contabilità, e-commerce) restano nel codice ma non si vendono.
CATALOG_MODULES = [m for m in MODULES if m in set(SALONE_MODULES) | set(EXTRA_MODULES)]

STATUS_LABELS = {
    "prova": "In prova",
    "attivo": "Attivo",
    "in_scadenza": "In scadenza",
    "tolleranza": "Scaduto (tolleranza)",
    "sola_lettura": "Sola lettura",
    "sospeso": "Sospeso",
    "prova_scaduta": "Prova scaduta",
    "programmato": "Non ancora iniziato",
}

EXPIRING_THRESHOLD_DAYS = 30

# Avvisi della prova gratuita (standard comune: 3 e 1 giorno prima e il giorno della fine).
TRIAL_REMINDER_DAYS = [3, 1, 0]

# Valori predefiniti del ciclo di vita, modificabili dal pannello (tabella saas_settings).
LIFECYCLE_DEFAULTS = {"grace_days": 15, "readonly_days": 30, "trial_reminder_days": TRIAL_REMINDER_DAYS}


@dataclass
class SubscriptionLike:
    start_date: date
    end_date: date
    is_trial: bool = False
    grace_days: int = 15
    readonly_days: int = 30


def current_subscription(subs: list, today: date):
    """Il periodo in corso oggi; se non c'è, quello che finisce più tardi."""
    if not subs:
        return None
    active = [s for s in subs if s.start_date <= today <= s.end_date]
    if active:
        return max(active, key=lambda s: s.end_date)
    past = [s for s in subs if s.start_date <= today]
    if past:
        return max(past, key=lambda s: s.end_date)
    return min(subs, key=lambda s: s.start_date)  # solo periodi futuri


def effective_end(subs: list, today: date) -> date | None:
    """Ultima data coperta, considerando anche i rinnovi già inseriti che partono dopo il periodo attuale."""
    cur = current_subscription(subs, today)
    if cur is None:
        return None
    end = cur.end_date
    for s in sorted(subs, key=lambda s: s.start_date):
        if s.start_date <= end + timedelta(days=1) and s.end_date > end:
            end = s.end_date
    return end


def subscription_status(sub, today: date, suspended: bool = False, end: date | None = None) -> str:
    if suspended or sub is None:
        return "sospeso"
    if today < sub.start_date:
        return "programmato"
    end = end or sub.end_date
    days_left = (end - today).days
    if days_left >= 0:
        if sub.is_trial:
            return "prova"
        return "in_scadenza" if days_left <= EXPIRING_THRESHOLD_DAYS else "attivo"
    if sub.is_trial:
        # prova gratuita finita: subito sospesa, senza tolleranza né sola lettura (i dati restano)
        return "prova_scaduta"
    overdue = -days_left
    if overdue <= sub.grace_days:
        return "tolleranza"
    if overdue <= sub.grace_days + sub.readonly_days:
        return "sola_lettura"
    return "sospeso"


def blocked_code(status: str) -> str:
    """Codice dell'errore 402 per chi non ha accesso: uniforme tra i software (standard comune)."""
    return "prova_scaduta" if status == "prova_scaduta" else "abbonamento_sospeso"


def monthly_amount(amount, period: str, start: date, end: date) -> Decimal:
    """Importo del periodo riportato al mese: annuale / 12, personalizzata = importo / giorni × 30."""
    amount = Decimal(str(amount or 0))
    if period == "mensile":
        return amount
    if period == "annuale":
        return amount / 12
    days = (end - start).days + 1
    return amount / days * 30 if days > 0 else Decimal("0")


def access_level(status: str) -> str:
    """'full', 'readonly' oppure 'none'."""
    if status in ("prova", "attivo", "in_scadenza", "tolleranza"):
        return "full"
    if status == "sola_lettura":
        return "readonly"
    return "none"


def next_period(start: date, period: str) -> date:
    """Data di fine per un periodo che inizia in `start`."""
    if period == "mensile":
        return start + relativedelta(months=1) - timedelta(days=1)
    return start + relativedelta(years=1) - timedelta(days=1)


def reminder_to_send(days_left: int, rules: list[int]) -> int | None:
    """Regola da applicare oggi.

    Si prende la regola più vicina che è già "scattata" (giorni_prima >= giorni rimanenti).
    Così, se il job salta un giorno, l'avviso parte comunque il giorno dopo; e non si inviano
    in blocco gli avvisi vecchi (a 15 giorni non arriva anche quello dei 30).
    """
    if days_left < 0:
        return None
    eligible = [r for r in rules if r >= days_left]
    return min(eligible) if eligible else None


def tenant_modules(plan_code: str | None, plan_modules: list[str] | None, extra: list[str]) -> list[str]:
    base = list(plan_modules) if plan_modules else PLAN_MODULES.get(plan_code or "", [])
    return [m for m in MODULES if m in set(base) | set(extra)]


def render_placeholders(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text
