"""Periodi relativi dei report ("questo mese", "ultimi 12 mesi"…): un report salvato resta sempre aggiornato."""

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta


def _month(d: date) -> date:
    return d.replace(day=1)


def _quarter(d: date) -> date:
    return d.replace(month=(d.month - 1) // 3 * 3 + 1, day=1)


PERIODS = {
    "oggi": ("Oggi", lambda t: (t, t)),
    "ieri": ("Ieri", lambda t: (t - timedelta(days=1), t - timedelta(days=1))),
    "ultimi_7_giorni": ("Ultimi 7 giorni", lambda t: (t - timedelta(days=6), t)),
    "ultimi_30_giorni": ("Ultimi 30 giorni", lambda t: (t - timedelta(days=29), t)),
    "settimana_corrente": ("Questa settimana", lambda t: (t - timedelta(days=t.weekday()), t)),
    "settimana_precedente": ("Settimana scorsa", lambda t: (t - timedelta(days=t.weekday() + 7), t - timedelta(days=t.weekday() + 1))),
    "mese_corrente": ("Questo mese", lambda t: (_month(t), t)),
    "mese_precedente": ("Mese scorso", lambda t: (_month(t) - relativedelta(months=1), _month(t) - timedelta(days=1))),
    "trimestre_corrente": ("Questo trimestre", lambda t: (_quarter(t), t)),
    "trimestre_precedente": ("Trimestre scorso", lambda t: (_quarter(t) - relativedelta(months=3), _quarter(t) - timedelta(days=1))),
    "anno_corrente": ("Quest'anno", lambda t: (t.replace(month=1, day=1), t)),
    "anno_precedente": ("Anno scorso", lambda t: (t.replace(year=t.year - 1, month=1, day=1), t.replace(year=t.year - 1, month=12, day=31))),
    "ultimi_12_mesi": ("Ultimi 12 mesi", lambda t: (_month(t) - relativedelta(months=11), t)),
    "prossimi_30_giorni": ("Prossimi 30 giorni", lambda t: (t, t + timedelta(days=30))),
    "prossimi_90_giorni": ("Prossimi 90 giorni", lambda t: (t, t + timedelta(days=90))),
    "ampio": ("Ultimi 5 anni e prossimi 2 (scadenze)", lambda t: (t - relativedelta(years=5), t + relativedelta(years=2))),
}


def resolve(kind: str | None, date_from: date | None = None, date_to: date | None = None, today: date | None = None) -> tuple[date, date]:
    """Periodo relativo → date; "personalizzato" usa le date indicate."""
    t = today or date.today()
    if kind in PERIODS:
        return PERIODS[kind][1](t)
    if date_from and date_to:
        return date_from, date_to
    return PERIODS["ultimi_12_mesi"][1](t)


def describe(kind: str | None, date_from: date | None = None, date_to: date | None = None) -> str:
    if kind in PERIODS:
        return PERIODS[kind][0]
    d1, d2 = resolve(kind, date_from, date_to)
    return f"dal {d1.strftime('%d/%m/%Y')} al {d2.strftime('%d/%m/%Y')}"
